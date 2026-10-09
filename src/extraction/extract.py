"""
Cluster-type dispatcher.

Given a cluster config, picks the right per-type extractor and calls it. This
is the single entry point most callers should use — they don't need to know
which extractor handles which tier or cluster shape.

Dispatch rules (checked in order):
  1. Every tier is in SHARED_TIERS (M0/M2/M5/Flex/Serverless)
     -> extract_free_tier_data (no API calls; returns "not supported" marker)
  2. clusterType is SHARDED or GEOSHARDED
     -> extract_shard_data (per-shard replica sets + config-server RS + routers)
  3. Anything else (REPLICASET, or clusterType missing/unrecognized)
     -> extract_gen1_data (single dedicated replica set)

Sample call:

    from src.extraction import AtlasClient, extract_cluster

    client   = AtlasClient()                                        # reads ATLAS_* env vars
    group_id = "674f42f21212e000bcbc3735"
    cfg      = client.get(f"/groups/{group_id}/clusters/Cluster0")  # cluster config
    procs    = client.get_all(f"/groups/{group_id}/processes")      # all project processes
    window   = {"granularity": "PT1H", "period": "P7D",
                "days": 7, "label": "7 days", "expected_samples": 7 * 24}

    result = extract_cluster(client, group_id, cfg, window, procs)

    # result["type"] is one of "replica_set" | "sharded" | "free_tier"
    if result["type"] == "replica_set":
        for node in result["nodes"]:
            print(node["label"], node["role"], list(node["data"]["host"]))
    elif result["type"] == "sharded":
        for rs_name, nodes in result["shards"].items():
            print(rs_name, len(nodes), "nodes")
        print("routers:", len(result["routers"]))
    elif result["type"] == "free_tier":
        print("skip:", result["reason"])
"""

import os

import yaml

import extract_free_tier_data, extract_gen1_data, extract_search_data, extract_shard_data
from common import AtlasAPIError, AtlasClient, SHARED_TIERS, tier_info

SHARDED_CLUSTER_TYPES = {"SHARDED", "GEOSHARDED"}

# Project root = three levels up from src/extraction/extract.py, i.e.
# .../mongodb-atlas-rightsizing-skill/. Anchoring the default here means
# `output/` always lands at the project root regardless of the shell cwd
# from which the CLI is invoked.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_CONFIG_PATH = os.path.normpath(os.path.join(_PROJECT_ROOT, "src", "config.yaml"))


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


def extract(client, group_id, cluster_cfg, window, processes):
    """Dispatch to the extractor for this cluster's type/tier.

    Args are identical to the individual extractors:
        client:       AtlasClient
        group_id:     Atlas project (group) ID
        cluster_cfg:  Cluster config dict (GET /groups/{gid}/clusters/{name})
        window:       {"granularity": "PT1H", "period": "P7D", ...}
        processes:    All processes for the project (GET /groups/{gid}/processes)

    Returns whatever the chosen extractor returns; the "type" field on the
    result identifies which was used ("replica_set", "sharded", "free_tier").
    Atlas Search is orthogonal to the mongod shape (any cluster shape can
    independently have dedicated Search Nodes attached), so its result is
    attached as a sibling `search` field. Mirrors the extract_bulk wiring —
    search failures don't fail the whole extraction.
    """
    result = _pick_extractor(cluster_cfg=cluster_cfg).extract(
        client=client, group_id=group_id, cluster_cfg=cluster_cfg,
        window=window, processes=processes,
    )
    try:
        result["search"] = extract_search_data.extract(
            client=client, group_id=group_id, cluster_cfg=cluster_cfg,
            window=window, processes=processes,
        )
    except AtlasAPIError as e:
        result["search"] = {
            "type": "search",
            "cluster": cluster_cfg.get("name"),
            "error": str(e),
        }
    return result


# ---------------------------------------------------------------------------
# CLI entrypoint
#
# Package uses relative imports, so run via -m from the project root:
#
#   python -m src.extraction.extract --group-id "$ATLAS_GROUP_ID" \
#                                    --cluster Cluster0 \
#                                    --out ./extraction.json
#
# Prints the extractor's dict as JSON on stdout (or to --out). Reads Atlas
# credentials from the same env vars as scripts/rightsizing.py. Lookback
# window (days/hours/granularity) is configured in src/config.yaml under
# the `extraction:` section.
# ---------------------------------------------------------------------------

def _build_window():
    """Build the extraction window dict from src/config.yaml.

    Reads `extraction.default_hours` first; if non-null, uses the hours path
    (PT1M for short windows per `minute_granularity_hours`, else PT1H).
    Otherwise uses `extraction.default_days` with PT1H granularity.
    """
    hours = _EXTRACTION_CFG["default_hours"]
    if hours is not None:
        if hours < 1:
            raise ValueError("extraction.default_hours must be >= 1")
        granularity = "PT1M" if hours <= _EXTRACTION_CFG["minute_granularity_hours"] else "PT1H"
        return {
            "days": hours / 24, "label": f"{hours} hours",
            "period": f"PT{hours}H", "granularity": granularity,
            "expected_samples": hours * 60 if granularity == "PT1M" else hours,
        }
    days = _EXTRACTION_CFG["default_days"]
    if days < 1:
        raise ValueError("extraction.default_days must be >= 1")
    return {
        "days": float(days), "label": f"{days} days",
        "period": f"P{days}D", "granularity": "PT1H",
        "expected_samples": days * 24,
    }


# OUTPUT_DIR env var, if set, is treated as a path *relative to the project
# root* — e.g. OUTPUT_DIR=output puts files under <root>/output/<cluster>/...
# Absolute OUTPUT_DIR paths are respected as-is (os.path.join drops the root
# argument when the tail is absolute).
DEFAULT_OUT_TEMPLATE = os.path.join(
    _PROJECT_ROOT, os.environ.get("OUTPUT_DIR", "output"), "{cluster}", "extraction.json"
)


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

    result = extract(client=client, group_id=args.group_id, cluster_cfg=cluster_cfg,
                     window=window, processes=processes)
    # Stamp identity onto the result so the file is self-describing.
    result.update({
        "cluster": args.cluster,
        "project_id": args.group_id,
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
