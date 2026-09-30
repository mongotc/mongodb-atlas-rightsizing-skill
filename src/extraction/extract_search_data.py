"""
Extract Atlas Search topology + metrics.

Four data sources, each with its own quirk:

1. `/search/deployment` — dedicated Search-Node topology (specs / effectiveSpecs).
   Aggregate only: instance_size + node_count per region/shard. Atlas Admin
   API v2 does NOT expose individual Search-Node hostnames here.

2. `/clusters/{name}/search/indexes` — list of Atlas Search indexes with per-
   host status. The `statusDetail[].hostname` field IS the source of truth
   for per-Search-Node hostnames — this is the documented auto-discovery
   path. Requires at least one Search index to exist on the cluster.

3. `/hosts/{procId}/fts/metrics/measurements` — FTS metrics per MONGOD host.
   Atlas attributes FTS work to the mongod host serving queries, not to the
   mongot process executing them. Length here = mongod RS-member count.

4. `/processes/{search-host}/measurements` — per-Search-Node SYSTEM_* metrics
   (CPU, memory) AND per-Search-Node FTS_PROCESS_* metrics. Confirmed
   empirically as the endpoint Atlas UI's per-node CPU chart uses:
       cluster0-shard-00-search-uma81v: CPU 2.395%
       cluster0-shard-00-search-vrzrkg: CPU 2.392%

Discovery order for the Search-Node process IDs used by (4):
  a. Auto-discovered via (2): join statusDetail[].hostname with the cluster's
     connection-string domain and port 27020.
  b. Fallback env var (per cluster) — used when the cluster has no Search
     indexes yet or the /search/indexes endpoint is unavailable:
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
    fetch_measurements,
    node_hosts,
    node_label,
    process_matches,
)


# Metrics to request per Search Node via /processes/{search-host}/measurements.
# Only SYSTEM_* — FTS_PROCESS_* names are accepted by that endpoint but always
# return empty on Search Nodes because Atlas attributes FTS metrics to the
# mongod host serving queries, not to the mongot process. FTS_PROCESS_* data
# is captured under `mongod_hosts[].data.fts` (via fetch_fts_measurements).
SEARCH_NODE_METRICS = [
    "SYSTEM_NORMALIZED_CPU_USER",
    "SYSTEM_NORMALIZED_CPU_KERNEL",
    "SYSTEM_MEMORY_USED",
    "SYSTEM_MEMORY_FREE",
    "SYSTEM_NETWORK_IN",
    "SYSTEM_NETWORK_OUT",
]


def extract(client, group_id, cluster_cfg, window, processes):
    """Return Atlas Search deployment + per-mongod-host FTS metrics + per-
    Search-Node metrics (when Search-Node hostnames are configured via env).

    Returns:
        {
          "type": "search",
          "cluster": <cluster name>,
          "present": <bool>,               # True if dedicated Search Nodes exist
          "state": <str or None>,
          "specs": [                       # aggregate Search-Node topology
            { "instance_size": "S20_HIGHCPU_NVME", "node_count": 2 },
          ],
          "mongod_hosts": [                # FTS metrics attributed to mongod
            {
              "label": "cluster0-shard-00-01:27017",
              "role": "REPLICA_PRIMARY",
              "hosts": [...],
              "process_id": "atlas-rkdvka-shard-00-01.jds2f.mongodb.net:27017",
              "data": {"fts": {...}},
            },
          ],
          "search_nodes": [                # per-Search-Node metrics when
            {                              # SEARCH_NODES_<CLUSTER> env is set
              "process_id": "cluster0-shard-00-search-uma81v.jds2f.mongodb.net:27020",
              "data": {"host": {<metric>: [(ts, value), ...]}},
              ...
            },
          ],
          "search_nodes_config_source": "SEARCH_NODES_CLUSTER0" | None,
          "raw": <dict or None>,
        }
    """
    cluster_name = cluster_cfg.get("name", "")
    deployment = _fetch_deployment(client, group_id, cluster_name)
    specs = _summarize_specs(deployment)

    # --- 1. Per-mongod-host FTS metrics -----------------------------------
    host_keys = cluster_host_keys(cluster_cfg)
    cluster_procs = [
        p for p in processes
        if p.get("id") and process_matches(p, host_keys, cluster_name)
    ]

    mongod_hosts = []
    for proc in cluster_procs:
        try:
            fts = fetch_fts_measurements(client, group_id, proc["id"], window)
        except AtlasAPIError as e:
            fts = {"__error__": str(e)}
        mongod_hosts.append({
            "label": node_label(proc),
            "role": proc.get("typeName"),
            "hosts": node_hosts(proc),
            "process_id": proc["id"],
            "data": {"fts": fts},
        })

    # --- 2. Discover Search-Node process IDs -----------------------------
    # Prefer auto-discovery via /search/indexes → statusDetail[].hostname;
    # fall back to SEARCH_NODES_<CLUSTER> env var if the cluster has no
    # indexes yet or the endpoint is otherwise unavailable.
    discovered_hosts, discovery_error = _discover_search_node_process_ids(
        client, group_id, cluster_cfg
    )
    env_key, configured_hosts = _configured_search_node_hosts(cluster_name)
    if discovered_hosts:
        process_ids = discovered_hosts
        source = "/clusters/{name}/search/indexes"
    elif configured_hosts:
        process_ids = configured_hosts
        source = env_key
    else:
        process_ids = []
        source = None

    # --- 3. Per-Search-Node metrics --------------------------------------
    search_nodes = []
    for host in process_ids:
        try:
            data = _fetch_search_node_measurements(client, group_id, host, window)
        except AtlasAPIError as e:
            data = {"__error__": str(e)}
        search_nodes.append({
            "process_id": host,
            "data": {"host": data},
        })

    return {
        "type": "search",
        "cluster": cluster_name,
        "present": bool(specs),
        "state": (deployment or {}).get("stateName"),
        "specs": specs,
        "mongod_hosts": mongod_hosts,
        "search_nodes": search_nodes,
        "search_nodes_source": source,
        "search_nodes_discovery_error": discovery_error,
        "raw": deployment,
    }


def _configured_search_node_hosts(cluster_name):
    """Read SEARCH_NODES_<CLUSTER_NAME_UPPER> env var.

    Returns (env_key_name, [host:port, ...]). Empty list if unset."""
    env_key = f"SEARCH_NODES_{cluster_name.upper()}"
    raw = (os.environ.get(env_key) or "").strip()
    if not raw:
        return env_key, []
    return env_key, [h.strip() for h in raw.split(",") if h.strip()]


# Dedicated Search Nodes always listen on this port; confirmed empirically.
SEARCH_NODE_PORT = 27020


def _discover_search_node_process_ids(client, group_id, cluster_cfg):
    """Auto-discover per-Search-Node process IDs from /search/indexes.

    Returns (process_ids, error_message). Each Atlas Search index carries a
    `statusDetail[]` array with one entry per Search Node hosting the index;
    each entry has a `hostname` field with the short Search-Node name (e.g.
    "cluster0-shard-00-search-uma81v"). Combine with the cluster's
    connection-string domain and port 27020 to build fully-qualified process
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

    domains = {domain for _, domain in cluster_host_keys(cluster_cfg)}
    if not domains:
        return [], "could not determine cluster domain from connection string"
    domain = next(iter(domains))

    return sorted(f"{h}{domain}:{SEARCH_NODE_PORT}" for h in short_hostnames), None


def _fetch_search_node_measurements(client, group_id, process_id, window):
    """Query /processes/{search-host}/measurements for a Search Node process
    ID. Returns {metric: [(timestamp, value), ...]} — same shape as the
    'host' dict on mongod nodes in the other extractors."""
    base = f"/groups/{group_id}/processes/{process_id}"
    query = [("granularity", window["granularity"]), ("period", window["period"])]
    return fetch_measurements(client, f"{base}/measurements", query, SEARCH_NODE_METRICS)


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
