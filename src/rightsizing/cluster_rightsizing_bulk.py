#!/usr/bin/env python3
"""
Bulk cluster rightsizing + per-cluster visualization + top-level report.

Walks every cluster in an extraction_summary.json (produced by
src/extraction/extract_bulk.py) and, for each cluster with status=="ok":

  1. Runs ClusterRightsizingManager → writes `rightsizing_report.md` next
     to that cluster's extraction.json.
  2. Renders `visualization_old.html` + `visualization_new.html` next to
     the same extraction.json.
  3. Records the mongod + Search scale-down verdicts.

After the loop, writes a top-level `rightsizing_bulk_report.md` with a
3-column table (cluster, mongod, search). Values are:
  - "down" → fleet can scale down
  - "n/a"  → fleet cannot scale down OR doesn't exist on that cluster

Mirrors src/visualize/visualize_bulk.py's skip-and-continue semantics —
one bad cluster never stops the run. Exit code 2 if any per-cluster error
was recorded, else 0.

Example:

  python src/rightsizing/cluster_rightsizing_bulk.py \\
    --summary output/<org>/extraction_summary.json
"""

import argparse
import json
import os
import sys
from typing import Optional

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)
# visualize/visualize.py uses sibling imports (`from visualize_old import ...`)
# that only resolve when src/visualize/ is also on sys.path.
_VIS_DIR = os.path.join(_SRC_DIR, "visualize")
if _VIS_DIR not in sys.path:
    sys.path.append(_VIS_DIR)

from cluster_rightsizing import run_cluster  # noqa: E402
from report_generator import write_bulk_summary_report, write_report  # noqa: E402
from thresholds import DEFAULT_YAML_PATH, load_thresholds  # noqa: E402
from visualize.visualize import visualize  # noqa: E402


def _label(flag: Optional[bool]) -> str:
    """Mirror of the summary table's cell semantics for stdout logs."""
    return "down" if flag is True else "n/a"


def cluster_rightsizing_bulk(summary_path: str,
                             thresholds_path: Optional[str] = None,
                             out_dir: Optional[str] = None,
                             verbose: bool = True) -> int:
    """Load extraction_summary.json, iterate every cluster where
    status=="ok", and for each: rightsize + visualize + record the
    cluster's two scale-down verdicts. Writes
    `rightsizing_bulk_report.md` to `out_dir` (default: summary's own
    directory). Returns 2 on any per-cluster error, else 0."""

    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)
    thresholds = load_thresholds(path=thresholds_path)
    out_dir = out_dir or (os.path.dirname(os.path.abspath(summary_path)) or ".")

    if verbose:
        print(f"Rightsizing from {summary_path}")

    rows: list[dict] = []
    total_ok = 0
    total_err = 0
    total_skipped = 0

    for item in summary.get("results", []):
        pname = item.get("project") or item.get("project_id") or "unknown"
        cname = item.get("cluster") or "unknown"
        label = f"{pname} / {cname}"

        if item.get("status") != "ok":
            total_skipped += 1
            if verbose:
                print(f"[skip] {label}: extraction not ok")
            continue

        extraction_path = item.get("out")
        if not extraction_path or not os.path.exists(extraction_path):
            total_err += 1
            rows.append({"cluster": cname, "status": "err",
                         "mongod": None, "search": None,
                         "error": f"extraction file missing: {extraction_path}"})
            if verbose:
                print(f"[err]  {label}: extraction file missing: "
                      f"{extraction_path}", file=sys.stderr)
            continue

        try:
            with open(extraction_path, encoding="utf-8") as f:
                extraction = json.load(f)
            result = run_cluster(extraction=extraction, thresholds=thresholds)
            report_path = os.path.join(
                os.path.dirname(extraction_path), "rightsizing_report.md",
            )
            write_report(result=result, path=report_path, cluster_name=cname)
            visualize(extraction_path=extraction_path, out=None, open_browser=False)
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            total_err += 1
            rows.append({"cluster": cname, "status": "err",
                         "mongod": None, "search": None, "error": str(e)})
            if verbose:
                print(f"[err]  {label}: {e}", file=sys.stderr)
            continue

        total_ok += 1
        search_cell: Optional[bool] = (
            result.search_can_scale_down if result.search_nodes else None
        )
        rows.append({
            "cluster": cname,
            "status": "ok",
            "mongod": result.can_scale_down,
            "search": search_cell,
        })
        if verbose:
            print(f"[ok]   {label}: mongod={_label(result.can_scale_down)} "
                  f"search={_label(search_cell)}")

    bulk_report_path = os.path.join(out_dir, "rightsizing_bulk_report.md")
    write_bulk_summary_report(rows=rows, path=bulk_report_path)

    if verbose:
        print(f"\nRightsized {total_ok} cluster(s), "
              f"{total_err} error(s), {total_skipped} skipped")
        print(f"[bulk summary written to {bulk_report_path}]", file=sys.stderr)

    return 2 if total_err else 0


def console_main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--summary", required=True,
                    help="Path to extraction_summary.json "
                         "(from src/extraction/extract_bulk.py).")
    ap.add_argument("--thresholds", default=None,
                    help=f"Path to config.yaml (default: {DEFAULT_YAML_PATH}).")
    ap.add_argument("--out-dir", default=None,
                    help="Directory for the top-level bulk summary "
                         "(default: same directory as --summary).")
    args = ap.parse_args(argv)

    try:
        return cluster_rightsizing_bulk(
            summary_path=args.summary,
            thresholds_path=args.thresholds,
            out_dir=args.out_dir,
        )
    except OSError as e:
        sys.exit(f"Could not read summary: {e}")
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in summary: {e}")


if __name__ == "__main__":
    sys.exit(console_main())
