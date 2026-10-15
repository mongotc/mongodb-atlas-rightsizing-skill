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

    Prefers the `window` field stamped onto the extraction (both host and
    disk sub-windows); falls back to reconstructing host sample counts from
    the first host-metric series. Disk sample counts are tracked separately
    because disks are fetched over a wider window than host metrics — see
    src/config.yaml:extraction.disk_days."""
    def iter_host_series():
        for node in extraction.get("nodes") or []:
            for series in ((node.get("data") or {}).get("host") or {}).values():
                yield series or []
        for shard in (extraction.get("shards") or {}).values():
            for node in shard:
                for series in ((node.get("data") or {}).get("host") or {}).values():
                    yield series or []

    def iter_disk_series():
        def by_node(nodes):
            for n in nodes:
                for metrics in ((n.get("data") or {}).get("disks") or {}).values():
                    for series in metrics.values():
                        yield series or []
        yield from by_node(extraction.get("nodes") or [])
        for shard in (extraction.get("shards") or {}).values():
            yield from by_node(shard)

    stamped = extraction.get("window") or {}
    host_n = max((len(s) for s in iter_host_series()), default=0)
    disk_n = max((len(s) for s in iter_disk_series()), default=0)
    if host_n <= 0:
        host_n = default_days * 24

    days = max(host_n / 24.0, 1.0)
    disk_days_stamped = (stamped.get("disk") or {}).get("days")
    if disk_days_stamped:
        expected_disk = int(disk_days_stamped) * 24
    else:
        expected_disk = disk_n or host_n

    return {
        "days": days, "label": f"~{host_n} hourly samples",
        "period": f"P{int(days)}D", "granularity": "PT1H",
        "expected_samples": host_n or 1,
        "expected_compute_samples": host_n or 1,
        "expected_disk_samples": expected_disk or 1,
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
