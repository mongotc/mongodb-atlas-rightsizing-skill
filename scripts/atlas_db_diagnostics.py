#!/usr/bin/env python3
"""
Multi-cluster database diagnostics driven by the Atlas Admin API.

Discovers each cluster's connection string via the Atlas Admin API, injects a
shared monitoring user (RIGHT_SIZING_USER / RIGHT_SIZING_PASSWORD), then reuses
the collection functions in db_diagnostics.py to gather in-database signals
per cluster. Writes one JSON file per cluster plus a summary.

Solves the per-cluster MONGODB_URI limitation: one command covers every cluster
in a project without hand-managing URIs.

Auth (env only — never as CLI flags):
  Atlas API   : ATLAS_CLIENT_ID / ATLAS_CLIENT_SECRET   (or ATLAS_PUBLIC_KEY / ATLAS_PRIVATE_KEY)
  MongoDB user: RIGHT_SIZING_USER / RIGHT_SIZING_PASSWORD

The MongoDB user must exist in every audited cluster with the roles verified by
scripts/permissions_check.js (clusterMonitor + a custom role granting
dbStats / collStats / listCollections). Read-only; never modifies a cluster.

Usage:
  python atlas_db_diagnostics.py --group-id <id> --out-dir ./report
  python atlas_db_diagnostics.py --group-id <id> --cluster cluster0 --out-dir ./report
  python atlas_db_diagnostics.py --group-id <id> --databases mydb other_db --sample-interval 30

Dependencies: `requests` (for the Atlas API) and `pymongo` (for the DB calls).
"""

import argparse
import json
import os
import re
import sys
import time
from urllib.parse import quote

from rightsizing import AtlasClient, AtlasAPIError, SHARED_TIERS
from db_diagnostics import (
    utc_now, summarize_server_status, describe_source, get_data_footprint,
)


def build_uri(standard_srv, user, password):
    """Insert credentials into an Atlas connection string.

    Atlas returns 'mongodb+srv://cluster0.abcde.mongodb.net' (no userinfo).
    Passwords are percent-encoded with safe='' so '@', ':', '/', '+', spaces
    etc. survive round-tripping through pymongo's URI parser."""
    if "://" not in standard_srv:
        raise ValueError(f"Unexpected connection string shape: {standard_srv[:60]}...")
    scheme, rest = standard_srv.split("://", 1)
    if scheme not in ("mongodb", "mongodb+srv"):
        raise ValueError(f"Unsupported scheme in Atlas connection string: {scheme}")
    return f"{scheme}://{quote(user, safe='')}:{quote(password, safe='')}@{rest}/admin"


def is_shared_tier(cluster_cfg):
    """True if any region config runs on a shared/serverless tier: those clusters
    don't expose serverStatus / dbStats the way dedicated tiers do."""
    for spec in cluster_cfg.get("replicationSpecs", []):
        for rc in spec.get("regionConfigs", []):
            if (rc.get("electableSpecs") or {}).get("instanceSize") in SHARED_TIERS:
                return True
    return False


def diagnose_cluster(cluster_cfg, user, password, databases, sample_interval):
    """Connect to one cluster and collect diagnostics; returns the same dict shape
    as db_diagnostics.py's standalone output."""
    from pymongo import MongoClient  # lazy so --help works without pymongo installed

    conn_strings = cluster_cfg.get("connectionStrings") or {}
    srv = conn_strings.get("standardSrv") or conn_strings.get("standard")
    if not srv:
        raise ValueError("cluster has no standardSrv/standard connection string in the Atlas response")

    uri = build_uri(srv, user, password)
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    try:
        client.admin.command("ping")  # fail fast on bad creds/network

        dbs = databases or [
            d for d in client.list_database_names() if d not in ("admin", "local", "config")
        ]

        before = client.admin.command("serverStatus")
        t0 = time.time()
        time.sleep(sample_interval)
        after = client.admin.command("serverStatus")
        elapsed = time.time() - t0
        hello = client.admin.command("hello")

        footprint, errors = get_data_footprint(client, dbs)
        return {
            "sampled_at": utc_now(),
            "sample_interval_s": round(elapsed, 1),
            "source": describe_source(client, hello, after),
            "server_status_summary": summarize_server_status(before, after, elapsed),
            "data_footprint": footprint,
            "errors": errors,
        }
    finally:
        client.close()


def slugify(name):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group-id", required=True, help="Atlas project (group) ID")
    ap.add_argument("--cluster", help="Single cluster name; omit to run against every cluster in the project")
    ap.add_argument("--databases", nargs="*",
                    help="Databases to inspect on each cluster; omit to auto-discover per cluster")
    ap.add_argument("--sample-interval", type=int, default=60,
                    help="Seconds between serverStatus samples (default 60)")
    ap.add_argument("--out-dir", default="./rightsizing-report",
                    help="Output directory; writes db_diagnostics_<cluster>.json per cluster plus a summary")
    args = ap.parse_args(argv)

    user = os.environ.get("RIGHT_SIZING_USER")
    password = os.environ.get("RIGHT_SIZING_PASSWORD")
    if not user or not password:
        sys.exit("Set RIGHT_SIZING_USER and RIGHT_SIZING_PASSWORD in the environment.")

    try:
        atlas = AtlasClient()
    except AtlasAPIError as e:
        sys.exit(str(e))

    try:
        if args.cluster:
            cluster_names = [args.cluster]
        else:
            cluster_names = [c["name"] for c in atlas.get_all(f"/groups/{args.group_id}/clusters")]
    except AtlasAPIError as e:
        sys.exit(f"Atlas API error listing clusters: {e}")

    if not cluster_names:
        sys.exit(f"No clusters found in project {args.group_id}.")

    os.makedirs(args.out_dir, exist_ok=True)
    summary, failed = [], 0

    for name in cluster_names:
        entry = {"cluster": name, "group_id": args.group_id}
        try:
            cfg = atlas.get(f"/groups/{args.group_id}/clusters/{name}")
            if is_shared_tier(cfg):
                entry["status"] = "skipped"
                entry["reason"] = "shared/serverless tier — no serverStatus internals"
                print(f"[skip]  {name}: shared/serverless tier")
                summary.append(entry)
                continue

            print(f"[run]   {name}: sampling for {args.sample_interval}s...")
            diagnostics = diagnose_cluster(cfg, user, password, args.databases, args.sample_interval)
            diagnostics["cluster"] = name
            diagnostics["group_id"] = args.group_id

            out_path = os.path.join(args.out_dir, f"db_diagnostics_{slugify(name)}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(diagnostics, f, indent=2, default=str)

            entry["status"] = "ok"
            entry["output"] = out_path
            if diagnostics["errors"]:
                entry["dbstats_errors"] = len(diagnostics["errors"])
            print(f"[ok]    {name}: written to {out_path}")
        except Exception as e:
            failed += 1
            entry["status"] = "error"
            entry["error"] = str(e)
            print(f"[err]   {name}: {e}", file=sys.stderr)
        summary.append(entry)

    summary_path = os.path.join(args.out_dir, "db_diagnostics_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"generated_at": utc_now(), "group_id": args.group_id, "clusters": summary}, f, indent=2)
    print(f"\nSummary written to {summary_path} ({len(summary)} cluster(s), {failed} error(s))")

    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
