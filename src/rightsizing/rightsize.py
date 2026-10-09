#!/usr/bin/env python3
"""
Single-cluster rightsizing CLI.

Consumes one extraction.json (produced by src/extraction/) and writes
rightsizing.json + rightsizing.md next to it. Pure offline evaluation — no
Atlas API calls.

Example:

  python src/rightsizing/rightsize.py \\
    --extraction output/<org>/<project>/Cluster0/extraction.json

  python src/rightsizing/rightsize.py \\
    --extraction path/to/extraction.json \\
    --thresholds path/to/custom-config.yaml \\
    --out /tmp/out
"""

import argparse
import json
import os
import sys

# Bare-import style, matching the extraction package.
import evaluate as evaluate_mod
from report import build_report_json, build_report_md, write_report
from thresholds import DEFAULT_YAML_PATH, load_thresholds


def _window_from_extraction(extraction, default_days=7):
    """Rebuild the window dict used by node_eval.evaluate_node.

    Extraction doesn't currently persist the window it was collected under.
    Reconstruct expected_samples from the first metric series we can find,
    falling back to `default_days` * 24 hourly samples if the extraction is
    empty. This isn't perfect but it lets the sustained-days check remain
    meaningful without adding a required CLI flag."""
    n = 0
    for node in extraction.get("nodes") or []:
        for series in ((node.get("data") or {}).get("host") or {}).values():
            n = max(n, len(series or []))
    for shard in (extraction.get("shards") or {}).values():
        for node in shard:
            for series in ((node.get("data") or {}).get("host") or {}).values():
                n = max(n, len(series or []))
    if n <= 0:
        n = default_days * 24
    days = max(n / 24.0, 1.0)
    return {
        "days": days, "label": f"~{n} hourly samples", "period": f"P{int(days)}D",
        "granularity": "PT1H", "expected_samples": n or 1,
    }


def _default_out_dir(extraction_path):
    return os.path.dirname(os.path.abspath(extraction_path)) or "."


def console_main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--extraction", required=True,
                    help="Path to extraction.json (from src/extraction/)")
    ap.add_argument("--thresholds", default=None,
                    help=f"Path to config.yaml (default: {DEFAULT_YAML_PATH})")
    ap.add_argument("--out", default=None,
                    help="Output directory (default: same directory as --extraction). "
                         "'-' writes rightsizing.json to stdout and skips the markdown.")
    args = ap.parse_args(argv)

    try:
        with open(args.extraction, encoding="utf-8") as f:
            extraction = json.load(f)
    except OSError as e:
        sys.exit(f"Could not read extraction: {e}")
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in extraction: {e}")

    try:
        thresholds = load_thresholds(path=args.thresholds)
    except (OSError, KeyError, ValueError) as e:
        sys.exit(f"Could not load thresholds: {e}")

    window = _window_from_extraction(extraction=extraction)
    results = evaluate_mod.evaluate(extraction=extraction, thresholds=thresholds, window=window)

    extras = {
        "cluster": extraction.get("cluster"),
        "projectId": extraction.get("project_id"),
        "projectName": extraction.get("project_name"),
        "extractionPath": os.path.abspath(args.extraction),
    }

    if args.out == "-":
        print(json.dumps(build_report_json(
            results=results, window=window,
            thresholds_source=thresholds.source_path, extras=extras),
            indent=2, default=str))
    else:
        out_dir = args.out or _default_out_dir(extraction_path=args.extraction)
        md_path, json_path = write_report(
            results=results, window=window, out_dir=out_dir,
            thresholds_source=thresholds.source_path, extras=extras)
        print(build_report_md(results=results, window=window,
                              thresholds_source=thresholds.source_path))
        print(f"\n[written to {md_path} and {json_path}]", file=sys.stderr)

    return 2 if any(r.get("verdict") == "error" for r in results) else 0


if __name__ == "__main__":
    sys.exit(console_main())
