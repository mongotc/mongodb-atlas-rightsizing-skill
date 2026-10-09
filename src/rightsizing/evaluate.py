"""Dispatcher: read an extraction.json, pick the right evaluator by cluster
type, and always evaluate Atlas Search if it's present on the cluster.

  type == "replica_set" -> evaluate_replicaset
  type == "sharded"     -> evaluate_shard
  type == "free_tier"   -> synthetic no_change result with "shared/free tier" reason

Atlas Search is orthogonal to the mongod deployment shape (see
src/extraction/extract_search_data.py:32-34), so this dispatcher always runs
the Search evaluator when `extraction.search.present` and appends its result.
"""

import evaluate_replicaset
import evaluate_search
import evaluate_shard


def evaluate(extraction, thresholds, window):
    """Return a list of per-cluster / per-shard / per-Search-deployment result
    dicts, suitable for report.build_report_md / write_report_json."""
    t = extraction.get("type")
    cluster_name = extraction.get("cluster", "")

    if t == "replica_set":
        results = evaluate_replicaset.evaluate(extraction=extraction, thresholds=thresholds, window=window)
    elif t == "sharded":
        results = evaluate_shard.evaluate(extraction=extraction, thresholds=thresholds, window=window)
    elif t == "free_tier":
        tier = extraction.get("tier") or "UNKNOWN"
        results = [{
            "cluster_name": cluster_name, "cluster": cluster_name,
            "current_tier": tier,
            "cluster_type": (extraction.get("config") or {}).get("cluster_type"),
            "verdict": "no_change", "confidence": "n/a",
            "triggers": [], "borderline": [], "notes": [], "coverage": None, "nodes": [],
            "reasons": [extraction.get("reason") or
                        f"Shared/free tier {tier} — doesn't expose the hardware "
                        f"measurements the rightsizing thresholds depend on."],
        }]
    else:
        results = [{
            "cluster_name": cluster_name, "cluster": cluster_name,
            "current_tier": "UNKNOWN", "cluster_type": None,
            "verdict": "error", "confidence": "n/a",
            "triggers": [], "borderline": [], "notes": [], "coverage": None, "nodes": [],
            "reasons": [f"Unknown extraction type: {t!r}"],
        }]

    search = extraction.get("search")
    if search and search.get("present"):
        search_result = evaluate_search.evaluate(search=search, thresholds=thresholds, window=window)
        if search_result:
            results.append(search_result)
    return results
