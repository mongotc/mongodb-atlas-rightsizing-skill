#!/usr/bin/env python3
"""
MongoDB Atlas rightsizing report.

Pulls hardware measurements for one or more clusters from the Atlas Admin API, evaluates every
node against the rules in ../references/thresholds.md, and writes report.md (human-readable) and
report.json (structured; consumed by merge_verdict.py).

Auth comes from environment variables only, so secrets never end up in shell history or `ps`:
  Service account (preferred): ATLAS_CLIENT_ID / ATLAS_CLIENT_SECRET
  API key (legacy, HTTP Digest): ATLAS_PUBLIC_KEY / ATLAS_PRIVATE_KEY

This script is READ-ONLY. It never modifies a cluster.

Usage:
  python rightsizing.py --group-id <id> --cluster mycluster --days 7 --out-dir ./report
  python rightsizing.py --group-id <id> --days 30 --out-dir ./report     # every cluster in the project
  python rightsizing.py --config targets.json --out-dir ./report         # several projects/clusters
  python rightsizing.py --group-id <id> --cluster mycluster --hours 2    # live spot-check, always low confidence

Exit status: 0 on success; 2 if any cluster could not be evaluated because of an Atlas API error
(the report is still written, with those clusters marked "error").

Only dependency: `requests` (pip install requests).
"""

import argparse
import json
import operator
import os
import re
import sys
import time
from datetime import datetime, timezone

try:
    import requests
    from requests.auth import HTTPDigestAuth
except ImportError:
    sys.exit("This script requires the 'requests' package: pip install requests")

ATLAS_BASE = "https://cloud.mongodb.com/api/atlas/v2"
TOKEN_URL = "https://cloud.mongodb.com/api/oauth/token"
# Pinned so a newer default API version can't change response shapes underneath the script.
API_VERSION_HEADER = {"Accept": "application/vnd.atlas.2025-03-12+json"}

# Host-level metrics: /groups/{groupId}/processes/{processId}/measurements
HOST_METRICS = [
    "SYSTEM_NORMALIZED_CPU_USER",
    "SYSTEM_NORMALIZED_CPU_KERNEL",
    "SYSTEM_MEMORY_USED",
    "SYSTEM_MEMORY_FREE",
    "CONNECTIONS",
    "TICKETS_AVAILABLE_READS",            # context only; see thresholds.md "Concurrency queuing"
    "TICKETS_AVAILABLE_WRITE",            # singular "WRITE" is the real Atlas name
    "GLOBAL_LOCK_CURRENT_QUEUE_READERS",
    "GLOBAL_LOCK_CURRENT_QUEUE_WRITERS",
    "OP_EXECUTION_TIME_READS",            # context only
    "OP_EXECUTION_TIME_WRITES",
    "EXTRA_INFO_PAGE_FAULTS",             # per second
    "CACHE_BYTES_READ_INTO",              # bytes/sec, context only
    "CACHE_FILL_RATIO",                   # already 0-100
    "DIRTY_FILL_RATIO",                   # already 0-100
    "SYSTEM_NORMALIZED_CPU_IOWAIT",       # context only
]

# Disk-level metrics: /groups/{groupId}/processes/{processId}/disks/{partitionName}/measurements
DISK_METRICS = [
    "DISK_PARTITION_IOPS_READ",
    "DISK_PARTITION_IOPS_WRITE",
    "DISK_PARTITION_SPACE_PERCENT_USED",  # disk capacity used, NOT I/O busy time
    "DISK_PARTITION_SPACE_USED",
    "DISK_PARTITION_SPACE_FREE",
    "DISK_PARTITION_LATENCY_READ",        # ms per op
    "DISK_PARTITION_LATENCY_WRITE",
    "DISK_PARTITION_THROUGHPUT_READ",     # bytes/sec, context only
    "DISK_PARTITION_THROUGHPUT_WRITE",
]

# Without these a node can't be judged "fine": a missing core metric means insufficient data.
CORE_HOST_METRICS = (
    "SYSTEM_NORMALIZED_CPU_USER",
    "SYSTEM_NORMALIZED_CPU_KERNEL",
    "SYSTEM_MEMORY_USED",
    "SYSTEM_MEMORY_FREE",
)
CORE_DISK_METRIC = "DISK_PARTITION_SPACE_PERCENT_USED"

# Scale-up triggers and scale-down ceilings. Keep in sync with references/thresholds.md.
CPU_UP, CPU_DOWN = 80, 20                        # % (user + kernel)
MEM_FREE_UP, MEM_FREE_DOWN = 10, 40              # % free, judged on p5 (low end of the window)
IOPS_UP, IOPS_DOWN = 0.90, 0.50                  # fraction of provisioned IOPS (read + write)
SPACE_UP, SPACE_DOWN = 90, 50                    # % disk capacity used
LATENCY_UP, LATENCY_DOWN = 15, 5                 # ms, heuristic
CONNS_UP, CONNS_DOWN = 0.80, 0.30                # fraction of the tier's per-node limit
PAGE_FAULTS_UP, PAGE_FAULTS_DOWN = 1.0, 0.5      # per second, heuristic
CACHE_FILL_UP, CACHE_FILL_DOWN = 80, 50          # % (WT eviction_target)
DIRTY_FILL_UP, DIRTY_FILL_DOWN = 5, 2            # % (WT eviction_dirty_target)
IOWAIT_CONTEXT = 5                               # % iowait worth quoting next to a latency trigger

NEAR_THRESHOLD = 0.10  # a p95 within 10% of a scale-up trigger is "borderline"
MIN_COVERAGE = 0.90    # below this fraction of expected samples, the data has gaps
SUSTAINED_DAYS = 3     # CPU / IOPS / disk space must breach on >= 3 of the last 7 days

DISK_TRIGGERS = {"iops", "disk_space", "disk_latency_read", "disk_latency_write"}
EVALUATED_VERDICTS = {"scale_up", "disk_iops_only", "scale_down_candidate", "no_change"}
SHARED_TIERS = {"M0", "M2", "M5", "FLEX", "SERVERLESS"}

# Max concurrent connections per node, from "Connection Limits and Cluster Tier" at
# https://www.mongodb.com/docs/atlas/reference/atlas-limits/ (checked 2026-09-22). That page has
# several tables (by cloud provider / cluster class) that disagree for some tiers, e.g. M80 is
# 96000 in one and 64000 in the others. Stored as (lowest, highest); the check uses the lowest so
# it errs toward flagging. R-series and _NVME tiers are looked up by their M-number.
TIER_MAX_CONNECTIONS = {
    "M10": (1500, 1500), "M20": (3000, 3000), "M30": (3000, 3000), "M40": (4000, 6000),
    "M50": (16000, 16000), "M60": (32000, 32000), "M80": (64000, 96000), "M140": (96000, 96000),
    "M200": (128000, 128000), "M300": (128000, 128000), "M400": (128000, 128000),
    "M600": (128000, 128000), "M700": (128000, 128000),
}

VERDICT_LABELS = {
    "scale_up": "SCALE UP",
    "disk_iops_only": "CHANGE DISK / IOPS ONLY",
    "scale_down_candidate": "SCALE DOWN CANDIDATE",
    "no_change": "NO CHANGE",
    "insufficient_data": "INSUFFICIENT DATA",
    "not_supported": "NOT SUPPORTED",
    "not_applicable": "NOT APPLICABLE",
    "error": "ERROR",
}


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------------------------
# Atlas API access
# --------------------------------------------------------------------------------------------

class AtlasAPIError(Exception):
    pass


class AtlasClient:
    """requests wrapper: auth (with OAuth token refresh), retry with backoff on 429/5xx,
    pagination, and failures raised as AtlasAPIError instead of being swallowed."""

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
                "No credentials found. Set ATLAS_CLIENT_ID/ATLAS_CLIENT_SECRET (service account) "
                "or ATLAS_PUBLIC_KEY/ATLAS_PRIVATE_KEY (API key) in the environment."
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
            raise AtlasAPIError(f"OAuth token request failed ({resp.status_code}): {resp.text[:300]}")
        body = resp.json()
        self.session.headers["Authorization"] = f"Bearer {body['access_token']}"
        # Service-account tokens last an hour; refresh a minute early so long audits don't 401.
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
                raise AtlasAPIError(f"Atlas API error {resp.status_code} on {path}: {resp.text[:500]}")
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


def _series(data):
    """Measurements response -> {metric name: [(timestamp, value), ...]} with nulls dropped."""
    out = {}
    for m in data.get("measurements", []):
        out[m["name"]] = [
            (dp["timestamp"], dp["value"]) for dp in m.get("dataPoints", []) if dp.get("value") is not None
        ]
    return out


def fetch_node_metrics(client, group_id, process_id, window, host_only=False):
    """{"host": {metric: series}, "disks": {partition: {metric: series}}} for one process."""
    base = f"/groups/{group_id}/processes/{process_id}"
    query = [("granularity", window["granularity"]), ("period", window["period"])]
    host = _series(client.get(f"{base}/measurements", query + [("m", m) for m in HOST_METRICS]))
    disks = {}
    if not host_only:
        for partition in client.get_all(f"{base}/disks"):
            name = partition.get("partitionName")
            if name:
                disks[name] = _series(client.get(
                    f"{base}/disks/{name}/measurements", query + [("m", m) for m in DISK_METRICS]
                ))
    return {"host": host, "disks": disks}


# --------------------------------------------------------------------------------------------
# Cluster topology
# --------------------------------------------------------------------------------------------

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
    """Exact match on host prefix + domain, so 'prod' never picks up 'prod-analytics' or 'prod2'.
    Falls back to an exact '<cluster name>-shard-' / '-config-' prefix when the cluster response
    has no parseable connection string."""
    keys = [_host_key(proc.get(f)) for f in ("userAlias", "hostname", "id")]
    keys = [k for k in keys if k]
    if host_keys:
        return any(k in host_keys for k in keys)
    return any(k[0] == cluster_name.lower() for k in keys)


def group_processes_by_replica_set(procs):
    """Split a cluster's processes into per-replica-set groups (each shard and the config server
    is its own replica set) plus mongos routers, which have no replicaSetName.

    Implemented against the documented process schema; not yet checked against a live sharded
    cluster, so compare the shard breakdown with the Atlas UI the first time."""
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


def normalize_tier(tier):
    m = re.match(r"^[MR](\d+)", tier or "")
    return f"M{m.group(1)}" if m else None


def tier_info(cluster_cfg):
    """Tier(s), provisioned IOPS and auto-scaling settings across every region config."""
    tiers, iops, notes = set(), set(), []
    autoscaling = {"compute": None, "disk": False}
    for spec in cluster_cfg.get("replicationSpecs", []):
        for rc in spec.get("regionConfigs", []):
            electable = rc.get("electableSpecs") or {}
            if electable.get("instanceSize"):
                tiers.add(electable["instanceSize"])
            if electable.get("diskIOPS") is not None:
                iops.add(electable["diskIOPS"])
            for kind in ("readOnlySpecs", "analyticsSpecs"):
                other = rc.get(kind) or {}
                if other.get("nodeCount") and other.get("instanceSize") not in (None, electable.get("instanceSize")):
                    notes.append(
                        f"{kind[:-5]} nodes run {other['instanceSize']} (electable nodes run "
                        f"{electable.get('instanceSize')}); they are evaluated against the same thresholds."
                    )
            scaling = rc.get("autoScaling") or {}
            compute = scaling.get("compute") or {}
            if compute.get("enabled"):
                autoscaling["compute"] = compute
            if (scaling.get("diskGB") or {}).get("enabled"):
                autoscaling["disk"] = True
    return sorted(tiers) or ["UNKNOWN"], sorted(iops), autoscaling, sorted(set(notes))


def autoscaling_notes(autoscaling, verdict, trigger_ids):
    notes = []
    compute = autoscaling.get("compute")
    if compute:
        span = f"{compute.get('minInstanceSize', '?')}–{compute.get('maxInstanceSize', '?')}"
        if verdict == "scale_up" and trigger_ids - DISK_TRIGGERS:
            notes.append(
                f"Compute auto-scaling is ON ({span}). Atlas scales up by itself under sustained load, "
                f"so if it hasn't, the cluster may already be at its max tier: raising "
                f"maxInstanceSize is likely the right change, not a manual tier bump."
            )
        elif verdict == "scale_down_candidate":
            if compute.get("scaleDownEnabled"):
                notes.append(
                    f"Compute auto-scaling with scale-down is ON ({span}). Atlas should downsize by itself "
                    f"and may override a manual change; lower minInstanceSize instead."
                )
            else:
                notes.append(
                    f"Compute auto-scaling is ON ({span}) but scale-down is disabled: enable scale-down "
                    f"or lower the tier manually."
                )
        else:
            notes.append(f"Compute auto-scaling is ON ({span}); a manual tier change may be overridden.")
    if autoscaling.get("disk") and "disk_space" in trigger_ids:
        notes.append("Storage auto-scaling is ON: Atlas grows the disk automatically as it fills, "
                     "so the disk-space trigger may resolve itself.")
    return notes


# --------------------------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------------------------

def pctl(values, p):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def summarize(points):
    values = [v for _, v in points or []]
    if not values:
        return None
    return {
        "p5": round(pctl(values, 0.05), 2),
        "p50": round(pctl(values, 0.5), 2),
        "p95": round(pctl(values, 0.95), 2),
        "max": round(max(values), 2),
        "n": len(values),
    }


def combine(a, b, fn):
    """Join two series on timestamp and apply fn(a_value, b_value)."""
    b_by_ts = dict(b or [])
    return [(ts, fn(v, b_by_ts[ts])) for ts, v in a or [] if ts in b_by_ts]


def breach_days(points, threshold, last_n_days=7):
    """How many of the last N UTC days have their own p95 above threshold."""
    by_day = {}
    for ts, v in points:
        by_day.setdefault(ts[:10], []).append(v)
    recent = sorted(by_day)[-last_n_days:]
    return sum(1 for day in recent if pctl(by_day[day], 0.95) > threshold)


def sustained_days_required(window_days):
    if window_days >= 7:
        return SUSTAINED_DAYS
    return max(1, -(-SUSTAINED_DAYS * int(window_days) // 7))


# --------------------------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------------------------

def evaluate_node(data, ctx):
    """Apply the thresholds to one node. ctx: provisioned_iops, max_connections, window."""
    host, disks = data.get("host", {}), data.get("disks", {})
    window = ctx["window"]
    triggers, borderline = [], []
    summary = {name: summarize(pts) for name, pts in host.items()}

    def check_high(tid, label, points, threshold, unit="", sustained=False, threshold_text=None, suffix=""):
        s = summarize(points)
        if not s:
            return None
        limit = threshold_text or f"{round(threshold, 2)}{unit}"
        if s["p95"] > threshold:
            if sustained:
                days = breach_days(points, threshold)
                need = sustained_days_required(window["days"])
                if days < need:
                    borderline.append(
                        f"{label} p95 {s['p95']}{unit} > {limit}, but only on {days} day(s) "
                        f"(needs {need} to count as sustained)"
                    )
                    return s
                triggers.append({"id": tid, "text": f"{label} p95 {s['p95']}{unit} > {limit}, on {days} day(s){suffix}"})
            else:
                triggers.append({"id": tid, "text": f"{label} p95 {s['p95']}{unit} > {limit}{suffix}"})
        elif s["p95"] >= threshold * (1 - NEAR_THRESHOLD):
            borderline.append(f"{label} p95 {s['p95']}{unit} is within {int(NEAR_THRESHOLD * 100)}% of the {limit} trigger")
        return s

    cpu_pts = combine(host.get("SYSTEM_NORMALIZED_CPU_USER"), host.get("SYSTEM_NORMALIZED_CPU_KERNEL"), operator.add)
    cpu = check_high("cpu", "CPU (user+kernel)", cpu_pts, CPU_UP, "%", sustained=True)
    summary["CPU_USER_PLUS_KERNEL"] = cpu

    mem_pts = [
        (ts, v) for ts, v in combine(
            host.get("SYSTEM_MEMORY_FREE"), host.get("SYSTEM_MEMORY_USED"),
            lambda free, used: 100.0 * free / (free + used) if free + used > 0 else None,
        ) if v is not None
    ]
    mem = summarize(mem_pts)
    summary["MEMORY_FREE_PCT"] = mem
    if mem:
        if mem["p5"] < MEM_FREE_UP:
            triggers.append({"id": "memory", "text": f"Free memory p5 {mem['p5']}% < {MEM_FREE_UP}% (low for at least 5% of the window)"})
        elif mem["p5"] <= MEM_FREE_UP * (1 + NEAR_THRESHOLD):
            borderline.append(f"Free memory p5 {mem['p5']}% is within {int(NEAR_THRESHOLD * 100)}% of the {MEM_FREE_UP}% trigger")

    conns = summarize(host.get("CONNECTIONS"))
    limit = ctx.get("max_connections")
    if conns and limit:
        low, high = limit
        limit_text = str(low) if low == high else f"{low} (the docs list {low}–{high} for this tier by provider/class)"
        check_high("connections", "Connections", host["CONNECTIONS"], CONNS_UP * low,
                   threshold_text=f"{int(CONNS_UP * 100)}% of the tier's {limit_text} max per node")

    for label, name in (("read", "READERS"), ("write", "WRITERS")):
        q = summarize(host.get(f"GLOBAL_LOCK_CURRENT_QUEUE_{name}"))
        if q and q["p95"] > 0:
            exec_time = summarize(host.get(f"OP_EXECUTION_TIME_{label.upper()}S"))
            extra = (f"; OP_EXECUTION_TIME_{label.upper()}S p95 {exec_time['p95']}ms"
                     if exec_time and exec_time["p95"] > 0 else "")
            triggers.append({"id": f"queue_{label}", "text": (
                f"{label.capitalize()} concurrency queue p95 {q['p95']} > 0: operations are waiting "
                f"for a WiredTiger ticket{extra}")})

    cache_read = summarize(host.get("CACHE_BYTES_READ_INTO"))
    page_faults = check_high(
        "page_faults", "Page faults", host.get("EXTRA_INFO_PAGE_FAULTS"), PAGE_FAULTS_UP, "/sec",
        suffix=(f" (CACHE_BYTES_READ_INTO p95 {cache_read['p95']} B/s)" if cache_read and cache_read["p95"] > 0 else "")
        + ": WiredTiger cache may be undersized for the working set",
    )
    cache_fill = check_high("cache_fill", "Cache fill ratio", host.get("CACHE_FILL_RATIO"), CACHE_FILL_UP, "%",
                            suffix=" (eviction_target): background eviction likely running continuously")
    dirty_fill = check_high("dirty_fill", "Dirty fill ratio", host.get("DIRTY_FILL_RATIO"), DIRTY_FILL_UP, "%",
                            suffix=" (eviction_dirty_target): dirty-page eviction likely running continuously")
    queues = [summarize(host.get(f"GLOBAL_LOCK_CURRENT_QUEUE_{n}")) for n in ("READERS", "WRITERS")]

    iowait = summarize(host.get("SYSTEM_NORMALIZED_CPU_IOWAIT"))
    prov = ctx.get("provisioned_iops")
    disk_down = []
    for part, m in sorted(disks.items()):
        for name, pts in m.items():
            summary[f"{name}[{part}]"] = summarize(pts)
        iops_pts = combine(m.get("DISK_PARTITION_IOPS_READ"), m.get("DISK_PARTITION_IOPS_WRITE"), operator.add)
        iops = summarize(iops_pts)
        summary[f"DISK_PARTITION_IOPS_TOTAL[{part}]"] = iops
        if prov:
            check_high("iops", f"Disk IOPS read+write [{part}]", iops_pts, IOPS_UP * prov, sustained=True,
                       threshold_text=f"{int(IOPS_UP * 100)}% of provisioned {prov}")
        space = check_high("disk_space", f"Disk space used [{part}]", m.get(CORE_DISK_METRIC), SPACE_UP, "%",
                           sustained=True)
        latencies = []
        for label in ("read", "write"):
            throughput = summarize(m.get(f"DISK_PARTITION_THROUGHPUT_{label.upper()}"))
            context = []
            if throughput and throughput["p95"] > 0:
                context.append(f"throughput p95 {throughput['p95']} B/s")
            if iowait and iowait["p95"] > IOWAIT_CONTEXT:
                context.append(f"CPU iowait p95 {iowait['p95']}%")
            latencies.append(check_high(
                f"disk_latency_{label}", f"Disk {label} latency [{part}]", m.get(f"DISK_PARTITION_LATENCY_{label.upper()}"),
                LATENCY_UP, "ms", threshold_text=f"{LATENCY_UP}ms heuristic",
                suffix=f" ({', '.join(context)})" if context else "",
            ))
        disk_down.append(
            space is not None and space["p95"] < SPACE_DOWN
            and (not prov or not iops or iops["p95"] < IOPS_DOWN * prov)
            and all(lat is None or lat["p95"] < LATENCY_DOWN for lat in latencies)
        )

    missing = [m for m in CORE_HOST_METRICS if not host.get(m)]
    if not any(m.get(CORE_DISK_METRIC) for m in disks.values()):
        missing.append(CORE_DISK_METRIC)

    core_series = [host.get(m) or [] for m in CORE_HOST_METRICS]
    core_series += [m.get(CORE_DISK_METRIC) or [] for m in disks.values()] or [[]]
    expected = window["expected_samples"]
    coverage = min(min(len(s) / expected, 1.0) for s in core_series) if expected else 0.0

    down_checks = {
        "cpu": bool(cpu and cpu["p95"] < CPU_DOWN),
        "memory": bool(mem and mem["p5"] > MEM_FREE_DOWN),
        "disk": bool(disk_down) and all(disk_down),
        "page_faults": page_faults is None or page_faults["p95"] < PAGE_FAULTS_DOWN,
        "cache_fill": cache_fill is None or cache_fill["p95"] < CACHE_FILL_DOWN,
        "dirty_fill": dirty_fill is None or dirty_fill["p95"] < DIRTY_FILL_DOWN,
        "queues": all(q is None or q["max"] == 0 for q in queues),
        "connections": not conns or not limit or conns["p95"] < CONNS_DOWN * limit[0],
    }
    return {
        "triggers": triggers,
        "borderline": borderline,
        "down_checks": down_checks,
        "summary": summary,
        "coverage": round(coverage, 3),
        "missing": missing,
    }


def confidence_for(verdict, trigger_ids, window_days, coverage, borderline, missing):
    if verdict == "insufficient_data" or window_days < 3 or coverage < MIN_COVERAGE or missing:
        return "low"
    if verdict in ("scale_up", "disk_iops_only"):
        if window_days < 7 or len(trigger_ids) < 2:
            return "medium"
        return "high"
    if borderline:
        return "low"
    return "medium" if window_days < 7 else "high"


def evaluate_group(nodes, ctx):
    """Evaluate every node (a replica set or one shard) and combine: the group is judged by its
    worst node, so a hot primary can't be averaged away by idle secondaries.

    nodes: [{"label", "role", "hosts", "data"}]. Returns a partial result dict."""
    window = ctx["window"]
    evaluated = [(n, evaluate_node(n["data"], ctx)) for n in nodes]
    node_rows = [
        {"node": n["label"], "role": n.get("role"), "hosts": n.get("hosts", []),
         "coverage": r["coverage"], "metric_summary": r["summary"]}
        for n, r in evaluated
    ]

    if not evaluated or not any(any(v for v in r["summary"].values()) for _, r in evaluated):
        return {
            "verdict": "insufficient_data", "confidence": "low", "triggers": [], "borderline": [],
            "reasons": ["No metrics were returned for the requested window: no processes matched, or the "
                        "cluster is too new (check its creation time), paused, or unreachable. Not a basis "
                        "for any verdict; re-run once it has some operating history."],
            "coverage": 0.0, "nodes": node_rows, "notes": [],
        }

    triggers, borderline, notes = [], [], []
    for n, r in evaluated:
        triggers += [{"id": t["id"], "node": n["label"], "text": f"{n['label']}: {t['text']}"} for t in r["triggers"]]
        borderline += [f"{n['label']}: {b}" for b in r["borderline"]]
        if r["missing"]:
            notes.append(f"{n['label']}: missing core metrics {', '.join(r['missing'])}")
    missing = any(r["missing"] for _, r in evaluated)
    coverage = min(r["coverage"] for _, r in evaluated)
    trigger_ids = {t["id"] for t in triggers}

    if coverage < MIN_COVERAGE:
        notes.append(
            f"Data coverage is {coverage:.0%} of the expected samples for the lowest node/metric (gaps from "
            f"restarts, a cluster younger than the window, or missing data)."
        )

    if triggers:
        verdict = "disk_iops_only" if trigger_ids <= DISK_TRIGGERS else "scale_up"
        reasons = [t["text"] for t in triggers]
        if verdict == "disk_iops_only":
            reasons.append("Only disk signals fired: check whether more IOPS or disk (not a compute tier "
                           "change) resolves it.")
    elif missing:
        verdict = "insufficient_data"
        reasons = ["Core metrics (CPU, memory or disk space) are missing for at least one node, so there is "
                   "no basis for a no-change or scale-down verdict."]
    elif (all(all(r["down_checks"].values()) for _, r in evaluated)
          and window["days"] >= 7 and coverage >= MIN_COVERAGE and not borderline):
        verdict = "scale_down_candidate"
        reasons = ["Every node is comfortably under all scale-down limits (CPU, memory, disk space, IOPS, "
                   "latency, cache, queues, connections)."]
    else:
        verdict = "no_change"
        reasons = ["No scale-up thresholds crossed."]
        if borderline:
            reasons = ["No scale-up thresholds crossed, but some metrics are close to a trigger (see below)."]

    if verdict == "scale_down_candidate" and not ctx.get("provisioned_iops"):
        notes.append("IOPS headroom was not checked: the cluster config doesn't report provisioned diskIOPS.")

    return {
        "verdict": verdict,
        "confidence": confidence_for(verdict, trigger_ids, window["days"], coverage, borderline, missing),
        "triggers": sorted(trigger_ids),
        "reasons": reasons,
        "borderline": borderline,
        "notes": notes,
        "coverage": round(coverage, 3),
        "nodes": node_rows,
    }


def evaluate_cluster(client, group_id, name, window, processes):
    """Evaluate one cluster. Returns a list of results (one per replica set / shard, plus routers)."""
    cfg = client.get(f"/groups/{group_id}/clusters/{name}")
    tiers, iops_values, autoscaling, tier_notes = tier_info(cfg)
    tier_display = tiers[0] if len(tiers) == 1 else "mixed: " + ", ".join(tiers)
    base = {"group_id": group_id, "cluster_name": name, "current_tier": tier_display}

    if len(tiers) == 1 and tiers[0] in SHARED_TIERS:
        return [dict(base, cluster=name, verdict="not_supported", confidence="n/a", triggers=[],
                     reasons=["Free/shared/flex tiers don't expose full hardware measurements."],
                     borderline=[], notes=[], coverage=None, nodes=[])]

    notes = list(tier_notes)
    max_connections = None
    if len(tiers) == 1:
        max_connections = TIER_MAX_CONNECTIONS.get(normalize_tier(tiers[0]))
        if not max_connections:
            notes.append(f"Connections check skipped: no known connection limit for tier {tiers[0]}.")
    else:
        notes.append("Connections check skipped: shards run different tiers, so there is no single limit.")

    provisioned_iops = iops_values[0] if len(iops_values) == 1 else None
    if len(iops_values) > 1:
        notes.append(
            f"IOPS check skipped: shards have different provisioned IOPS ({', '.join(map(str, iops_values))}) "
            f"and shard-to-replica-set mapping isn't confirmed; check IOPS headroom per shard in the Atlas UI."
        )
    elif not iops_values:
        notes.append("IOPS check skipped: the cluster config doesn't report provisioned diskIOPS.")

    host_keys = cluster_host_keys(cfg)
    procs = [p for p in processes if process_matches(p, host_keys, name)]
    shard_groups, routers = group_processes_by_replica_set(procs)
    ctx = {"window": window, "provisioned_iops": provisioned_iops, "max_connections": max_connections}

    def nodes_for(group, host_only=False):
        return [{
            "label": node_label(p), "role": p.get("typeName"), "hosts": node_hosts(p),
            "data": fetch_node_metrics(client, group_id, p["id"], window, host_only=host_only),
        } for p in group if p.get("id")]

    results = []
    groups = sorted(shard_groups.items()) or [(None, [])]
    for rs_name, group in groups:
        evaluation = evaluate_group(nodes_for(group), ctx)
        evaluation["notes"] = notes + evaluation["notes"] + autoscaling_notes(
            autoscaling, evaluation["verdict"], set(evaluation["triggers"]))
        if not procs:
            evaluation["notes"].append(
                "No processes matched this cluster's hostnames; check the cluster name and that the API "
                "key can see the project's processes.")
        display = name if len(shard_groups) <= 1 and not routers else f"{name} — replica set {rs_name}"
        results.append(dict(base, cluster=display, **evaluation))

    if routers:
        router_nodes = nodes_for(routers, host_only=True)
        results.append(dict(
            base, cluster=f"{name} — mongos routers ({len(routers)})", verdict="not_applicable",
            confidence="n/a", triggers=[], borderline=[], notes=[], coverage=None,
            reasons=["mongos routers have no local storage or WiredTiger cache: shown for visibility only, "
                     "not evaluated against the rightsizing thresholds."],
            nodes=[{"node": n["label"], "role": n["role"], "hosts": n["hosts"], "coverage": None,
                    "metric_summary": {k: summarize(v) for k, v in n["data"]["host"].items()}}
                   for n in router_nodes],
        ))
    return results


# --------------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------------

def build_report(results, window):
    lines = ["# Atlas Rightsizing Report", "",
             f"Lookback: {window['label']} (granularity {window['granularity']})  |  Generated: {utc_now()}", ""]
    for r in results:
        lines.append(f"## {r['cluster']}  —  {r['current_tier']}")
        lines.append(f"Project `{r['group_id']}`")
        lines.append("")
        lines.append(f"**Verdict: {VERDICT_LABELS.get(r['verdict'], r['verdict'])}**  (confidence: {r['confidence']})")
        lines.append("")
        lines += [f"- {reason}" for reason in r["reasons"]]
        if r.get("borderline"):
            lines += ["", "**Close to a trigger:**"] + [f"- {b}" for b in r["borderline"]]
        if r.get("notes"):
            lines += ["", "**Notes:**"] + [f"- {n}" for n in r["notes"]]
        if r.get("coverage") is not None:
            lines += ["", f"Data coverage: {r['coverage']:.0%} of expected samples (lowest node/core metric)."]
        lines.append("")
        for node in r.get("nodes", []):
            rows = [(k, s) for k, s in node["metric_summary"].items() if s]
            if not rows:
                continue
            lines.append(f"### {node['node']}" + (f" ({node['role']})" if node.get("role") else ""))
            lines.append("")
            lines.append("| Metric | p5 | p50 | p95 | max | samples |")
            lines.append("|---|---|---|---|---|---|")
            lines += [f"| {k} | {s['p5']} | {s['p50']} | {s['p95']} | {s['max']} | {s['n']} |" for k, s in rows]
            lines.append("")
    lines.append("---")
    lines.append("This is a read-only recommendation. No cluster was modified. Node roles are as of report time.")
    lines.append("Verify thresholds against your own risk tolerance before acting (references/thresholds.md).")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------

def build_window(days=None, hours=None):
    if hours is not None:
        if hours < 1:
            raise ValueError("--hours must be a whole number >= 1")
        # Atlas keeps 1-minute data for roughly 38 hours (observed); PT1M shows short spikes that
        # coarser buckets average away. Longer ad-hoc windows fall back to hourly data.
        granularity = "PT1M" if hours <= 36 else "PT1H"
        return {
            "days": hours / 24, "label": f"{hours} hours", "period": f"PT{hours}H", "granularity": granularity,
            "expected_samples": hours * 60 if granularity == "PT1M" else hours,
        }
    days = 7 if days is None else days
    if days < 1:
        raise ValueError("--days must be a whole number >= 1")
    return {"days": float(days), "label": f"{days} days", "period": f"P{days}D", "granularity": "PT1H",
            "expected_samples": days * 24}


def load_targets(args):
    """[(group_id, cluster or None)] plus days/hours, from --config and/or CLI flags (CLI wins)."""
    days, hours, targets = args.days, args.hours, []
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            cfg = json.load(f)
        days = days if days is not None else cfg.get("days")
        hours = hours if hours is not None else cfg.get("hours")
        targets = [(t["group_id"], t.get("cluster")) for t in cfg.get("targets", [])]
    if args.group_id:
        targets.append((args.group_id, args.cluster))
    if not targets:
        raise ValueError("Give --group-id (optionally with --cluster) or --config with at least one target")
    return targets, days, hours


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group-id", help="Atlas project (group) ID")
    ap.add_argument("--cluster", help="Cluster name; omit to audit every cluster in the project")
    ap.add_argument("--config", help="JSON file with several targets (see config.example.json)")
    ap.add_argument("--days", type=int, default=None, help="Lookback window in whole days (default 7)")
    ap.add_argument("--hours", type=int, default=None,
                    help="Lookback in whole hours for a live spot-check; overrides --days and always "
                         "reports low confidence")
    ap.add_argument("--out-dir", default="./rightsizing-report", help="Output directory")
    args = ap.parse_args(argv)

    try:
        targets, days, hours = load_targets(args)
        window = build_window(days, hours)
    except (ValueError, OSError, KeyError) as e:
        ap.error(str(e))

    try:
        client = AtlasClient()
    except AtlasAPIError as e:
        sys.exit(str(e))

    results, process_cache = [], {}
    for group_id, cluster in targets:
        try:
            names = [cluster] if cluster else [c["name"] for c in client.get_all(f"/groups/{group_id}/clusters")]
            if group_id not in process_cache:
                process_cache[group_id] = client.get_all(f"/groups/{group_id}/processes")
        except AtlasAPIError as e:
            results.append(error_result(group_id, cluster or "(all clusters)", e))
            continue
        for name in names:
            try:
                results += evaluate_cluster(client, group_id, name, window, process_cache[group_id])
            except AtlasAPIError as e:
                results.append(error_result(group_id, name, e))

    os.makedirs(args.out_dir, exist_ok=True)
    report_md = build_report(results, window)
    with open(os.path.join(args.out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(report_md)
    with open(os.path.join(args.out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": utc_now(),
            "groupIds": sorted({g for g, _ in targets}),
            "windowDays": window["days"], "windowLabel": window["label"], "granularity": window["granularity"],
            "results": results,
        }, f, indent=2)

    print(report_md)
    print(f"\n[written to {args.out_dir}/report.md and report.json]")
    if any(r["verdict"] == "error" for r in results):
        print("One or more clusters could not be evaluated because of Atlas API errors (see report).", file=sys.stderr)
        return 2
    return 0


def error_result(group_id, name, err):
    return {
        "group_id": group_id, "cluster_name": name, "cluster": name, "current_tier": "UNKNOWN",
        "verdict": "error", "confidence": "n/a", "triggers": [], "borderline": [], "notes": [],
        "reasons": [f"Could not evaluate: {err}"], "coverage": None, "nodes": [],
    }


if __name__ == "__main__":
    sys.exit(main())
