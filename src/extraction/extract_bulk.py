#!/usr/bin/env python3
"""
Bulk cluster extraction driven by an inventory file.

Reads inventory.json (produced by src/discovery/gather_info.py). For every
cluster it lists, this script:
  - Fetches the cluster config and (once per project) the process list
  - Calls extract.extract() to route to the right per-type extractor
    (free_tier / gen1 / shard)
  - Writes the extractor result to one JSON file per cluster
  - Records a per-cluster status entry
  - Continues on per-cluster errors — one bad cluster does not stop the batch

Uses the same window semantics as extract.py — lookback is configured in
src/config.yaml under `extraction:` — and the same project-root-anchored
OUTPUT_DIR convention.

Default output layout:
  <project root>/<OUTPUT_DIR>/<org>/<project>/<cluster>/extraction.json
Plus a batch summary at:
  <project root>/<OUTPUT_DIR>/<org>/extraction_summary.json

Auth (env only): same as extract.py / gather_info.py
  ATLAS_CLIENT_ID / ATLAS_CLIENT_SECRET (preferred, OAuth2), OR
  ATLAS_PUBLIC_KEY / ATLAS_PRIVATE_KEY (legacy API key, HTTP Digest)

Example:
  python src/extraction/extract_bulk.py \\
    --inventory output/<org>/inventory.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

from common import AtlasAPIError, AtlasClient
from extract import extract as extract_cluster, _build_window
from extract_search_data import extract as extract_search


# Project root = 3 levels up from src/extraction/extract_bulk.py.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_OUTPUT_DIR_NAME = os.environ.get("OUTPUT_DIR", "output")


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slugify(name):
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", (name or "").strip()).strip("_")
    return slug or "unknown"


def _window_metadata(window):
    """Serializable snapshot of the window used to fetch this extraction.

    Includes the host sub-window (days/period/granularity) and the disk
    sub-window (just period/days, since granularity is shared) so downstream
    evaluators know how the two series were sized."""
    disk_sub = window.get("disk") or {}
    return {
        "days": window.get("days"), "label": window.get("label"),
        "period": window["period"], "granularity": window["granularity"],
        "disk": {"period": disk_sub.get("period", window["period"]),
                 "days": disk_sub.get("days", window.get("days"))},
    }


def _load_inventory(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _default_out_dir(inventory):
    org_name = (inventory.get("org") or {}).get("name") or ""
    return os.path.join(_PROJECT_ROOT, _OUTPUT_DIR_NAME, _slugify(org_name))


def _iter_clusters(inventory):
    """Yield (project, cluster) dicts for every named cluster in the inventory."""
    for project in inventory.get("projects", []):
        if not project.get("id"):
            continue
        for cluster in project.get("clusters", []):
            if cluster.get("name"):
                yield project, cluster


def _extract_one(client, project, cluster, processes, window, base_out_dir):
    """Extract a single cluster; return a status/summary dict."""
    pid = project["id"]
    pname = project.get("name") or pid
    cname = cluster["name"]
    entry = {"project": pname, "project_id": pid, "cluster": cname}

    try:
        cfg = client.get(f"/groups/{pid}/clusters/{cname}")
    except AtlasAPIError as e:
        entry.update(status="error", error=f"cluster config fetch: {e}")
        return entry

    try:
        result = extract_cluster(client=client, group_id=pid, cluster_cfg=cfg,
                                 window=window, processes=processes)
    except AtlasAPIError as e:
        entry.update(status="error", error=f"extraction: {e}")
        return entry

    # Atlas Search is orthogonal to the mongod deployment shape (a replica
    # set, sharded cluster, or free-tier cluster can each independently have
    # Search Nodes attached). Attach the search extractor's result as a
    # sibling field; failures here don't fail the whole cluster.
    try:
        result["search"] = extract_search(client=client, group_id=pid, cluster_cfg=cfg,
                                          window=window, processes=processes)
    except AtlasAPIError as e:
        result["search"] = {"type": "search", "cluster": cname, "error": str(e)}

    # Stamp identity onto the result so a stray file is self-describing.
    result.update({"cluster": cname, "project_id": pid, "project_name": pname,
                   "window": _window_metadata(window=window)})
    out_path = os.path.join(base_out_dir, _slugify(name=pname), cname, "extraction.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    entry.update(status="ok", type=result.get("type"), out=out_path)
    return entry


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--inventory", required=True,
                    help="Path to inventory.json (from src/discovery/gather_info.py)")
    ap.add_argument("--out-dir", default=None,
                    help="Base output directory. Default: "
                         "<project root>/<OUTPUT_DIR>/<org_slug>/")
    args = ap.parse_args(argv)

    try:
        inventory = _load_inventory(path=args.inventory)
    except OSError as e:
        sys.exit(f"Could not read inventory: {e}")
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in inventory: {e}")

    try:
        window = _build_window()
    except ValueError as e:
        ap.error(str(e))

    try:
        client = AtlasClient()
    except AtlasAPIError as e:
        sys.exit(str(e))

    base_out_dir = args.out_dir or _default_out_dir(inventory=inventory)
    os.makedirs(base_out_dir, exist_ok=True)

    print(f"Extracting from {args.inventory}")
    print(f"Window: {window['label']} ({window['granularity']})")
    print(f"Output base: {base_out_dir}")

    # Cache processes per project — every cluster in a project shares the
    # same /processes response, so one API call per project instead of one
    # per cluster.
    process_cache = {}
    results = []
    for project, cluster in _iter_clusters(inventory=inventory):
        pid = project["id"]
        pname = project.get("name") or pid
        cname = cluster["name"]

        if pid not in process_cache:
            try:
                process_cache[pid] = client.get_all(f"/groups/{pid}/processes")
            except AtlasAPIError as e:
                process_cache[pid] = None
                print(f"[err]  {pname}: process list: {e}", file=sys.stderr)

        processes = process_cache[pid]
        if processes is None:
            results.append({
                "project": pname, "project_id": pid, "cluster": cname,
                "status": "error", "error": "process list unavailable for this project",
            })
            continue

        print(f"[run]  {pname} / {cname}")
        entry = _extract_one(client=client, project=project, cluster=cluster,
                             processes=processes, window=window,
                             base_out_dir=base_out_dir)
        results.append(entry)
        if entry["status"] == "ok":
            print(f"[ok]   {pname} / {cname}: {entry.get('type')} -> {entry['out']}")
        else:
            print(f"[err]  {pname} / {cname}: {entry.get('error')}", file=sys.stderr)

    summary = {
        "generated_at": _utc_now(),
        "org": inventory.get("org"),
        "inventory": os.path.abspath(args.inventory),
        "window": {"days": window.get("days"), "label": window["label"],
                   "period": window["period"], "granularity": window["granularity"]},
        "count": len(results),
        "errors": sum(1 for r in results if r.get("status") == "error"),
        "results": results,
    }
    summary_path = os.path.join(base_out_dir, "extraction_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\nSummary: {summary['count']} cluster(s), {summary['errors']} error(s)")
    print(f"Summary written to: {summary_path}")

    return 2 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
