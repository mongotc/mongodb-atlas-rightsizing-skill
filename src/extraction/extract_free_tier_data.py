"""
Extract for free / shared / flex / serverless Atlas tiers
(M0, M2, M5, Flex, Serverless).

These tiers don't expose the host and per-disk hardware measurements the
rightsizing thresholds depend on: normalized CPU, memory used/free,
per-partition IOPS, WiredTiger cache fill, global-lock queues, etc. The
measurements endpoint on Atlas either omits them entirely or rejects them
per the tier's supported set — there is no meaningful sizing recommendation
to compute from what is available.

This extractor is deliberately a no-op: it returns a "not supported" marker
so callers can produce a clean verdict without hitting metric-related API
errors. Kept for symmetry with the other per-type extractors and so callers
have a single well-defined interface to dispatch to.
"""

from common import SHARED_TIERS, summarize_config, tier_info


def extract(client, group_id, cluster_cfg, window, processes):
    """Return a not-supported marker for shared/serverless/flex tiers.

    The signature matches extract_gen1_data and extract_shard_data so a
    dispatcher can call any of them uniformly. `client`, `group_id`,
    `window` and `processes` are intentionally unused — no Atlas calls are
    made because none of the relevant metrics are available.

    Returns:
        {
          "type": "free_tier",
          "cluster": <cluster name>,
          "tier": <tier string, e.g. "M0"; "UNKNOWN" if not identifiable>,
          "supported": False,
          "reason": <human-readable explanation>,
          "config": {"cluster_type": ..., "tiers": [...], ...},
        }
    """
    del client, group_id, window, processes  # explicitly unused

    tiers, *_ = tier_info(cluster_cfg)
    tier = tiers[0] if len(tiers) == 1 else (
        "mixed:" + ",".join(tiers) if tiers else "UNKNOWN"
    )
    return {
        "type": "free_tier",
        "cluster": cluster_cfg.get("name", ""),
        "tier": tier,
        "supported": False,
        "reason": (
            f"Tier {tier} is in the shared/free/flex/serverless set "
            f"({sorted(SHARED_TIERS)}) which doesn't expose the hardware "
            f"measurements the rightsizing thresholds depend on."
        ),
        "config": summarize_config(cluster_cfg),
    }
