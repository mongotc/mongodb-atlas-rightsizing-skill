"""
Extract dedicated Atlas Search Node metrics only.

We deliberately IGNORE co-located mongot (FTS metrics on mongod hosts). On
clusters with dedicated Search Nodes, mongot runs on the S-tier nodes and
the mongod-side FTS metrics are always empty; on clusters without dedicated
Search Nodes, we don't care. Everything here concerns dedicated nodes.

Three data sources:

1. `/search/deployment` — dedicated Search-Node topology (specs /
   effectiveSpecs). Aggregate only: instance_size + node_count per region /
   shard. Atlas Admin API v2 does NOT expose individual Search-Node hostnames
   here.

2. `/clusters/{name}/search/indexes` — list of Atlas Search indexes with per-
   host status. The `statusDetail[].hostname` field IS the source of truth
   for per-Search-Node hostnames — the documented auto-discovery path.
   Requires at least one Search index to exist on the cluster AND the API
   key must carry a role that includes search-index read (e.g. Project Read
   Only or above).

3. `/processes/{search-host}/measurements` — per-Search-Node SYSTEM_*
   metrics (CPU, memory, network). Confirmed empirically as the endpoint
   Atlas UI's per-node CPU chart uses.

Discovery order for the Search-Node process IDs used by (3):
  a. Auto-discovered via (2): join statusDetail[].hostname with the cluster's
     connection-string domain and SEARCH_NODE_PORT (currently 28000).
  b. Fallback env var (per cluster) — used when (a) isn't available (no
     indexes defined, or the API key lacks search-index read permission):
       SEARCH_NODES_<CLUSTER_NAME_UPPER> = comma-separated 'host:port' entries

Search is orthogonal to the mongod deployment shape (replica set / sharded /
serverless can each optionally have Search). Run alongside the mongod
extractors.
"""

import os

from common import (
    AtlasAPIError,
    cluster_host_keys,
    fetch_fts_measurements,
)


# Per-Search-Node metrics come from `/hosts/{procId}/fts/metrics/measurements`
# (same endpoint used for mongod FTS when co-located) — confirmed via Atlas
# Admin API docs for `operation-listgrouphostftsmetricmeasurements`:
# "Returns the Atlas Search hardware and status data series within the
# provided time range for one process in the specified project."
#
# The `/processes/{procId}/measurements` endpoint with SYSTEM_* names returns
# a stub (null period/start/end, empty dataPoints) for Search Nodes.
#
# Base metric names come from constants/atlas_search_metrics.py (the Atlas
# catalog). We append speculative probe names below — unknown names get
# silently dropped by fetch_fts_measurements' retry loop, so overshooting
# is safe.
from constants.atlas_search_metrics import (  # noqa: E402
    HARDWARE_METRICS as _SEARCH_HARDWARE,
    STATUS_METRICS as _SEARCH_STATUS,
)

# Extractor-specific probe names observed in Atlas docs / UI charts but NOT
# in the confirmed catalog. Kept here (not in constants/) because they are
# speculative — if any of these turn out to be real + stable, promote them
# to atlas_search_metrics.py with their units and remove from this list.
_SEARCH_SPECULATIVE_PROBES = [
    "SEARCH_PROCESS_MEMORY_RESIDENT",   # chart: "Search Process Memory"
    "SEARCH_PROCESS_OVERLOADED",        # chart: "Search Process Throttling"
    "SEARCH_PROCESS_THROTTLING",        # chart: "Search Process Throttling"
    "SEARCH_REPLICATION_LAG_MAX",       # chart: "Search Max Replication Lag"
    "FTS_PROCESS_PAGE_FAULTS",          # chart: "Search Page Fault"
    "SEARCH_OPCOUNTERS",                # chart: "Search Opcounters"
    "SEARCH_OPCOUNTER_QUERY",           # chart: "Search Query Status"
    "SEARCH_QUERY_STATUS",              # chart: "Search Query Status"
]

SEARCH_NODE_METRICS = (
    list(_SEARCH_HARDWARE) + list(_SEARCH_STATUS) + _SEARCH_SPECULATIVE_PROBES
)


def extract(client, group_id, cluster_cfg, window, processes):
    """Dedicated Search-Node topology + per-Search-Node metrics.

    `processes` is accepted for signature compatibility with the other
    extractors but unused — Search Nodes don't appear in /processes.

    Returns:
        {
          "type": "search",
          "cluster": <cluster name>,
          "present": <bool>,               # True if dedicated Search Nodes exist
          "state": <str or None>,
          "specs": [                       # aggregate Search-Node topology
            {"instance_size": "S20_HIGHCPU_NVME", "node_count": 2, ...},
          ],
          "search_nodes": [                # per-Search-Node metrics (empty
            {                              # when discovery failed)
              "process_id": "cluster0-shard-00-search-uma81v.jds2f.mongodb.net:28000",
              "data": {"host": {<metric>: [(ts, value), ...]}},
            },
          ],
          "search_nodes_source": "/clusters/{name}/search/indexes" |
                                 "SEARCH_NODES_<CLUSTER>" | None,
          "search_nodes_discovery_error": <str or None>,
          "raw": <dict or None>,
        }
    """
    cluster_name = cluster_cfg.get("name", "")
    deployment = _fetch_deployment(client=client, group_id=group_id, cluster_name=cluster_name)
    specs = _summarize_specs(deployment=deployment)

    # Short-circuit: no dedicated Search Nodes means nothing to extract.
    if not specs:
        return {
            "type": "search",
            "cluster": cluster_name,
            "present": False,
            "state": (deployment or {}).get("stateName"),
            "specs": [],
            "search_nodes": [],
            "search_nodes_source": None,
            "search_nodes_discovery_error": None,
            "raw": deployment,
        }

    # --- Discover Search-Node process IDs --------------------------------
    # Env var override wins — if the operator has already pinned hostnames
    # for this cluster, we skip the /search/indexes call entirely (saves the
    # API round-trip and avoids 401s on keys without search-index-read).
    # Falls back to /search/indexes auto-discovery otherwise.
    env_key, configured_hosts = _configured_search_node_hosts(cluster_name=cluster_name)
    discovery_error = None
    if configured_hosts:
        process_ids = configured_hosts
        source = env_key
    else:
        discovered_hosts, discovery_error = _discover_search_node_process_ids(
            client=client, group_id=group_id, cluster_cfg=cluster_cfg,
        )
        if discovered_hosts:
            process_ids = discovered_hosts
            source = "/clusters/{name}/search/indexes"
        else:
            process_ids = []
            source = None

    # --- Per-Search-Node metrics -----------------------------------------
    search_nodes = []
    for host in process_ids:
        try:
            data = _fetch_search_node_measurements(client=client, group_id=group_id,
                                                   process_id=host, window=window)
        except AtlasAPIError as e:
            data = {"__error__": str(e)}
        search_nodes.append({
            "process_id": host,
            "data": {"host": data},
        })

    return {
        "type": "search",
        "cluster": cluster_name,
        "present": True,
        "state": (deployment or {}).get("stateName"),
        "specs": specs,
        "search_nodes": search_nodes,
        "search_nodes_source": source,
        "search_nodes_discovery_error": discovery_error,
        "raw": deployment,
    }


def _configured_search_node_hosts(cluster_name):
    """Read SEARCH_NODES_<CLUSTER_NAME_UPPER> env var, with hyphens in the
    cluster name normalized to underscores (shell env vars can't contain
    hyphens, so `stack-0000` -> `SEARCH_NODES_STACK_0000`).

    Also accepts the legacy hyphenated form in case the user set it that way
    via a dotenv parser that tolerates hyphens.

    Returns (env_key_name_used, [host:port, ...]). Empty list if unset."""
    upper = cluster_name.upper()
    canonical = f"SEARCH_NODES_{upper.replace('-', '_')}"
    legacy_hyphen = f"SEARCH_NODES_{upper}"
    for key in (canonical, legacy_hyphen):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return key, [h.strip() for h in raw.split(",") if h.strip()]
    return canonical, []


# Dedicated Search Nodes listen on this port. Confirmed empirically on
# 2026-10-08 (older topologies used 27020). Also hardcoded in
# src/discovery/gather_info.py — keep in sync if Atlas changes it.
SEARCH_NODE_PORT = 28000


def _discover_search_node_process_ids(client, group_id, cluster_cfg):
    """Auto-discover per-Search-Node process IDs from /search/indexes.

    Returns (process_ids, error_message). Each Atlas Search index carries a
    `statusDetail[]` array with one entry per Search Node hosting the index;
    each entry has a `hostname` field with the short Search-Node name (e.g.
    "cluster0-shard-00-search-uma81v"). Combine with the cluster's
    connection-string domain and SEARCH_NODE_PORT to build fully-qualified process
    IDs that /processes/{id}/measurements accepts.

    Empty return when the cluster has no Search indexes (nothing to
    enumerate) or the domain can't be determined."""
    cluster_name = cluster_cfg.get("name", "")
    try:
        indexes = client.get(
            f"/groups/{group_id}/clusters/{cluster_name}/search/indexes"
        )
    except AtlasAPIError as e:
        if "404" in str(e):
            return [], "no search indexes on this cluster"
        return [], f"/search/indexes fetch: {e}"

    if not isinstance(indexes, list):
        return [], "unexpected /search/indexes response shape"
    if not indexes:
        return [], "no search indexes defined on this cluster"

    short_hostnames = set()
    for idx in indexes:
        for st in (idx.get("statusDetail") or []):
            h = st.get("hostname")
            if h:
                short_hostnames.add(h)
    if not short_hostnames:
        return [], "search indexes exist but none report statusDetail hostnames"

    domains = {domain for _, domain in cluster_host_keys(cluster_cfg=cluster_cfg)}
    if not domains:
        return [], "could not determine cluster domain from connection string"
    domain = next(iter(domains))

    return sorted(f"{h}{domain}:{SEARCH_NODE_PORT}" for h in short_hostnames), None


def _fetch_search_node_measurements(client, group_id, process_id, window):
    """Query `/hosts/{search-host}/fts/metrics/measurements` for a dedicated
    Search Node processId. Returns {metric: [(timestamp, value), ...]} —
    same shape as the 'host' dict on mongod nodes in the other extractors.
    See module docstring for the endpoint rationale."""
    return fetch_fts_measurements(client=client, group_id=group_id,
                                  process_id=process_id, window=window,
                                  metric_names=SEARCH_NODE_METRICS)


def _fetch_deployment(client, group_id, cluster_name):
    """/search/deployment or None on 404 (no dedicated Search Nodes)."""
    try:
        return client.get(f"/groups/{group_id}/clusters/{cluster_name}/search/deployment")
    except AtlasAPIError as e:
        if "404" in str(e):
            return None
        raise


def _summarize_specs(deployment):
    if not deployment:
        return []
    # Prefer effectiveSpecs (richer: cloudProvider, regionName, shardId);
    # fall back to `specs` (deprecated but still returned).
    entries = deployment.get("effectiveSpecs") or deployment.get("specs") or []
    return [
        {
            "instance_size": s.get("instanceSize"),
            "node_count": s.get("nodeCount"),
            "region_name": s.get("regionName"),
            "cloud_provider": s.get("cloudProvider"),
            "shard_id": s.get("shardId"),
        }
        for s in entries
    ]


__all__ = ["extract", "SEARCH_NODE_METRICS"]
