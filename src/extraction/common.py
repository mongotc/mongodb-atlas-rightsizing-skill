"""
Shared Atlas API client, metric definitions and topology utilities used by
every per-type extractor.

Contents:
  - AtlasClient / AtlasAPIError    auth (OAuth service account or legacy
                                   digest), retry/backoff on 429/5xx,
                                   pagination, errors raised (not swallowed)
  - HOST_METRICS / DISK_METRICS /
    SEARCH_METRICS                 default metric lists for each measurements
                                   endpoint, built from constants/
  - SHARED_TIERS                   Atlas tiers that don't expose hardware
                                   measurements (M0/M2/M5/Flex/Serverless)
  - fetch_measurements             metric-tolerant fetch: drops metrics Atlas
                                   rejects as INVALID_METRIC_NAME and retries
  - fetch_node_metrics             one-process host + per-disk bundle
  - cluster_host_keys,
    process_matches,
    group_processes_by_replica_set,
    node_label, node_hosts         cluster/process topology helpers
  - tier_info, normalize_tier      tier detection (dedicated + sharded shapes)

Kept API-compatible with the equivalents in scripts/rightsizing.py so both
can coexist while the extraction package is being adopted.
"""

import os
import re
import sys
import time
import requests
from requests.auth import HTTPDigestAuth

# Make src/ importable so `constants.tiers` resolves regardless of whether
# this module is loaded as `src.extraction.common` (via __init__.py) or as
# `common` (when a CLI file in this directory runs and Python auto-adds
# src/extraction/ to sys.path but not src/).
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from constants.tiers import SHARED_TIERS, normalize_tier, parse_instance_size  # noqa: E402
# Metric catalogs are maintained in constants/ as the single source of truth —
# names + units for every process type. The extractor uses the keys as the
# default metric lists for its three fetch paths. If Atlas rejects any name
# in a request, fetch_measurements drops it and retries (INVALID_METRIC_NAME
# handling below), so unused-per-topology metrics are safe to leave in.
from constants.atlas_mongo_metrics import (  # noqa: E402
    HARDWARE_METRICS as _MONGO_HARDWARE,
    STATUS_METRICS as _MONGO_STATUS,
    DISK_METRICS as _MONGO_DISK,
)
from constants.atlas_search_metrics import HARDWARE_METRICS as _SEARCH_HARDWARE  # noqa: E402


ATLAS_BASE = "https://cloud.mongodb.com/api/atlas/v2"
TOKEN_URL = "https://cloud.mongodb.com/api/oauth/token"
# Pinned so a newer default API version can't change response shapes underneath us.
API_VERSION_HEADER = {"Accept": "application/vnd.atlas.2025-03-12+json"}


# Default metric lists for the three measurements endpoints. Keys come from
# constants/ (atlas_mongo_metrics for mongod/disk, atlas_search_metrics for FTS).
# fetch_node_metrics accepts a host_metrics= override — see extract_shard_data
# which passes atlas_mongos_metrics.ALL_METRICS for SHARD_MONGOS processes.
#
# Endpoint mapping:
#   HOST_METRICS   -> /groups/{gid}/processes/{procId}/measurements           (m=NAME, repeated)
#   DISK_METRICS   -> /groups/{gid}/processes/{procId}/disks/{part}/measurements
#   SEARCH_METRICS -> /groups/{gid}/hosts/{procId}/fts/metrics/measurements   (metrics=NAME, repeated;
#                                                                             response in hardwareMeasurements[])
HOST_METRICS = list(_MONGO_HARDWARE) + list(_MONGO_STATUS)
DISK_METRICS = list(_MONGO_DISK)
SEARCH_METRICS = list(_SEARCH_HARDWARE)

# CORE_HOST_METRICS / CORE_DISK_METRIC (the "insufficient-data" invariants)
# live in rightsizing/node_eval.py — they encode verdict business rules, not
# Atlas's offer surface, and only node_eval reads them.
#
# SHARED_TIERS is imported from constants.tiers (single source of truth).


# ---------------------------------------------------------------------------
# Atlas API client
# ---------------------------------------------------------------------------

class AtlasAPIError(Exception):
    pass


class AtlasClient:
    """requests wrapper: auth (with OAuth token refresh), retry with backoff on
    429/5xx, pagination, and failures raised as AtlasAPIError instead of
    being swallowed."""

    RETRY_STATUSES = (429, 500, 502, 503, 504)

    def __init__(self, session=None, max_retries=5, timeout=30, sleep=time.sleep, env=None):
        env = os.environ if env is None else env
        self.session = session or requests.Session()
        self.session.headers.update(API_VERSION_HEADER)
        self.max_retries = max_retries
        self.timeout = timeout
        self._sleep = sleep
        self._client_id = env.get("ATLAS_CLIENT_ID")
        self._client_secret = env.get("ATLAS_CLIENT_SECRET")
        self._token_expires_at = 0.0
        public_key, private_key = env.get("ATLAS_PUBLIC_KEY"), env.get("ATLAS_PRIVATE_KEY")
        if self._uses_oauth():
            self._refresh_token()
        elif public_key and private_key:
            self.session.auth = HTTPDigestAuth(public_key, private_key)
        else:
            raise AtlasAPIError(
                "No credentials found. Set ATLAS_CLIENT_ID/ATLAS_CLIENT_SECRET "
                "(service account) or ATLAS_PUBLIC_KEY/ATLAS_PRIVATE_KEY "
                "(API key) in the environment."
            )

    def _uses_oauth(self):
        return bool(self._client_id and self._client_secret)

    def _refresh_token(self):
        resp = self.session.post(
            TOKEN_URL,
            auth=(self._client_id, self._client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
            timeout=self.timeout,
        )
        if not resp.ok:
            raise AtlasAPIError(
                f"OAuth token request failed ({resp.status_code}): {resp.text[:300]}"
            )
        body = resp.json()
        self.session.headers["Authorization"] = f"Bearer {body['access_token']}"
        # Service-account tokens last an hour; refresh a minute early so long
        # audits don't 401 mid-run.
        self._token_expires_at = time.time() + float(body.get("expires_in", 3600)) - 60

    def _backoff(self, attempt, retry_after):
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                pass
        return min(2 ** attempt, 30)

    def get(self, path, params=None):
        url = path if path.startswith("http") else f"{ATLAS_BASE}{path}"
        refreshed_after_401 = False
        for attempt in range(self.max_retries + 1):
            if self._uses_oauth() and time.time() >= self._token_expires_at:
                self._refresh_token()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt == self.max_retries:
                    raise AtlasAPIError(f"Network error on {path}: {e}")
                self._sleep(self._backoff(attempt, None))
                continue
            if resp.status_code == 401 and self._uses_oauth() and not refreshed_after_401:
                self._refresh_token()
                refreshed_after_401 = True
                continue
            if resp.status_code in self.RETRY_STATUSES and attempt < self.max_retries:
                self._sleep(self._backoff(attempt, resp.headers.get("Retry-After")))
                continue
            if not resp.ok:
                raise AtlasAPIError(
                    f"Atlas API error {resp.status_code} on {path}: {resp.text[:500]}"
                )
            return resp.json()
        raise AtlasAPIError(f"Gave up on {path} after {self.max_retries} retries")

    def get_all(self, path, params=None, items_per_page=500):
        """Follow Atlas pagination and return every item in `results`."""
        params = dict(params or {})
        params.update({"itemsPerPage": items_per_page, "includeCount": "true"})
        items, page = [], 1
        while True:
            params["pageNum"] = page
            data = self.get(path, dict(params))
            batch = data.get("results", [])
            items.extend(batch)
            total = data.get("totalCount")
            if not batch or len(batch) < items_per_page or (total is not None and len(items) >= total):
                return items
            page += 1


# ---------------------------------------------------------------------------
# Measurement fetching (metric-tolerant)
# ---------------------------------------------------------------------------

def _series(data):
    """Measurements response -> {metric name: [(timestamp, value), ...]} with nulls dropped."""
    out = {}
    for m in data.get("measurements", []):
        out[m["name"]] = [
            (dp["timestamp"], dp["value"])
            for dp in m.get("dataPoints", [])
            if dp.get("value") is not None
        ]
    return out


_INVALID_METRIC_RE = re.compile(r'"parameters"\s*:\s*\[\s*"([^"]+)"')


def fetch_measurements(client, measurements_path, query, metric_names):
    """Fetch a measurements endpoint, dropping metrics Atlas rejects as
    INVALID_METRIC_NAME and retrying. Needed because a process's supported
    metric set depends on its role (mongos routers, for example, don't expose
    WiredTiger cache or global-lock metrics) and Atlas returns 404 on the
    first unknown name rather than ignoring it."""
    remaining = list(metric_names)
    while remaining:
        try:
            return _series(client.get(measurements_path, query + [("m", m) for m in remaining]))
        except AtlasAPIError as e:
            msg = str(e)
            if "INVALID_METRIC_NAME" not in msg:
                raise
            match = _INVALID_METRIC_RE.search(msg)
            if not match or match.group(1) not in remaining:
                raise
            remaining.remove(match.group(1))
    return {}


def fetch_node_metrics(client, group_id, process_id, window, host_only=False,
                       host_metrics=None):
    """{"host": {metric: series}, "disks": {partition: {metric: series}}} for one process.

    host_metrics overrides the default HOST_METRICS list — used for mongos
    routers (pass atlas_mongos_metrics.ALL_METRICS.keys()) so routers get
    their full catalog instead of the mongod-biased default (which captures
    only ~7 of ~97 mongos metrics after Atlas drops the WT-only names).

    Disk-partition metrics are fetched with `window["disk"]["period"]` when
    present (default: same as host). Atlas resets per-partition series under
    new device names on fleet maintenances, so a wider disk window makes it
    more likely the pre-rename series is still joinable."""
    base = f"/groups/{group_id}/processes/{process_id}"
    host_query = [("granularity", window["granularity"]), ("period", window["period"])]
    disk_window = window.get("disk") or {}
    disk_query = [("granularity", window["granularity"]),
                  ("period", disk_window.get("period", window["period"]))]
    host = fetch_measurements(client=client, measurements_path=f"{base}/measurements",
                              query=host_query,
                              metric_names=list(host_metrics) if host_metrics is not None else HOST_METRICS)
    disks = {}
    if not host_only:
        for partition in client.get_all(f"{base}/disks"):
            name = partition.get("partitionName")
            if name:
                disks[name] = fetch_measurements(
                    client=client,
                    measurements_path=f"{base}/disks/{name}/measurements",
                    query=disk_query, metric_names=DISK_METRICS,
                )
    return {"host": host, "disks": disks}


def _hardware_series(data):
    """Same shape as `_series` but reads from `hardwareMeasurements`, which is
    the schema the FTS metrics endpoint returns."""
    out = {}
    for m in data.get("hardwareMeasurements", []):
        out[m["name"]] = [
            (dp["timestamp"], dp["value"])
            for dp in m.get("dataPoints", [])
            if dp.get("value") is not None
        ]
    return out


def fetch_fts_measurements(client, group_id, process_id, window, metric_names=None):
    """Atlas Search (FTS / mongot) metrics for one mongod host.

    Endpoint / query shape differ from the standard measurements endpoint:
      - path: /groups/{gid}/hosts/{procId}/fts/metrics/measurements
              (NOT /groups/{gid}/processes/{procId}/measurements)
      - param: metrics=NAME repeated (NOT m=NAME)
      - response: hardwareMeasurements[] (NOT measurements[])

    The INVALID_METRIC_NAME error shape is identical, so the same
    drop-and-retry loop applies. `metric_names` defaults to SEARCH_METRICS."""
    metric_names = list(metric_names if metric_names is not None else SEARCH_METRICS)
    path = f"/groups/{group_id}/hosts/{process_id}/fts/metrics/measurements"
    query = [("granularity", window["granularity"]), ("period", window["period"])]
    remaining = list(metric_names)
    while remaining:
        try:
            data = client.get(path, query + [("metrics", m) for m in remaining])
            return _hardware_series(data)
        except AtlasAPIError as e:
            msg = str(e)
            if "INVALID_METRIC_NAME" not in msg:
                raise
            match = _INVALID_METRIC_RE.search(msg)
            if not match or match.group(1) not in remaining:
                raise
            remaining.remove(match.group(1))
    return {}


def fetch_search_metrics_for_node(client, group_id, process_id, window):
    """FTS metrics for one mongod host, keyed the same way as the mongod
    node's `host` dict — so callers can shove it under
    `node['data']['fts']` and treat it symmetrically with `data['host']`."""
    return fetch_fts_measurements(client=client, group_id=group_id,
                                  process_id=process_id, window=window)


# ---------------------------------------------------------------------------
# Cluster / process topology
# ---------------------------------------------------------------------------

_HOST_RE = re.compile(r"^(?P<prefix>.+)-(?:shard|config)-\d+-\d+(?P<domain>\..+)$")


def _host_key(name):
    """'cluster0-shard-00-01.abcde.mongodb.net:27017' -> ('cluster0', '.abcde.mongodb.net')."""
    m = _HOST_RE.match((name or "").lower().split(":")[0])
    return (m.group("prefix"), m.group("domain")) if m else None


def _bare_host(name):
    return (name or "").lower().split(":")[0]


def cluster_host_keys(cluster_cfg):
    """(prefix, domain) pairs for the hosts in the cluster's standard connection string."""
    std = (cluster_cfg.get("connectionStrings") or {}).get("standard") or ""
    if not std:
        return set()
    hosts = std.split("://", 1)[-1].split("/", 1)[0].split(",")
    return {k for k in (_host_key(h) for h in hosts) if k}


def process_matches(proc, host_keys, cluster_name):
    """Exact match on host prefix + domain, so 'prod' never picks up
    'prod-analytics' or 'prod2'. Falls back to an exact '<cluster name>-shard-'
    / '-config-' prefix when the cluster response has no parseable connection
    string."""
    keys = [_host_key(proc.get(f)) for f in ("userAlias", "hostname", "id")]
    keys = [k for k in keys if k]
    if host_keys:
        return any(k in host_keys for k in keys)
    return any(k[0] == cluster_name.lower() for k in keys)


def group_processes_by_replica_set(procs):
    """Split a cluster's processes into per-replica-set groups (each shard and
    the config server is its own replica set) plus mongos routers, which have
    no replicaSetName."""
    shard_groups, routers = {}, []
    for p in procs:
        rs_name = p.get("replicaSetName")
        if rs_name and p.get("typeName") != "SHARD_MONGOS":
            shard_groups.setdefault(rs_name, []).append(p)
        else:
            routers.append(p)
    return shard_groups, routers


def node_label(proc):
    alias = proc.get("userAlias") or proc.get("hostname") or proc.get("id") or "unknown"
    short = alias.split(".")[0]
    port = proc.get("port")
    return f"{short}:{port}" if port else short


def node_hosts(proc):
    return sorted({_bare_host(proc.get(f)) for f in ("userAlias", "hostname", "id") if proc.get(f)})


# ---------------------------------------------------------------------------
# Tier detection
# ---------------------------------------------------------------------------

# normalize_tier is imported from constants.tiers (single source of truth).


def tier_info(cluster_cfg):
    """Tier(s), provisioned IOPS and auto-scaling settings across every region
    config.

    Dedicated replica sets nest instanceSize / diskIOPS under electableSpecs.
    Sharded clusters (v2 API) put them directly on the regionConfig. Check both."""
    tiers, iops, notes = set(), set(), []
    autoscaling = {"compute": None, "disk": False}
    for spec in cluster_cfg.get("replicationSpecs", []):
        for rc in spec.get("regionConfigs", []):
            electable = rc.get("electableSpecs") or {}
            instance_size = electable.get("instanceSize") or rc.get("instanceSize")
            if instance_size:
                tiers.add(instance_size)
            disk_iops = electable.get("diskIOPS")
            if disk_iops is None:
                disk_iops = rc.get("diskIOPS")
            if disk_iops is not None:
                iops.add(disk_iops)
            for kind in ("readOnlySpecs", "analyticsSpecs"):
                other = rc.get(kind) or {}
                if other.get("nodeCount") and other.get("instanceSize") not in (None, instance_size):
                    notes.append(
                        f"{kind[:-5]} nodes run {other['instanceSize']} (electable nodes run "
                        f"{instance_size}); they are evaluated against the same thresholds."
                    )
            scaling = rc.get("autoScaling") or {}
            compute = scaling.get("compute") or {}
            if compute.get("enabled"):
                autoscaling["compute"] = compute
            if (scaling.get("diskGB") or {}).get("enabled"):
                autoscaling["disk"] = True
    return sorted(tiers) or ["UNKNOWN"], sorted(iops), autoscaling, sorted(set(notes))


def _summarize_regions(cluster_cfg):
    """One row per regionConfig with the four axes Atlas encodes in
    `instanceSize` (base tier, class, storage class, generation) plus the
    cloud provider and region. Prefers `effectiveElectableSpecs` so autoscale
    drift is reflected; falls back to `electableSpecs` (requested) and then
    the regionConfig-level `instanceSize` for sharded (v2 API) shapes.
    See Atlas Admin API HardwareSpec20240805 enum (checked 2026-10-06)."""
    rows = []
    for spec in (cluster_cfg or {}).get("replicationSpecs", []):
        for rc in spec.get("regionConfigs", []):
            effective = rc.get("effectiveElectableSpecs") or {}
            electable = rc.get("electableSpecs") or {}
            instance_size = (
                effective.get("instanceSize")
                or electable.get("instanceSize")
                or rc.get("instanceSize")
            )
            electable_count = (
                effective.get("nodeCount")
                or electable.get("nodeCount")
                or rc.get("nodeCount")
                or 0
            )
            read_only_count = (
                (rc.get("readOnlySpecs") or {}).get("nodeCount") or 0
            )
            analytics_count = (
                (rc.get("analyticsSpecs") or {}).get("nodeCount") or 0
            )
            node_count = electable_count + read_only_count + analytics_count
            # Per-regionConfig provisioned IOPS. Prefer effectiveElectableSpecs
            # (reflects autoscale drift) then electableSpecs, then the
            # regionConfig-level field (sharded shape). None = not reported.
            disk_iops = (
                effective.get("diskIOPS")
                if effective.get("diskIOPS") is not None else
                electable.get("diskIOPS")
                if electable.get("diskIOPS") is not None else
                rc.get("diskIOPS")
            )
            # Configured storage. Atlas 2024-05-30+ moved diskSizeGB out of the
            # top-level cluster field and nested it under electableSpecs; the
            # top-level field is absent/null on newer-API responses. Prefer
            # effective → electable → regionConfig to match the IOPS lookup.
            disk_size_gb = (
                effective.get("diskSizeGB")
                if effective.get("diskSizeGB") is not None else
                electable.get("diskSizeGB")
                if electable.get("diskSizeGB") is not None else
                rc.get("diskSizeGB")
            )
            # EBS volume type (AWS only; GCP/Azure return None).
            ebs_volume_type = (
                effective.get("ebsVolumeType")
                or electable.get("ebsVolumeType")
                or rc.get("ebsVolumeType")
            )
            base, cls, storage, gen = parse_instance_size(instance_size)
            rows.append({
                "provider": rc.get("providerName"),
                "backing_provider": rc.get("backingProviderName"),
                "region": rc.get("regionName"),
                "instance_size": instance_size,
                "base_tier": base,
                "class": cls,
                "storage": storage,
                "generation": gen,
                "node_count": node_count,
                "electable_count": electable_count,
                "read_only_count": read_only_count,
                "analytics_count": analytics_count,
                "disk_iops": disk_iops,
                "disk_size_gb": disk_size_gb,
                "ebs_volume_type": ebs_volume_type,
            })
    return rows


def summarize_config(cluster_cfg):
    """Extract the small subset of cluster config the rightsizing evaluator
    needs. Persisted as the top-level `config` block on every extraction.json
    so the evaluator runs offline (no Atlas API access at eval time).

    Returns:
      {
        "cluster_type": "REPLICASET" | "SHARDED" | "GEOSHARDED" | None,
        "tiers": ["M10", ...],           # tier_info()[0]; raw instance_size strings
        "provisioned_iops": [3000, ...], # tier_info()[1]; empty when Atlas
                                         # doesn't report diskIOPS
        "disk_size_gb": 200,             # cluster-wide configured storage
                                         # (Atlas cluster.diskSizeGB)
        "autoscaling": {"compute": {...}|None, "disk": bool},
        "tier_notes": ["analytics nodes run M20 ...", ...],
        "regions": [                     # per-regionConfig breakdown with the
          {                              # four axes Atlas encodes in instanceSize
            "provider": "GCP",           # (base_tier, class, storage, generation)
            "backing_provider": None,
            "region": "CENTRAL_US",
            "instance_size": "M40_GEN_2",
            "base_tier": "M40",
            "class": "general",          # 'general' | 'low_cpu'
            "storage": "standard",       # 'standard' | 'nvme'
            "generation": "gen2",        # 'gen1' | 'gen2'
            "node_count": 3,
            "disk_iops": 3000,           # per-regionConfig provisioned IOPS
                                         # (None when Atlas doesn't report)
            "ebs_volume_type": "PROVISIONED",  # AWS only; None otherwise
          },
          ...
        ],
      }
    """
    tiers, iops, autoscaling, notes = tier_info(cluster_cfg or {})
    regions = _summarize_regions(cluster_cfg)
    # Fall back to the first non-null per-region disk_size_gb when Atlas
    # doesn't populate the deprecated top-level cluster.diskSizeGB (true for
    # 2024-05-30+ API responses). Keeps the top-level field useful for a
    # quick "cluster storage" readout at the config level.
    top_level_size = (cluster_cfg or {}).get("diskSizeGB")
    if top_level_size is None:
        for r in regions:
            if r.get("disk_size_gb") is not None:
                top_level_size = r["disk_size_gb"]
                break
    return {
        "cluster_type": (cluster_cfg or {}).get("clusterType"),
        "tiers": tiers,
        "provisioned_iops": iops,
        "disk_size_gb": top_level_size,
        "autoscaling": autoscaling,
        "tier_notes": notes,
        "regions": regions,
    }
