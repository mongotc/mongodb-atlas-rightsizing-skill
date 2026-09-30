#!/usr/bin/env python3
"""
Bulk rightsizing driven by an extraction summary.

Mirrors src/extraction/extract_bulk.py: takes the extraction_summary.json
produced by that script, iterates every cluster that extracted successfully,
evaluates each one, writes rightsizing.json + rightsizing.md next to the
input extraction, and writes a rightsizing_summary.json at the org root.

Example:

  python src/rightsizing/rightsize_bulk.py \\
    --summary output/<org>/extraction_summary.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import evaluate as evaluate_mod
from report import write_report, write_summary
from rightsize import _window_from_extraction
from thresholds import DEFAULT_YAML_PATH, load_thresholds


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--summary", required=True,
                    help="Path to extraction_summary.json (from src/extraction/extract_bulk.py)")
    ap.add_argument("--thresholds", default=None,
                    help=f"Path to thresholds.yaml (default: {DEFAULT_YAML_PATH})")
    ap.add_argument("--out-dir", default=None,
                    help="Directory for rightsizing_summary.json (default: same dir as --summary)")
    args = ap.parse_args(argv)

    try:
        with open(args.summary, encoding="utf-8") as f:
            summary = json.load(f)
    except OSError as e:
        sys.exit(f"Could not read summary: {e}")
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in summary: {e}")

    try:
        thresholds = load_thresholds(args.thresholds)
    except (OSError, KeyError, ValueError) as e:
        sys.exit(f"Could not load thresholds: {e}")

    base_out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.summary))
    os.makedirs(base_out_dir, exist_ok=True)

    print(f"Evaluating from {args.summary}")
    print(f"Thresholds: {thresholds.source_path}")

    entries = []
    total_errors = 0
    for item in summary.get("results", []):
        pname = item.get("project") or item.get("project_id") or "unknown"
        cname = item.get("cluster") or "unknown"
        entry = {"project": pname, "project_id": item.get("project_id"), "cluster": cname}

        if item.get("status") != "ok":
            entry.update(status="skipped",
                         reason=f"extraction status was {item.get('status')!r}")
            entries.append(entry)
            print(f"[skip] {pname} / {cname}: extraction not ok")
            continue

        extraction_path = item.get("out")
        if not extraction_path or not os.path.exists(extraction_path):
            entry.update(status="error", error=f"extraction file not found: {extraction_path}")
            entries.append(entry)
            total_errors += 1
            print(f"[err]  {pname} / {cname}: extraction file missing", file=sys.stderr)
            continue

        try:
            with open(extraction_path, encoding="utf-8") as f:
                extraction = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            entry.update(status="error", error=f"could not read {extraction_path}: {e}")
            entries.append(entry)
            total_errors += 1
            print(f"[err]  {pname} / {cname}: {e}", file=sys.stderr)
            continue

        window = _window_from_extraction(extraction)
        results = evaluate_mod.evaluate(extraction, thresholds, window)
        out_dir = os.path.dirname(extraction_path)
        extras = {
            "cluster": extraction.get("cluster"), "projectId": item.get("project_id"),
            "projectName": pname, "extractionPath": extraction_path,
        }
        md_path, json_path = write_report(
            results, window, out_dir,
            thresholds_source=thresholds.source_path, extras=extras)

        verdicts = sorted({r.get("verdict") for r in results})
        entry.update(status="ok", verdicts=verdicts,
                     out_md=md_path, out_json=json_path,
                     extraction=extraction_path)
        entries.append(entry)
        print(f"[ok]   {pname} / {cname}: {', '.join(verdicts)} -> {md_path}")

    summary_out = {
        "generated_at": _utc_now(),
        "org": summary.get("org"),
        "source_summary": os.path.abspath(args.summary),
        "thresholds_source": thresholds.source_path,
        "window": summary.get("window"),
        "count": len(entries),
        "errors": total_errors,
        "results": entries,
    }
    summary_path = os.path.join(base_out_dir, "rightsizing_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_out, f, indent=2, default=str)

    summary_md_path = write_summary(summary_out, base_out_dir)

    print(f"\nSummary: {len(entries)} cluster(s), {total_errors} error(s)")
    print(f"Summary written to: {summary_path}")
    print(f"Summary table:     {summary_md_path}")
    return 2 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
