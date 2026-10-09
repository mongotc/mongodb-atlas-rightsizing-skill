"""
Atlas cluster metrics extraction, split by deployment type.

Shared core lives in `common` (AtlasClient, metric lists, metric-tolerant
fetchers, topology helpers, tier detection). Per-type extractors:

  extract_free_tier_data — M0 / M2 / M5 / Flex / Serverless (not supported)
  extract_gen1_data      — dedicated replica sets (M10+)
  extract_shard_data     — sharded clusters (SHARDED / GEOSHARDED)

This package is a parallel extraction layer intended to become the shared
source of truth. It does not replace scripts/rightsizing.py yet — the script
still runs standalone against its own copy of these primitives.
"""

from .common import (
    AtlasAPIError,
    AtlasClient,
    DISK_METRICS,
    HOST_METRICS,
    SEARCH_METRICS,
    SHARED_TIERS,
    cluster_host_keys,
    fetch_measurements,
    fetch_node_metrics,
    group_processes_by_replica_set,
    node_hosts,
    node_label,
    normalize_tier,
    process_matches,
    tier_info,
)

def __getattr__(name):
    """Lazy re-export of the dispatcher so `python -m src.extraction.extract`
    doesn't warn about the submodule being imported both here and by runpy."""
    if name == "extract_cluster":
        from .extract import extract
        return extract
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AtlasAPIError",
    "AtlasClient",
    "DISK_METRICS",
    "HOST_METRICS",
    "SEARCH_METRICS",
    "SHARED_TIERS",
    "cluster_host_keys",
    "extract_cluster",
    "fetch_measurements",
    "fetch_node_metrics",
    "group_processes_by_replica_set",
    "node_hosts",
    "node_label",
    "normalize_tier",
    "process_matches",
    "tier_info",
]
