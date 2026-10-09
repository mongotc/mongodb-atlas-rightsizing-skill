"""Evaluate a dedicated replica set — extraction.type == "replica_set".

Runs `evaluate_node` on every node and combines into a single group verdict.
The group is judged by its *worst* node so a hot primary can't be averaged
away by idle secondaries.

Ported from scripts/rightsizing.py:626-697 (`evaluate_group`) and
scripts/rightsizing.py:700-765 (the replica-set branch of `evaluate_cluster`),
adapted to read from extraction.json instead of the Atlas API.
"""

import os
import sys

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from constants.tiers import SHARED_TIERS, TIER_MAX_CONNECTIONS, normalize_tier  # noqa: E402
from constants.verdicts import DISK_TRIGGERS  # noqa: E402

from autoscaling import autoscaling_notes  # noqa: E402
from node_eval import evaluate_node  # noqa: E402


def _confidence(verdict, trigger_ids, window_days, coverage, borderline, missing, thresholds):
    if window_days < 3 or coverage < thresholds.min_coverage or missing:
        return "low"
    if verdict == "scale_up":
        if window_days < 7 or len(trigger_ids) < 2:
            return "medium"
        return "high"
    if borderline:
        return "low"
    return "medium" if window_days < 7 else "high"


def _context(config, thresholds):
    """Turn the extraction.config block into an evaluator context + notes.

    Returns (ctx, notes, is_shared_only). `is_shared_only` is True when every
    tier is a shared/free/flex/serverless tier — the caller should short-
    circuit to a no_change verdict with the 'shared tier' reason."""
    cfg = config or {}
    tiers = cfg.get("tiers") or ["UNKNOWN"]
    iops_values = cfg.get("provisioned_iops") or []
    autoscaling = cfg.get("autoscaling") or {"compute": None, "disk": False}
    tier_notes = list(cfg.get("tier_notes") or [])

    is_shared_only = bool(tiers) and all(t in SHARED_TIERS for t in tiers)

    max_connections = None
    if len(tiers) == 1:
        max_connections = TIER_MAX_CONNECTIONS.get(normalize_tier(tier=tiers[0]))
        if not max_connections and tiers[0] not in SHARED_TIERS:
            tier_notes.append(f"Connections check skipped: no known connection limit for tier {tiers[0]}.")
    elif len(tiers) > 1:
        tier_notes.append("Connections check skipped: shards run different tiers, so there is no single limit.")

    provisioned_iops = iops_values[0] if len(iops_values) == 1 else None
    if len(iops_values) > 1:
        tier_notes.append(
            f"IOPS check skipped: shards have different provisioned IOPS "
            f"({', '.join(map(str, iops_values))}); check IOPS headroom per shard in the Atlas UI."
        )
    elif not iops_values:
        tier_notes.append("IOPS check skipped: the cluster config doesn't report provisioned diskIOPS.")

    return (
        {
            "provisioned_iops": provisioned_iops, 
            "max_connections": max_connections,
            "autoscaling": autoscaling, 
            "tiers": tiers
        },
        tier_notes,
        is_shared_only,
    )


def evaluate_group(nodes, ctx, thresholds, window):
    """Evaluate a list of nodes as a single group and return a partial result.

    `nodes` items match the extraction shape: {"label", "role", "hosts", "data"}.
    Return shape matches scripts/rightsizing.py:626-697."""
    
    per_node = [(n, evaluate_node(data=n["data"], ctx={**ctx, "window": window}, thresholds=thresholds))
                for n in nodes]
    
    node_rows = [
        {"node": n["label"], "role": n.get("role"), "hosts": n.get("hosts", []),
         "coverage": r["coverage"], "metric_summary": r["summary"]}
        for n, r in per_node
    ]

    if not per_node or not any(any(v for v in r["summary"].values()) for _, r in per_node):
        return {
            "verdict": "no_change", "confidence": "low",
            "triggers": [], "borderline": [],
            "reasons": [
                "Not enough data points: no metrics were returned for the requested window. "
                "No processes matched, or the cluster is too new, paused, or unreachable. "
                "Re-run once the cluster has operating history."
            ],
            "coverage": 0.0, "nodes": node_rows, "notes": [],
        }

    triggers, borderline, notes = [], [], []
    for n, r in per_node:
        triggers += [
            {"id": t["id"], "node": n["label"], "text": f"{n['label']}: {t['text']}"}
            for t in r["triggers"]
        ]
        borderline += [f"{n['label']}: {b}" for b in r["borderline"]]
        if r["missing"]:
            notes.append(f"{n['label']}: missing core metrics {', '.join(r['missing'])}")
    missing = any(r["missing"] for _, r in per_node)
    coverage = min(r["coverage"] for _, r in per_node)
    trigger_ids = {t["id"] for t in triggers}

    if coverage < thresholds.min_coverage:
        notes.append(
            f"Data coverage is {coverage:.0%} of the expected samples for the lowest "
            f"node/metric (gaps from restarts, a cluster younger than the window, or "
            f"missing data)."
        )

    if triggers:
        verdict = "scale_up"
        reasons = [t["text"] for t in triggers]
        if trigger_ids <= set(DISK_TRIGGERS):
            reasons.append(
                "Only disk signals fired: check whether more IOPS or disk (not a compute "
                "tier change) resolves it."
            )
    elif missing:
        verdict = "no_change"
        reasons = [
            "Not enough data points: core metrics (CPU, memory or disk space) are missing "
            "for at least one node. Re-extract and re-run."
        ]
    elif (all(all(r["down_checks"].values()) for _, r in per_node)
          and window["days"] >= 7 and coverage >= thresholds.min_coverage
          and not borderline):
        verdict = "scale_down"
        reasons = [
            "Every node is comfortably under all scale-down limits (CPU, memory, disk space, "
            "IOPS, latency, cache, queues, connections)."
        ]
    else:
        verdict = "no_change"
        # Data-sparsity short-circuits any other analysis — if the window is
        # too short or coverage is too low, no scale-down (or scale-down-block)
        # reasoning is trustworthy. Report only "not enough data points".
        expected = int(window.get("expected_samples") or 0)
        actual = int(round(coverage * expected)) if expected else 0
        if window["days"] < 7 or coverage < thresholds.min_coverage:
            if expected and coverage < thresholds.min_coverage:
                reasons = [
                    f"Not enough data points: {actual} of {expected} expected samples "
                    f"({window['days']:.1f} days). Need ≥ 7 days and ≥ "
                    f"{thresholds.min_coverage:.0%} coverage — collect more history "
                    f"and re-run."
                ]
            else:
                reasons = [
                    f"Not enough data points: only {window['days']:.1f} days of data "
                    f"(need ≥ 7). Collect more history and re-run."
                ]
        else:
            # Full-coverage, 7+ day window — now the down_checks and borderline
            # signals are meaningful.
            failed = sorted({
                name for _, r in per_node for name, ok in r["down_checks"].items() if not ok
            })
            if failed:
                reasons = [f"No scale-up thresholds crossed; scale-down bars not met for: "
                           f"{', '.join(failed)}."]
            else:
                reasons = ["No scale-up thresholds crossed."]
            if borderline:
                reasons[0] += " Some metrics are close to a trigger (see below)."

    if verdict == "scale_down" and not ctx.get("provisioned_iops"):
        notes.append("IOPS headroom was not checked: the cluster config doesn't report provisioned diskIOPS.")

    return {
        "verdict": verdict,
        "confidence": _confidence(verdict=verdict, trigger_ids=trigger_ids,
                                  window_days=window["days"], coverage=coverage,
                                  borderline=borderline, missing=missing,
                                  thresholds=thresholds),
        "triggers": sorted(trigger_ids),
        "reasons": reasons,
        "borderline": borderline,
        "notes": notes,
        "coverage": round(coverage, 3),
        "nodes": node_rows,
    }


def evaluate(extraction, thresholds, window):
    """Evaluate a replica-set extraction.json.

    Returns a list with one result dict (mirrors the sharded evaluator's
    shape, which returns many)."""
    cluster_name = extraction.get("cluster", "")
    config = extraction.get("config") or {}
    ctx, tier_notes, is_shared_only = _context(config=config, thresholds=thresholds)
    tiers = ctx["tiers"]
    tier_display = tiers[0] if len(tiers) == 1 else "mixed: " + ", ".join(tiers)
    base = {"cluster_name": cluster_name, "current_tier": tier_display,
            "cluster_type": config.get("cluster_type")}

    if is_shared_only:
        return [dict(base, cluster=cluster_name, verdict="no_change", confidence="n/a",
                     triggers=[], borderline=[], notes=[], coverage=None, nodes=[],
                     reasons=["Shared/free/flex/serverless tier — hardware measurements aren't "
                              "exposed, so the rightsizing thresholds can't be evaluated."])]

    result = evaluate_group(nodes=extraction.get("nodes") or [], ctx=ctx,
                            thresholds=thresholds, window=window)
    result["notes"] = tier_notes + result["notes"] + autoscaling_notes(
        autoscaling=ctx.get("autoscaling"), verdict=result["verdict"],
        trigger_ids=set(result["triggers"]))
    return [dict(base, cluster=cluster_name, **result)]
