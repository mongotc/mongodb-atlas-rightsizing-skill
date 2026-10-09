"""Evaluate a sharded cluster — extraction.type == "sharded".

Runs the replica-set evaluator once per shard (and once for the config
replica set) and adds an informational `no_change` row for mongos routers so the
report shows they exist without judging them against scale thresholds
(routers have no local storage or WiredTiger cache).

Sharded clusters can also run mixed tiers per shard — the connections/IOPS
checks are skipped with an explanatory note in that case (handled inside
`_context` in evaluate_replicaset).
"""

from evaluate_replicaset import _context, evaluate_group
from autoscaling import autoscaling_notes
from stats import summarize


def evaluate(extraction, thresholds, window):
    """Return one result per shard (including config RS) + one for the
    routers. Order: sorted shard names first, then routers last."""
    cluster_name = extraction.get("cluster", "")
    config = extraction.get("config") or {}
    ctx, tier_notes, _is_shared = _context(config=config, thresholds=thresholds)
    tiers = ctx["tiers"]
    tier_display = tiers[0] if len(tiers) == 1 else "mixed: " + ", ".join(tiers)
    base = {"cluster_name": cluster_name, "current_tier": tier_display,
            "cluster_type": config.get("cluster_type")}

    results = []
    shards = extraction.get("shards") or {}
    for rs_name, nodes in sorted(shards.items()):
        result = evaluate_group(nodes=nodes, ctx=ctx, thresholds=thresholds, window=window)
        result["notes"] = tier_notes + result["notes"] + autoscaling_notes(
            autoscaling=ctx.get("autoscaling"), verdict=result["verdict"],
            trigger_ids=set(result["triggers"]))
        display = f"{cluster_name} - replica set {rs_name}"
        results.append(dict(base, cluster=display, **result))

    routers = extraction.get("routers") or []
    if routers:
        results.append(dict(
            base,
            cluster=f"{cluster_name} - mongos routers ({len(routers)})",
            verdict="no_change", confidence="n/a",
            triggers=[], borderline=[], notes=[], coverage=None,
            reasons=[
                "mongos routers have no local storage or WiredTiger cache — shown for "
                "visibility only, not evaluated against the rightsizing thresholds."
            ],
            nodes=[{
                "node": n["label"], "role": n.get("role"), "hosts": n.get("hosts", []),
                "coverage": None,
                "metric_summary": {k: summarize(v) for k, v in (n.get("data") or {}).get("host", {}).items()},
            } for n in routers],
        ))
    return results
