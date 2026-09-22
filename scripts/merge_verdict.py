#!/usr/bin/env python3
"""
Merge an Atlas hardware-metrics rightsizing report (rightsizing.py) with database-internal
diagnostics (db_diagnostics.py) into one combined report.

rightsizing.py answers "is the hardware under pressure." db_diagnostics.py answers "why, and is
more hardware actually the fix." The combination rules are documented in
references/db-diagnostics.md; keep that file and the constants below in sync.

--db-diagnostics is OPTIONAL. Without it, the Atlas-only verdicts pass through unchanged and are
labeled as Atlas-only. If a path IS given but can't be read, that's an error, not a silent
fallback.

Core rule: when the two sources disagree, SURFACE the disagreement; never silently prefer one.

This script is READ-ONLY and makes no network calls; it only reads the two JSON files.

Usage:
  python merge_verdict.py --rightsizing-report ./report/report.json \\
      --db-diagnostics ./report/db_diagnostics.json --out-dir ./report

  # Atlas-only (no DB credentials available):
  python merge_verdict.py --rightsizing-report ./report/report.json --out-dir ./report
"""

import argparse
import json
import os
from datetime import datetime, timezone

# Heuristic: documents examined per document returned. Not from official docs; a legitimate
# aggregation or report query can exceed it without a missing index, which is why a collection-scan
# rate > 0 is also required when the server reports it.
HIGH_EXAMINED_RATIO = 10
WT_CACHE_MODERATE_PCT = 60   # below this + data fits in cache => memory pressure isn't WiredTiger
WT_CACHE_FULL_PCT = 80       # WT eviction_target
DB_CONNECTIONS_ELEVATED_PCT = 60

EVALUATED_VERDICTS = {"scale_up", "disk_iops_only", "scale_down_candidate", "no_change"}
RELATION_LABELS = {"agrees": "[AGREES]", "disagrees": "[DISAGREES]",
                   "root_cause": "[LIKELY ROOT CAUSE]", "context": "[CONTEXT]"}
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def finding(signal, relation, note, **extra):
    return dict({"signal": signal, "relation": relation, "note": note}, **extra)


def total_data_bytes(footprint):
    """dataSize + indexSize summed over every inspected database. This is an upper bound on the
    working set, not the working set. None if nothing usable was collected."""
    total, saw_any = 0, False
    for stats in (footprint or {}).values():
        if not isinstance(stats, dict) or "error" in stats:
            continue
        total += (stats.get("data_size_bytes") or 0) + (stats.get("index_size_bytes") or 0)
        saw_any = True
    return int(total) if saw_any else None


def analyze_cpu(triggers, db, window_label):
    if "cpu" not in triggers:
        return None
    examined, returned = db.get("docs_examined_per_sec"), db.get("docs_returned_per_sec")
    ratio, scans = db.get("examined_to_returned_ratio"), db.get("collection_scans_per_sec")
    if not examined or ratio is None:
        return None
    ratio_value = float("inf") if ratio == "inf" else ratio
    ratio_text = "no documents returned" if ratio == "inf" else f"{ratio}:1"
    if ratio_value <= HIGH_EXAMINED_RATIO:
        return finding("cpu_scan_efficiency_ok", "agrees", (
            f"Queries look efficient (examined:returned {ratio_text}), so the CPU pressure is more likely "
            f"real load than missing indexes. A compute scale-up is a reasonable fix."))
    if scans is not None and scans <= 0:
        return finding("cpu_scan_ratio_no_collscans", "context", (
            f"Examined:returned is {ratio_text} ({examined}/sec examined vs {returned}/sec returned), but no "
            f"collection scans ran during the sample. That pattern fits aggregations or large index range "
            f"scans more than missing indexes; check Performance Advisor before assuming either."))
    scan_text = f", {scans} collection scans/sec" if scans is not None else ""
    return finding("cpu_vs_scan_efficiency", "root_cause", (
        f"Atlas CPU trigger AND examined:returned is {ratio_text} ({examined}/sec examined vs {returned}/sec "
        f"returned{scan_text}). The root cause is likely missing or poor indexes, not undersized compute. "
        f"Review indexes (Atlas Performance Advisor or explain()) BEFORE a tier bump: it's cheaper, and "
        f"scaling up would hide the problem while costing more every month."),
        lead_with_schema_fix=True)


def analyze_memory(triggers, db, footprint, window_label):
    if not triggers & {"memory", "cache_fill", "page_faults"}:
        return None
    pct, cache_max = db.get("wt_cache_pct_used"), db.get("wt_cache_bytes_max")
    total = total_data_bytes(footprint)
    if pct is None or not cache_max or total is None:
        return None
    if total > cache_max:
        ratio = total / cache_max
        if "page_faults" in triggers:
            return finding("memory_consistent", "agrees", (
                f"Total data+index size ({total:,} bytes) is {ratio:.1f}x the WiredTiger cache ({cache_max:,} "
                f"bytes, {pct}% full) and Atlas shows page-fault pressure. That's consistent with the hot set "
                f"not fitting in cache. Total size is only an upper bound on the working set."))
        return finding("memory_inconclusive", "context", (
            f"Total data+index size ({total:,} bytes) is {ratio:.1f}x the WiredTiger cache ({cache_max:,} "
            f"bytes, {pct}% full). That's normal and doesn't show the hot set doesn't fit: Atlas shows no "
            f"page-fault pressure. Judge the memory signal on its Atlas evidence alone."))
    if pct < WT_CACHE_MODERATE_PCT:
        return finding("memory_unconfirmed", "disagrees", (
            f"Atlas flagged memory/cache pressure, but all data+indexes ({total:,} bytes) fit in the "
            f"WiredTiger cache ({cache_max:,} bytes) and the cache is only {pct}% full. The pressure Atlas "
            f"sees probably isn't coming from WiredTiger (another process, normal OS page cache, or a short "
            f"spike). Don't recommend a memory-driven scale-up from the Atlas signal alone."),
            confidence_override="low")
    return None


def analyze_connections(triggers, db, window_label):
    db_pct = db.get("connections_pct_used")
    if db_pct is None:
        return None
    atlas_fired = "connections" in triggers
    elevated = db_pct > DB_CONNECTIONS_ELEVATED_PCT
    if atlas_fired and elevated:
        return finding("connections_agree", "agrees", (
            f"Atlas connections trigger AND the live snapshot shows {db_pct}% of connections in use: real "
            f"connection pressure. Often an application connection-pooling problem as much as a tier "
            f"problem; mention both fixes."))
    if atlas_fired:
        return finding("connections_disagree", "disagrees", (
            f"Atlas flagged connection pressure over {window_label}, but the live snapshot shows only "
            f"{db_pct}% in use. Different sampling windows, or a spike that has since resolved. Check the "
            f"Atlas connections chart for when it happened before treating it as confirmed."),
            confidence_override="medium")
    if elevated:
        return finding("connections_disagree", "disagrees", (
            f"The live snapshot shows {db_pct}% of connections in use, but Atlas's p95 over {window_label} "
            f"didn't cross the trigger. The snapshot may have caught a spike the wider window smoothed out; "
            f"look at recent connection counts before dismissing it."))
    return None


def analyze_disk(triggers, db, window_label):
    read_side = triggers & {"iops", "disk_latency_read"}
    if not read_side and "disk_latency_write" not in triggers:
        return None
    if not read_side:
        return finding("disk_write_side", "context", (
            "Only write latency fired, which cache misses don't explain. Look at write volume and "
            "checkpoint pressure (DIRTY_FILL_RATIO) rather than cache size."))
    pct = db.get("wt_cache_pct_used")
    read_in, evicted = db.get("wt_pages_read_into_cache_per_sec"), db.get("wt_pages_evicted_per_sec")
    if pct is not None and pct >= WT_CACHE_FULL_PCT and read_in and evicted:
        return finding("disk_cache_miss_driven", "root_cause", (
            f"Atlas disk read signal AND the WiredTiger cache is {pct}% full while reading {read_in} "
            f"pages/sec in and evicting {evicted}/sec: read I/O is likely cache misses. More RAM (or a "
            f"smaller hot set) may fix it better than more IOPS."))
    return None


def source_hosts(db_diagnostics):
    src = db_diagnostics.get("source") or {}
    return {h.lower().split(":")[0] for h in src.get("hosts", []) if h}


def select_results(results, db_diagnostics, allow_host_mismatch):
    """Pick the report rows this snapshot applies to. Returns (rows, warnings).

    Only rows with an evaluated verdict are candidates (not mongos, errors or insufficient data).
    Rows are matched on host names, so a diagnostics file from a different cluster is rejected."""
    candidates = [r for r in results if r.get("verdict") in EVALUATED_VERDICTS]
    hosts = source_hosts(db_diagnostics)
    src = db_diagnostics.get("source") or {}
    if not hosts:
        return candidates, ["The diagnostics file doesn't record which host it came from (older format), "
                            "so it could not be matched to a cluster; it is applied to every evaluated row."]

    def row_hosts(r):
        return {h for n in r.get("nodes", []) for h in n.get("hosts", [])}

    direct = [r for r in results if hosts & row_hosts(r)]
    if not direct:
        msg = (f"The diagnostics file came from {', '.join(sorted(hosts))}, which doesn't match any node in "
               f"the rightsizing report.")
        if not allow_host_mismatch:
            raise SystemExit(msg + " Re-run db_diagnostics.py against the right cluster, or pass "
                                   "--allow-host-mismatch if the hostnames are aliases of the same nodes.")
        return candidates, [msg + " Applied anyway because --allow-host-mismatch was given."]

    if src.get("is_mongos"):
        clusters = {(r.get("group_id"), r.get("cluster_name")) for r in direct}
        rows = [r for r in candidates if (r.get("group_id"), r.get("cluster_name")) in clusters]
        warnings = []
        if len(rows) > 1:
            warnings.append(
                "This snapshot came through mongos but the cluster has several shards/replica sets. The "
                "db-internal signals reflect the whole cluster from one connection point and can hide a hot "
                "shard; re-run db_diagnostics.py against a shard primary if one is suspected.")
        return rows, warnings
    return [r for r in candidates if any(r is d for d in direct)], []


def analyze_result(result, db_diagnostics, window_label):
    """Run every combination rule for one report row."""
    db = db_diagnostics.get("server_status_summary", {})
    footprint = db_diagnostics.get("data_footprint", db_diagnostics.get("working_set", {}))
    triggers = set(result.get("triggers", []))
    notes = []
    for analyzer in (analyze_cpu, analyze_connections, analyze_disk):
        f = analyzer(triggers, db, window_label)
        if f:
            notes.append(f)
    f = analyze_memory(triggers, db, footprint, window_label)
    if f:
        notes.append(f)
    return notes


def merged_confidence(atlas_confidence, findings):
    if atlas_confidence not in CONFIDENCE_ORDER:
        return atlas_confidence
    level = atlas_confidence
    for f in findings:
        override = f.get("confidence_override")
        if override and CONFIDENCE_ORDER[override] < CONFIDENCE_ORDER[level]:
            level = override
    return level


def merge(rightsizing_report, db_diagnostics, allow_host_mismatch=False):
    """Return (merged_results, warnings). Each result gains combined_analysis / merged_confidence."""
    window_label = rightsizing_report.get("windowLabel", f"{rightsizing_report.get('windowDays')} days")
    results = rightsizing_report.get("results", [])
    if not db_diagnostics:
        return [dict(r, applies=False, combined_analysis=[], merged_confidence=r.get("confidence"))
                for r in results], []
    rows, warnings = select_results(results, db_diagnostics, allow_host_mismatch)
    warnings = warnings + [f"Diagnostics note: {n}" for n in db_diagnostics.get("server_status_summary", {}).get("notes", [])]
    merged = []
    for r in results:
        applies = any(r is row for row in rows)
        findings = analyze_result(r, db_diagnostics, window_label) if applies else []
        merged.append(dict(r, applies=applies, combined_analysis=findings,
                           merged_confidence=merged_confidence(r.get("confidence"), findings)))
    return merged, warnings


def build_merged_report(rightsizing_report, merged, warnings, db_diagnostics, db_diagnostics_path):
    lines = ["# Merged Rightsizing + DB Diagnostics Report", ""]
    projects = rightsizing_report.get("groupIds") or [rightsizing_report.get("groupId")]
    lines.append(f"Project(s): {', '.join(f'`{p}`' for p in projects if p)}  |  "
                 f"Lookback: {rightsizing_report.get('windowLabel', rightsizing_report.get('windowDays'))}  |  "
                 f"Generated: {utc_now()}")
    lines.append("")

    if not db_diagnostics:
        lines.append("**Mode: ATLAS-ONLY**: no `--db-diagnostics` file given. The verdicts below are exactly "
                     "what `rightsizing.py` produced from Atlas hardware metrics. With a MongoDB user that has "
                     "`clusterMonitor` and read access, run `db_diagnostics.py` and re-run this merge for "
                     "root-cause analysis (e.g. \"add an index\" vs \"buy a bigger cluster\"); see "
                     "references/db-diagnostics.md.")
    else:
        src = db_diagnostics.get("source") or {}
        where = ", ".join(src.get("hosts", [])) or "unknown host"
        lines.append(f"**Mode: COMBINED**: merged with `{db_diagnostics_path}` (sampled "
                     f"{db_diagnostics.get('sampled_at', 'unknown time')} from {where}"
                     f"{' via mongos' if src.get('is_mongos') else ''}).")
        for w in warnings:
            lines += ["", f"**WARNING:** {w}"]
    lines.append("")

    for r in merged:
        lines.append(f"## {r['cluster']}  —  {r['current_tier']}")
        findings = r.get("combined_analysis", [])
        if any(f.get("lead_with_schema_fix") for f in findings):
            lines.append("**Recommended first step: index/query review.** A tier change is the fallback if "
                         "that doesn't relieve the pressure.")
            lines.append("")
        confidence = r.get("confidence")
        if r.get("merged_confidence") != confidence:
            confidence = f"{r.get('merged_confidence')} (Atlas-only: {r.get('confidence')})"
        lines.append(f"**Atlas verdict: {r['verdict'].replace('_', ' ').upper()}**  (confidence: {confidence})")
        lines.append("")
        lines += [f"- {reason}" for reason in r.get("reasons", [])]
        if r.get("borderline"):
            lines += ["", "**Close to a trigger:**"] + [f"- {b}" for b in r["borderline"]]
        if r.get("notes"):
            lines += ["", "**Notes:**"] + [f"- {n}" for n in r["notes"]]
        lines.append("")
        if db_diagnostics:
            if not r.get("applies"):
                lines.append("*DB diagnostics not applied to this row (not evaluated, or the snapshot came from "
                             "a different replica set).*")
                lines.append("")
            elif findings:
                lines.append("**Combined analysis (Atlas + DB-internal):**")
                lines.append("")
                for f in findings:
                    lines.append(f"{RELATION_LABELS.get(f['relation'], '[CONTEXT]')} {f['note']}")
                    lines.append("")
            elif r.get("verdict") in ("scale_up", "disk_iops_only"):
                lines.append("*No db-internal signal corroborated or contradicted this verdict; the Atlas-only "
                             "reasoning above stands on its own.*")
                lines.append("")

    lines.append("---")
    lines.append("This is a read-only recommendation. No cluster was modified.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rightsizing-report", required=True, help="Path to rightsizing.py's report.json")
    ap.add_argument("--db-diagnostics", default=None,
                    help="Path to db_diagnostics.py's db_diagnostics.json (optional; omit for Atlas-only)")
    ap.add_argument("--allow-host-mismatch", action="store_true",
                    help="Apply the diagnostics even if its host doesn't match any node in the report")
    ap.add_argument("--out-dir", default="./rightsizing-report")
    args = ap.parse_args(argv)

    try:
        rightsizing_report = load_json(args.rightsizing_report)
    except (OSError, ValueError) as e:
        raise SystemExit(f"Could not read rightsizing report {args.rightsizing_report}: {e}")

    db_diagnostics = None
    if args.db_diagnostics:
        try:
            db_diagnostics = load_json(args.db_diagnostics)
        except (OSError, ValueError) as e:
            raise SystemExit(f"Could not read --db-diagnostics {args.db_diagnostics}: {e}. "
                             f"Fix the path, or omit the flag for an Atlas-only report.")

    merged, warnings = merge(rightsizing_report, db_diagnostics, args.allow_host_mismatch)
    merged_md = build_merged_report(rightsizing_report, merged, warnings, db_diagnostics, args.db_diagnostics)

    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "merged_report.md"), "w", encoding="utf-8") as f:
        f.write(merged_md)
    with open(os.path.join(args.out_dir, "merged_report.json"), "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": utc_now(),
            "groupIds": rightsizing_report.get("groupIds") or [rightsizing_report.get("groupId")],
            "mode": "combined" if db_diagnostics else "atlas_only",
            "warnings": warnings,
            "results": merged,
        }, f, indent=2)

    print(merged_md)
    print(f"\n[written to {args.out_dir}/merged_report.md and merged_report.json]")


if __name__ == "__main__":
    main()
