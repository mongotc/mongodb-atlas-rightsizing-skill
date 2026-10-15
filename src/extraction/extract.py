"""
Cluster-type dispatcher.

Given a cluster config, picks the right per-type extractor and calls it. This
is the single entry point most callers should use — they don't need to know
which extractor handles which tier or cluster shape.

Dispatch rules (checked in order):
  1. Every tier is in SHARED_TIERS (M0/M2/M5/Flex/Serverless)
     -> extract_free_tier_data (no API calls; returns "not supported" marker)
  2. clusterType is SHARDED or GEOSHARDED (not tested)
     -> extract_shard_data (per-shard replica sets + config-server RS + routers)
  3. Anything else (REPLICASET, or clusterType missing/unrecognized)
     -> extract_gen1_data (single dedicated replica set)
"""

import os
import sys
import yaml

# Append (not insert) so the existing `from common import ...` continues to
# resolve to src/extraction/common.py — if we inserted at position 0, it would
# shadow onto the src/common/ package instead and break every extractor.
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

import extract_free_tier_data, extract_gen1_data, extract_search_data, extract_shard_data  # noqa: E402
from common import AtlasAPIError, AtlasClient, SHARED_TIERS, summarize_config, tier_info  # noqa: E402
from atlas_tier_spec import TierSpec, load_tier_spec  # noqa: E402

SHARDED_CLUSTER_TYPES = {"SHARDED", "GEOSHARDED"}
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CONFIG_PATH = os.path.normpath(os.path.join(_PROJECT_ROOT, "src", "config.yaml"))

# OUTPUT_DIR env var, if set, is treated as a path *relative to the project
# root* — e.g. OUTPUT_DIR=output puts files under <root>/output/<cluster>/...
# Absolute OUTPUT_DIR paths are respected as-is (os.path.join drops the root
# argument when the tail is absolute).
DEFAULT_OUT_TEMPLATE = os.path.join(
    _PROJECT_ROOT, os.environ.get("OUTPUT_DIR", "output"), "{cluster}", "extraction.json"
)

def _load_extraction_config():
    """Read the `extraction:` section of src/config.yaml. Returns a dict with
    default_days / default_hours / minute_granularity_hours. Falls back to
    hard-coded defaults if the file or section is missing so a broken yaml
    can't block an ad-hoc extraction."""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raw = {}
    e = raw.get("extraction") or {}
    return {
        "default_days": e.get("default_days", 7),
        "default_hours": e.get("default_hours"),  # None means "use days"
        "minute_granularity_hours": int(e.get("minute_granularity_hours", 36)),
        "disk_days": int(e.get("disk_days", 60)),
    }


_EXTRACTION_CFG = _load_extraction_config()


def _pick_extractor(cluster_cfg):
    """Return the extractor module suited to this cluster."""
    tiers, *_ = tier_info(cluster_cfg=cluster_cfg)
    if tiers and all(t in SHARED_TIERS for t in tiers):
        return extract_free_tier_data
    cluster_type = (cluster_cfg.get("clusterType") or "").upper()
    if cluster_type in SHARDED_CLUSTER_TYPES:
        return extract_shard_data
    return extract_gen1_data


def _resolve_tier_specs(cluster_cfg):
    config = summarize_config(cluster_cfg=cluster_cfg)
    specs: list[TierSpec | None] = []
    for region in config.get("regions") or []:
        try:
            specs.append(load_tier_spec(
                provider=region.get("provider"),
                instance_size=region.get("instance_size"),
                generation=region.get("generation"),
                cls=region.get("class"),
            ))
        except (LookupError, FileNotFoundError):
            specs.append(None)
    return specs


def extract(client, group_id, cluster_cfg, window, processes):
    tier_specs = _resolve_tier_specs(cluster_cfg=cluster_cfg)
    extractor = _pick_extractor(cluster_cfg=cluster_cfg)
    result = extractor.extract(
        client=client,
        group_id=group_id,
        cluster_cfg=cluster_cfg,
        window=window,
        processes=processes,
        tier_specs=tier_specs,
    )
    
    try:
        result["search"] = extract_search_data.extract(
            client=client, 
            group_id=group_id, 
            cluster_cfg=cluster_cfg,
            window=window, 
            processes=processes,
        )
    except AtlasAPIError as e:
        result["search"] = {
            "type": "search",
            "cluster": cluster_cfg.get("name"),
            "error": str(e),
        }
    return result


def _build_window():
    """Build the extraction window dict from src/config.yaml.

    Reads `extraction.default_hours` first; if non-null, uses the hours path
    (PT1M for short windows per `minute_granularity_hours`, else PT1H).
    Otherwise uses `extraction.default_days` with PT1H granularity.

    The returned dict also carries a nested `disk` sub-window that overrides
    just the `period` for disk-partition fetches — Atlas resets per-partition
    series under new device names on fleet maintenances, so a wider fetch
    gives us a better chance of retrieving the pre-rename history.
    """
    
    hours = _EXTRACTION_CFG["default_hours"]
    disk_days = _EXTRACTION_CFG["disk_days"]
    disk_sub = {"period": f"P{disk_days}D", "days": float(disk_days)}
    if hours is not None:
        if hours < 1:
            raise ValueError("extraction.default_hours must be >= 1")
        granularity = "PT1M" if hours <= _EXTRACTION_CFG["minute_granularity_hours"] else "PT1H"
        return {
            "days": hours / 24, "label": f"{hours} hours",
            "period": f"PT{hours}H", "granularity": granularity,
            "expected_samples": hours * 60 if granularity == "PT1M" else hours,
            "disk": disk_sub,
        }
    days = _EXTRACTION_CFG["default_days"]
    if days < 1:
        raise ValueError("extraction.default_days must be >= 1")
    return {
        "days": float(days), "label": f"{days} days",
        "period": f"P{days}D", "granularity": "PT1H",
        "expected_samples": days * 24,
        "disk": disk_sub,
    }


def console_main(argv=None):
    import argparse
    import json
    import os
    import sys

    ap = argparse.ArgumentParser(
        description="Extract raw Atlas metrics for one cluster and print as JSON. "
                    "Lookback window is configured in src/config.yaml under `extraction:`.",
    )
    ap.add_argument("--group-id", required=True, help="Atlas project (group) ID")
    ap.add_argument("--cluster", required=True, help="Cluster name")
    ap.add_argument("--out", default=DEFAULT_OUT_TEMPLATE,
                    help="Output JSON path (default: %(default)s). "
                         "'{cluster}' in the path is replaced with the cluster name; "
                         "pass '-' to write to stdout")
    args = ap.parse_args(argv)

    try:
        window = _build_window()
    except ValueError as e:
        ap.error(str(e))

    try:
        client = AtlasClient()
    except AtlasAPIError as e:
        sys.exit(str(e))

    try:
        cluster_cfg = client.get(f"/groups/{args.group_id}/clusters/{args.cluster}")
        processes = client.get_all(f"/groups/{args.group_id}/processes")
    except AtlasAPIError as e:
        sys.exit(f"Atlas API error: {e}")

    result = extract(client=client, 
                     group_id=args.group_id, 
                     cluster_cfg=cluster_cfg,
                     window=window, 
                     processes=processes)
    
    # Stamp identity + window onto the result so the file is self-describing.
    disk_sub = window.get("disk") or {}
    result.update({
        "cluster": args.cluster,
        "project_id": args.group_id,
        "window": {
            "days": window.get("days"), "label": window.get("label"),
            "period": window["period"], "granularity": window["granularity"],
            "disk": {"period": disk_sub.get("period", window["period"]),
                     "days": disk_sub.get("days", window.get("days"))},
        },
    })
    payload = json.dumps(result, indent=2, default=str)

    if args.out == "-":
        print(payload)
    else:
        out_path = args.out.replace("{cluster}", args.cluster)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"[written to {out_path}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(console_main())
