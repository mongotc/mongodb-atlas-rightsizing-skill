#!/usr/bin/env python3
"""
Bulk visualization driven by an extraction summary.

Mirrors src/rightsizing/rightsize_bulk.py: takes the extraction_summary.json
produced by extract_bulk.py, iterates every cluster that extracted
successfully, and writes BOTH visualization HTMLs (overlay + per-node) next
to each extraction.json via the top-level orchestrator in `visualize.py`.
Browser auto-open is forced off (bulk runs would spawn 160+ tabs otherwise).

Example:

  python src/visualize/visualize_bulk.py \\
    --summary output/<org>/extraction_summary.json
"""

import argparse
import json
import os
import sys

from visualize import visualize


def visualize_bulk(summary_path, verbose=True):
    """Walk extraction_summary.json and render a visualization per cluster.

    Returns an exit code (0 = all ok, 2 = at least one cluster errored)."""
    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)

    if verbose:
        print(f"Visualizing from {summary_path}")

    total_ok = 0
    total_errors = 0
    total_skipped = 0
    for item in summary.get("results", []):
        pname = item.get("project") or item.get("project_id") or "unknown"
        cname = item.get("cluster") or "unknown"

        if item.get("status") != "ok":
            total_skipped += 1
            if verbose:
                print(f"[skip] {pname} / {cname}: extraction not ok")
            continue

        extraction_path = item.get("out")
        if not extraction_path or not os.path.exists(extraction_path):
            total_errors += 1
            if verbose:
                print(f"[err]  {pname} / {cname}: extraction file missing: "
                      f"{extraction_path}", file=sys.stderr)
            continue

        try:
            old_path, new_path = visualize(extraction_path=extraction_path,
                                           out=None, open_browser=False)
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            total_errors += 1
            if verbose:
                print(f"[err]  {pname} / {cname}: {e}", file=sys.stderr)
            continue

        total_ok += 1
        if verbose:
            print(f"[ok]   {pname} / {cname}: {old_path} + {new_path}")

    if verbose:
        print(f"\nVisualized {total_ok} cluster(s), "
              f"{total_errors} error(s), {total_skipped} skipped")
    return 2 if total_errors else 0


def console_main(argv=None):
    """CLI wrapper: parses argv and calls `visualize_bulk`."""
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--summary", required=True,
                    help="Path to extraction_summary.json (from src/extraction/extract_bulk.py)")
    args = ap.parse_args(argv)

    try:
        return visualize_bulk(summary_path=args.summary)
    except OSError as e:
        sys.exit(f"Could not read summary: {e}")
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in summary: {e}")


if __name__ == "__main__":
    sys.exit(console_main())
