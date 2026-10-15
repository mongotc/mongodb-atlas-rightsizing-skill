"""Evaluate the Atlas Search deployment — extraction.search subtree.

Search is orthogonal to the mongod cluster shape (a replica set, sharded
cluster or free-tier cluster can each independently have dedicated Search
Nodes attached), so it always runs alongside the primary evaluator when
`extraction.search.present` is true.

Two data sources on a Search deployment:

  1. Per-Search-Node SYSTEM_* metrics (CPU, memory, network) under
     `extraction.search.search_nodes[]`. Auto-discovered from
     /clusters/{name}/search/indexes, so present only when the cluster has
     Search indexes defined AND dedicated Search Nodes provisioned.

  2. FTS_PROCESS_* metrics attributed to the *mongod* host serving queries
     (Atlas does not attribute FTS work to the mongot process). These live
     under `extraction.search.mongod_hosts[].data.fts`. Summarized as
     context; no trigger — FTS thresholds are heuristic and will migrate
     from references/search-thresholds.md once that lands.

This evaluator produces ONE result row for the whole Search deployment.
"""

from stats import combine, summarize
import operator


def evaluate(search, thresholds, window):
    """Return a single result dict for the Search deployment, or None if
    search is not present on this cluster."""
    if not search or not search.get("present"):
        return None

    cluster_name = search.get("cluster", "")
    specs = search.get("specs") or []
    spec_display = ", ".join(
        f"{s.get('node_count')}x {s.get('instance_size')}"
        f"{(' in ' + s.get('region_name')) if s.get('region_name') else ''}"
        for s in specs
    ) or "unknown"

    base = {
        "cluster_name": cluster_name,
        "cluster": f"{cluster_name} - Atlas Search",
        "current_tier": spec_display,
        "cluster_type": "SEARCH",
    }

    per_node_results, triggers, borderline, node_rows, missing = [], [], [], [], []
    for node in search.get("search_nodes") or []:
        r = _evaluate_search_node(node=node, thresholds=thresholds, window=window)
        per_node_results.append(r)
        triggers += r["triggers"]
        borderline += r["borderline"]
        node_rows.append(r["row"])
        if r["missing"]:
            missing.append(f"{r['row']['node']}: missing {', '.join(r['missing'])}")

    # FTS metrics on mongod hosts — context only.
    for mh in search.get("mongod_hosts") or []:
        fts = ((mh.get("data") or {}).get("fts") or {})
        if not fts or "__error__" in fts:
            continue
        node_rows.append({
            "node": f"{mh.get('label')} (FTS on mongod, context)",
            "role": mh.get("role"),
            "hosts": mh.get("hosts", []),
            "coverage": None, "compute_coverage": None, "disk_coverage": None,
            "metric_summary": {k: summarize(v) for k, v in fts.items()},
        })

    if not per_node_results:
        return dict(base, verdict="no_change", confidence="low",
                    triggers=[], borderline=borderline, notes=[],
                    coverage=None, compute_coverage=None, disk_coverage=None,
                    nodes=node_rows,
                    reasons=[
                        "Not enough data points: no per-Search-Node metrics were returned. "
                        "Dedicated Search Nodes aren't provisioned, no Search indexes exist "
                        "yet, or auto-discovery via /clusters/{name}/search/indexes failed."
                    ])

    trigger_ids = sorted({t["id"] for t in triggers})
    coverage = min((r["coverage"] for r in per_node_results if r["coverage"] is not None),
                   default=0.0)
    all_down = all(r["down_ok"] for r in per_node_results)

    if triggers:
        verdict = "scale_up"
        reasons = [t["text"] for t in triggers]
    elif all_down and window["days"] >= 7 and coverage >= thresholds.min_coverage and not borderline:
        verdict = "scale_down"
        reasons = [
            "Every Search Node is comfortably under the CPU and free-memory scale-down bars."
        ]
    else:
        verdict = "no_change"
        if window["days"] < 7 or coverage < thresholds.min_coverage:
            reasons = [
                f"Not enough data points: only {window['days']:.1f} days of data at "
                f"{coverage:.0%} coverage. Need ≥ 7 days and ≥ "
                f"{thresholds.min_coverage:.0%} coverage — collect more history and re-run."
            ]
        else:
            reasons = ["No Search Node crossed the CPU or memory triggers."]
            if borderline:
                reasons = [
                    "No Search Node crossed the triggers, but some metrics are close (see below)."
                ]

    notes = ["Search thresholds are heuristic (see references/search-thresholds.md when available); "
             "FTS_PROCESS_* metrics on mongod hosts are summarized for context but do not trigger."]
    if missing:
        notes += missing

    # Search Nodes have no local disk partitions exposed to Atlas monitoring,
    # so disk_coverage mirrors compute_coverage. Both are reported for a
    # consistent result shape across cluster types.
    return dict(
        base,
        verdict=verdict,
        confidence=_confidence(verdict=verdict, window_days=window["days"],
                               coverage=coverage, thresholds=thresholds),
        triggers=trigger_ids, reasons=reasons, borderline=borderline, notes=notes,
        coverage=round(coverage, 3),
        compute_coverage=round(coverage, 3),
        disk_coverage=round(coverage, 3),
        nodes=node_rows,
    )


def _evaluate_search_node(node, thresholds, window):
    process_id = node.get("process_id", "unknown")
    host = ((node.get("data") or {}).get("host") or {})

    cpu_pts = combine(a=host.get("SYSTEM_NORMALIZED_CPU_USER"),
                      b=host.get("SYSTEM_NORMALIZED_CPU_KERNEL"),
                      fn=operator.add)
    cpu = summarize(points=cpu_pts)

    mem_pts = [
        (ts, v) for ts, v in combine(
            a=host.get("SYSTEM_MEMORY_FREE"),
            b=host.get("SYSTEM_MEMORY_USED"),
            fn=lambda free, used: 100.0 * free / (free + used) if free + used > 0 else None,
        ) if v is not None
    ]
    mem = summarize(points=mem_pts)

    triggers, borderline = [], []
    if cpu:
        if cpu["p95"] > thresholds.mongot_host.cpu_up_pct:
            triggers.append({"id": "search_cpu", "text":
                f"{process_id}: Search Node CPU (user+kernel) p95 {cpu['p95']}% > "
                f"{thresholds.mongot_host.cpu_up_pct}%"})
        elif cpu["p95"] >= thresholds.mongot_host.cpu_up_pct * (1 - thresholds.near_threshold):
            borderline.append(
                f"{process_id}: CPU p95 {cpu['p95']}% within "
                f"{int(thresholds.near_threshold * 100)}% of the {thresholds.mongot_host.cpu_up_pct}% trigger"
            )

    if mem:
        if mem["p5"] < thresholds.mongot_host.mem_free_up_pct:
            triggers.append({"id": "search_memory", "text":
                f"{process_id}: Search Node free memory p5 {mem['p5']}% < "
                f"{thresholds.mongot_host.mem_free_up_pct}%"})
        elif mem["p5"] <= thresholds.mongot_host.mem_free_up_pct * (1 + thresholds.near_threshold):
            borderline.append(
                f"{process_id}: free memory p5 {mem['p5']}% within "
                f"{int(thresholds.near_threshold * 100)}% of the {thresholds.mongot_host.mem_free_up_pct}% trigger"
            )

    summary = {name: summarize(pts) for name, pts in host.items()}
    if cpu:
        summary["CPU_USER_PLUS_KERNEL"] = cpu
    if mem:
        summary["MEMORY_FREE_PCT"] = mem

    core_series = [host.get("SYSTEM_NORMALIZED_CPU_USER") or [],
                   host.get("SYSTEM_NORMALIZED_CPU_KERNEL") or [],
                   host.get("SYSTEM_MEMORY_USED") or [],
                   host.get("SYSTEM_MEMORY_FREE") or []]
    expected = window["expected_samples"]
    coverage = min(min(len(s) / expected, 1.0) for s in core_series) if expected else 0.0

    down_ok = bool(cpu and cpu["p95"] < thresholds.mongot_host.cpu_down_pct) \
        and bool(mem and mem["p5"] > thresholds.mongot_host.mem_free_down_pct)

    missing = []
    if not cpu:
        missing.append("CPU")
    if not mem:
        missing.append("memory")

    return {
        "row": {
            "node": process_id, "role": "SEARCH_NODE", "hosts": [process_id.split(":", 1)[0]],
            "coverage": round(coverage, 3),
            "compute_coverage": round(coverage, 3),
            "disk_coverage": round(coverage, 3),
            "metric_summary": summary,
        },
        "triggers": triggers,
        "borderline": borderline,
        "coverage": coverage,
        "down_ok": down_ok,
        "missing": missing,
    }


def _confidence(verdict, window_days, coverage, thresholds):
    if window_days < 3 or coverage < thresholds.min_coverage:
        return "low"
    return "medium" if window_days < 7 else "high"
