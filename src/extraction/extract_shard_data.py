"""
Extract raw per-node metrics for a sharded Atlas cluster.

A sharded cluster is a collection of replica sets:
  - one config-server replica set (processes have typeName SHARD_CONFIG_*,
    port 27017)
  - one replica set per shard (processes have typeName REPLICA_*, port 27017)
  - one or more mongos routers per shard host (typeName SHARD_MONGOS, port
    typically 27016) — routing only, no data, no WiredTiger cache, no disks

Data-bearing nodes (shards and config server) expose the full metric set;
mongos routers expose only a limited subset. `fetch_node_metrics(...,
host_only=True)` combined with the metric-tolerant fetcher in common handles
that: metrics Atlas rejects for the router (INVALID_METRIC_NAME) are dropped
and the request retried.
"""

from common import (
    cluster_host_keys,
    fetch_node_metrics,
    group_processes_by_replica_set,
    node_hosts,
    node_label,
    process_matches,
    summarize_config,
)
from constants.atlas_mongos_metrics import ALL_METRICS as _MONGOS_METRICS

# Pre-computed list of metric names routers (mongos) actually expose. Passed
# to fetch_node_metrics for every SHARD_MONGOS process so the extraction
# captures the full ~97-metric catalog from atlas_mongos_metrics.py instead
# of the ~7-metric intersection you'd get by reusing the mongod HOST_METRICS.
MONGOS_HOST_METRICS = list(_MONGOS_METRICS.keys())


def extract(client, group_id, cluster_cfg, window, processes):
    """Return raw metrics grouped by replica set (shards + config server) plus
    a separate list for the mongos routers.

    Args:
        client:       AtlasClient
        group_id:     Atlas project (group) ID.
        cluster_cfg:  Cluster config dict (from GET /groups/{gid}/clusters/{name}).
        window:       {"granularity": "PT1H", "period": "P7D", ...}
        processes:    All processes for the project (from GET /groups/{gid}/processes).

    Returns:
        {
          "type": "sharded",
          "cluster": <cluster name>,
          "config": {"cluster_type": ..., "tiers": [...], "provisioned_iops": [...],
                     "autoscaling": {...}, "tier_notes": [...]},
          "shards": {
             "<replica_set_name>": [<node>, ...],   # one entry per shard AND
             ...                                    # one entry for the config RS
          },
          "routers": [<node>, ...],   # mongos routers; may be empty
        }
    Each <node> has the same shape as in extract_gen1_data:
      {"label", "role", "hosts", "data": {"host", "disks"}}. Router entries
      have data["disks"] == {} because they don't have local storage.
    """
    host_keys = cluster_host_keys(cluster_cfg=cluster_cfg)
    cluster_name = cluster_cfg.get("name", "")
    cluster_procs = [p for p in processes
                     if process_matches(proc=p, host_keys=host_keys, cluster_name=cluster_name)]
    shard_groups, routers = group_processes_by_replica_set(procs=cluster_procs)
    return {
        "type": "sharded",
        "cluster": cluster_name,
        "config": summarize_config(cluster_cfg=cluster_cfg),
        "shards": {
            rs_name: [_extract_node(client=client, group_id=group_id, proc=p,
                                    window=window, host_only=False)
                      for p in group if p.get("id")]
            for rs_name, group in sorted(shard_groups.items())
        },
        "routers": [_extract_node(client=client, group_id=group_id, proc=p,
                                  window=window, host_only=True,
                                  host_metrics=MONGOS_HOST_METRICS)
                    for p in routers if p.get("id")],
    }


def _extract_node(client, group_id, proc, window, host_only, host_metrics=None):
    return {
        "label": node_label(proc=proc),
        "role": proc.get("typeName"),
        "hosts": node_hosts(proc=proc),
        "data": fetch_node_metrics(client=client, group_id=group_id,
                                   process_id=proc["id"], window=window,
                                   host_only=host_only, host_metrics=host_metrics),
    }
