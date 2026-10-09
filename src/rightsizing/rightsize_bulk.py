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


def rightsizing(summary_path, thresholds_path=None, out_dir=None, verbose=True):
    """Run bulk rightsizing against an extraction_summary.json.

    Importable, scriptable core of the bulk workflow. Opens the summary,
    loads thresholds, evaluates every cluster referenced by it, writes the
    per-cluster reports + an org-level summary.json + summary.md, and
    returns an exit code (0 = all ok, 2 = at least one cluster errored).

    Raises:
        OSError / json.JSONDecodeError on bad summary input,
        KeyError / ValueError on bad thresholds YAML.
    The CLI wrapper (`console_main`) translates these into sys.exit messages;
    direct callers can catch them.

    Args:
        summary_path:   path to extraction_summary.json
        thresholds_path: path to a config.yaml (None = bundled default)
        out_dir:        directory for rightsizing_summary.{json,md}
                        (None = same directory as summary_path)
        verbose:        print per-cluster progress + final paths to stdout
    """
    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)

    thresholds = load_thresholds(path=thresholds_path)

    base_out_dir = out_dir or os.path.dirname(os.path.abspath(summary_path))
    os.makedirs(base_out_dir, exist_ok=True)

    if verbose:
        print(f"Evaluating from {summary_path}")
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
            if verbose:
                print(f"[skip] {pname} / {cname}: extraction not ok")
            continue

        extraction_path = item.get("out")
        if not extraction_path or not os.path.exists(extraction_path):
            entry.update(status="error", error=f"extraction file not found: {extraction_path}")
            entries.append(entry)
            total_errors += 1
            if verbose:
                print(f"[err]  {pname} / {cname}: extraction file missing", file=sys.stderr)
            continue

        try:
            with open(extraction_path, encoding="utf-8") as f:
                extraction = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            entry.update(status="error", error=f"could not read {extraction_path}: {e}")
            entries.append(entry)
            total_errors += 1
            if verbose:
                print(f"[err]  {pname} / {cname}: {e}", file=sys.stderr)
            continue

        # main code
        window = _window_from_extraction(extraction=extraction)
        results = evaluate_mod.evaluate(extraction=extraction, thresholds=thresholds, window=window)

        cluster_out_dir = os.path.dirname(extraction_path)
        extras = {
            "cluster": extraction.get("cluster"), "projectId": item.get("project_id"),
            "projectName": pname, "extractionPath": extraction_path,
        }
        md_path, json_path = write_report(
            results=results, window=window, out_dir=cluster_out_dir,
            thresholds_source=thresholds.source_path, extras=extras)

        verdicts = sorted({r.get("verdict") for r in results})
        # One reasoning string per evaluated unit (shard/config RS, Search
        # deployment, mongos set). Takes the first reason from each result;
        # the full list is in the per-cluster rightsizing.json.
        reasoning = [
            {
                "cluster": r.get("cluster_name") or r.get("cluster") or "-",
                "verdict": r.get("verdict"),
                "reason": (r.get("reasons") or ["-"])[0],
            }
            for r in results
        ]
        entry.update(status="ok", verdicts=verdicts, reasoning=reasoning,
                     out_md=md_path, out_json=json_path,
                     extraction=extraction_path)
        entries.append(entry)
        if verbose:
            print(f"[ok]   {pname} / {cname}: {', '.join(verdicts)} -> {md_path}")

    summary_out = {
        "generated_at": _utc_now(),
        "org": summary.get("org"),
        "source_summary": os.path.abspath(summary_path),
        "thresholds_source": thresholds.source_path,
        "window": summary.get("window"),
        "count": len(entries),
        "errors": total_errors,
        "results": entries,
    }
    summary_out_path = os.path.join(base_out_dir, "rightsizing_summary.json")
    with open(summary_out_path, "w", encoding="utf-8") as f:
        json.dump(summary_out, f, indent=2, default=str)

    summary_md_path = write_summary(summary=summary_out, out_dir=base_out_dir)

    if verbose:
        print(f"\nSummary: {len(entries)} cluster(s), {total_errors} error(s)")
        print(f"Summary written to: {summary_out_path}")
        print(f"Summary table:     {summary_md_path}")
    return 2 if total_errors else 0


def console_main(argv=None):
    """CLI wrapper: parses argv and calls `rightsizing`."""
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--summary", required=True,
                    help="Path to extraction_summary.json (from src/extraction/extract_bulk.py)")
    ap.add_argument("--thresholds", default=None,
                    help=f"Path to config.yaml (default: {DEFAULT_YAML_PATH})")
    ap.add_argument("--out-dir", default=None,
                    help="Directory for rightsizing_summary.json (default: same dir as --summary)")
    args = ap.parse_args(argv)

    try:
        return rightsizing(
            summary_path=args.summary,
            thresholds_path=args.thresholds,
            out_dir=args.out_dir,
        )
    except OSError as e:
        sys.exit(f"Could not read summary: {e}")
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in summary: {e}")
    except (KeyError, ValueError) as e:
        sys.exit(f"Could not load thresholds: {e}")


if __name__ == "__main__":
    sys.exit(console_main())
