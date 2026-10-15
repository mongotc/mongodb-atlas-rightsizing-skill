"""
Extract raw per-node metrics for a dedicated replica set (Atlas "Gen1",
M10 and up).

A dedicated replica set is a single MongoDB replica set — typically three
nodes (one PRIMARY, two SECONDARY), optionally with read-only or analytics
nodes on the same or different tiers — running on dedicated hardware. Every
node exposes the full host and per-disk-partition metric set, so we fetch
everything for every node.

Not for sharded clusters (use extract_shard_data) or free/shared/serverless
tiers (use extract_free_tier_data).
"""

from common import (
    cluster_host_keys,
    fetch_node_metrics,
    node_hosts,
    node_label,
    process_matches,
    summarize_config,
)


def extract(client, group_id, cluster_cfg, window, processes, tier_specs=None):
    """Return raw metrics for every node in the replica set.

    Args:
        client:       AtlasClient
        group_id:     Atlas project (group) ID.
        cluster_cfg:  Cluster config dict (from GET /groups/{gid}/clusters/{name}).
        window:       {"granularity": "PT1H", "period": "P7D", ...}
        processes:    All processes for the project (from GET /groups/{gid}/processes).
        tier_specs:   list[TierSpec | None], one per regionConfig in
                      summarize_config(cluster_cfg)["regions"]. Resolved by
                      the extract.py dispatcher.

    Returns:
        {
          "type": "replica_set",
          "cluster": <cluster name>,
          "config": {"cluster_type": ..., "tiers": [...], "provisioned_iops": [...],
                     "autoscaling": {...}, "tier_notes": [...]},
          "nodes": [
            {"label": str, "role": str (typeName), "hosts": [str],
             "data": {"host": {metric: series}, "disks": {partition: {metric: series}}}},
            ...
          ],
        }
    """
    host_keys = cluster_host_keys(cluster_cfg=cluster_cfg)
    cluster_name = cluster_cfg.get("name", "")
    cluster_procs = [p for p in processes
                     if process_matches(proc=p, host_keys=host_keys, cluster_name=cluster_name)]
    return {
        "type": "replica_set",
        "cluster": cluster_name,
        "config": summarize_config(cluster_cfg=cluster_cfg),
        "nodes": [_extract_node(client=client, group_id=group_id, proc=p, window=window)
                  for p in cluster_procs if p.get("id")],
    }


def _extract_node(client, group_id, proc, window):
    return {
        "label": node_label(proc=proc),
        "role": proc.get("typeName"),
        "hosts": node_hosts(proc=proc),
        "data": fetch_node_metrics(client=client, group_id=group_id,
                                   process_id=proc["id"], window=window, host_only=False),
    }
