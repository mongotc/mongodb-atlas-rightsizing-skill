"""Human-readable and JSON reports for a rightsizing evaluation.

The markdown table format is a direct port of
scripts/rightsizing.py:772-802 (`build_report`). The JSON writer emits the
same schema the legacy script uses, so downstream tools (merge_verdict.py,
diff scripts) keep working against rightsizing.json.
"""

import json
import os
import sys
from datetime import datetime, timezone

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from constants.verdicts import VERDICT_LABELS  # noqa: E402


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_report_md(results, window, thresholds_source=None):
    """Return a markdown report of every result in `results`.

    `window` is the extraction window dict ({"days", "label", "granularity", ...}).
    `thresholds_source` is the absolute path to the thresholds.yaml used
    (printed in the footer so users can trace which knobs produced the verdict)."""
    lines = ["# Atlas Rightsizing Report", "",
             f"Lookback: {window['label']} (granularity {window['granularity']})  |  "
             f"Generated: {_utc_now()}", ""]
    for r in results:
        header = f"## {r['cluster']}"
        if r.get("current_tier"):
            header += f"  -  {r['current_tier']}"
        lines.append(header)
        lines.append(f"**Verdict: {VERDICT_LABELS.get(r['verdict'], r['verdict'])}**  "
                     f"(confidence: {r['confidence']})")
        lines.append("")
        lines += [f"- {reason}" for reason in r.get("reasons", [])]
        if r.get("borderline"):
            lines += ["", "**Close to a trigger:**"] + [f"- {b}" for b in r["borderline"]]
        if r.get("notes"):
            lines += ["", "**Notes:**"] + [f"- {n}" for n in r["notes"]]
        if r.get("coverage") is not None:
            lines += ["", f"Data coverage: {r['coverage']:.0%} of expected samples "
                          f"(lowest node/core metric)."]
        lines.append("")
        for node in r.get("nodes", []):
            rows = [(k, s) for k, s in (node.get("metric_summary") or {}).items() if s]
            if not rows:
                continue
            heading = f"### {node['node']}"
            if node.get("role"):
                heading += f" ({node['role']})"
            lines.append(heading)
            lines.append("")
            lines.append("| Metric | p5 | p50 | p95 | max | samples |")
            lines.append("|---|---|---|---|---|---|")
            lines += [f"| {k} | {s['p5']} | {s['p50']} | {s['p95']} | {s['max']} | {s['n']} |"
                      for k, s in rows]
            lines.append("")
    lines.append("---")
    lines.append("This is a read-only recommendation. No cluster was modified. "
                 "Node roles are as of report time.")
    if thresholds_source:
        lines.append(f"Thresholds: {thresholds_source}")
    lines.append("Verify against your own risk tolerance before acting "
                 "(references/mongod-thresholds.md).")
    return "\n".join(lines)


def build_report_json(results, window, thresholds_source=None, extras=None):
    """Return the report as a plain dict (ready for json.dump)."""
    payload = {
        "generatedAt": _utc_now(),
        "windowDays": window.get("days"),
        "windowLabel": window.get("label"),
        "granularity": window.get("granularity"),
        "thresholdsSource": thresholds_source,
        "results": results,
    }
    if extras:
        payload.update(extras)
    return payload


# Ordering used for the summary table: verdicts that need attention first,
# healthy ones next, informational rows last.
_VERDICT_PRIORITY = {
    "scale_up":             0,
    "disk_iops_only":       1,
    "insufficient_data":    2,
    "scale_down_candidate": 3,
    "no_change":            4,
    "not_supported":        5,
    "not_applicable":       6,
    "error":                7,
}


def _summarize_verdicts(verdicts):
    """Return a comma-joined display string of verdict labels, ordered by
    _VERDICT_PRIORITY so 'attention needed' verdicts read first."""
    ordered = sorted(verdicts or [], key=lambda v: _VERDICT_PRIORITY.get(v, 99))
    return ", ".join(VERDICT_LABELS.get(v, v) for v in ordered) or "-"


def build_summary_md(summary):
    """Org-level markdown table: one row per cluster, linking to the
    per-cluster rightsizing.md report.

    `summary` is the dict written to rightsizing_summary.json — it already
    carries per-cluster verdicts and absolute paths, so no further inspection
    of the per-cluster reports is needed."""
    org = summary.get("org") or {}
    window = summary.get("window") or {}

    lines = ["# Atlas Rightsizing Summary", ""]
    org_line = org.get("name") or ""
    if org.get("id"):
        org_line = f"{org_line} (`{org['id']}`)" if org_line else f"`{org['id']}`"
    if org_line:
        lines.append(f"Organization: {org_line}")
    lines.append(f"Window: {window.get('label') or 'unknown'}")
    lines.append(f"Generated: {summary.get('generated_at') or _utc_now()}")
    if summary.get("thresholds_source"):
        lines.append(f"Thresholds: `{summary['thresholds_source']}`")
    lines.append("")

    entries = summary.get("results") or []

    # Verdict overview counts (one cluster can carry several verdicts).
    tally = {}
    for e in entries:
        if e.get("status") == "ok":
            for v in e.get("verdicts") or []:
                tally[v] = tally.get(v, 0) + 1
        else:
            key = f"{e.get('status') or 'unknown'} (skipped/error)"
            tally[key] = tally.get(key, 0) + 1
    lines.append(f"**{len(entries)} cluster(s) evaluated** ({summary.get('errors', 0)} error(s))")
    lines.append("")
    if tally:
        lines.append("Verdict counts across all evaluated units (shards + Search deployments):")
        for k in sorted(tally, key=lambda x: _VERDICT_PRIORITY.get(x, 99)):
            label = VERDICT_LABELS.get(k, k)
            lines.append(f"- **{label}**: {tally[k]}")
        lines.append("")

    # Per-cluster table.
    base_dir = os.path.dirname(os.path.abspath(summary.get("source_summary") or "")) \
        if summary.get("source_summary") else None
    lines.append("| Project | Cluster | Status | Verdicts | Report |")
    lines.append("|---|---|---|---|---|")
    for e in entries:
        project = e.get("project") or e.get("project_id") or "-"
        cluster = e.get("cluster") or "-"
        status = e.get("status") or "-"
        verdicts = _summarize_verdicts(e.get("verdicts"))
        report_link = "-"
        if e.get("out_md"):
            path = e["out_md"]
            if base_dir:
                try:
                    path = os.path.relpath(path, base_dir)
                except ValueError:
                    pass  # Windows cross-drive; keep absolute
            report_link = f"[rightsizing.md]({path})"
        row_note = ""
        if status != "ok" and e.get("error"):
            row_note = f" ({e['error']})"
        elif status != "ok" and e.get("reason"):
            row_note = f" ({e['reason']})"
        lines.append(f"| {project} | {cluster} | {status}{row_note} | {verdicts} | {report_link} |")

    lines.append("")
    lines.append("Each row links to the per-cluster report with the metric tables and reasons.")
    return "\n".join(lines)


def write_summary(summary, out_dir, name="rightsizing_summary.md"):
    """Write the org-level markdown summary next to rightsizing_summary.json."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_summary_md(summary))
    return path


def write_report(results, window, out_dir, thresholds_source=None, extras=None,
                 md_name="rightsizing.md", json_name="rightsizing.json"):
    """Write both files (`md_name` and `json_name`) into `out_dir`. Returns
    the paths written."""
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, md_name)
    json_path = os.path.join(out_dir, json_name)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(build_report_md(results, window, thresholds_source))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(build_report_json(results, window, thresholds_source, extras),
                  f, indent=2, default=str)
    return md_path, json_path
