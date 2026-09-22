#!/usr/bin/env python3
"""
Database-internal diagnostics to complement the Atlas Admin API hardware metrics.

Connects directly to a MongoDB deployment (needs a user with `clusterMonitor`, plus `read` on the
databases inspected for dbStats/collStats) and collects:

  - serverStatus(), sampled twice to turn cumulative counters into rates: connection headroom,
    WiredTiger cache pressure, documents examined vs returned, collection scans, opcounters
  - dbStats() / collStats() per database: data + index size (an upper bound on the working set,
    not the working set itself)
  - which host answered (hello / serverStatus.host), so merge_verdict.py can check the file
    belongs to the cluster it is merged with

This is a different data source from rightsizing.py (Atlas hardware metrics). Pass both JSON files
to merge_verdict.py; see references/db-diagnostics.md for how they are combined.

This script only runs read-only admin commands. It never writes to the database.

Usage:
  MONGODB_URI="mongodb+srv://user:pass@cluster.../admin" \\
  python db_diagnostics.py --databases mydb another_db --sample-interval 60 --out-dir ./report

  Omit --databases to auto-discover all non-system databases. Prefer MONGODB_URI over --uri so the
  password doesn't end up in shell history or the process list.

Only dependency: `pymongo` (pip install pymongo).
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get(doc, *path):
    """Nested lookup that returns None (not 0) when any key is missing."""
    for key in path:
        if not isinstance(doc, dict) or key not in doc:
            return None
        doc = doc[key]
    return doc


def _rate(before, after, path, elapsed_s):
    b, a = _get(before, *path), _get(after, *path)
    if b is None or a is None or elapsed_s <= 0:
        return None
    return round((a - b) / elapsed_s, 2)


def summarize_server_status(before, after, elapsed_s):
    """Turn two serverStatus snapshots into rates and pressure signals. Anything the server didn't
    report comes back as None, never as a misleading 0."""
    notes = []

    op_before, op_after = before.get("opcounters", {}), after.get("opcounters", {})
    op_rates = {k: _rate(before, after, ("opcounters", k), elapsed_s) for k in op_after if k in op_before}

    docs_examined = _rate(before, after, ("metrics", "queryExecutor", "scannedObjects"), elapsed_s)
    keys_examined = _rate(before, after, ("metrics", "queryExecutor", "scanned"), elapsed_s)
    docs_returned = _rate(before, after, ("metrics", "document", "returned"), elapsed_s)
    collection_scans = _rate(before, after, ("metrics", "queryExecutor", "collectionScans", "total"), elapsed_s)
    if docs_examined is None or docs_returned is None:
        ratio = None
    elif docs_returned > 0:
        ratio = round(docs_examined / docs_returned, 1)
    else:
        ratio = "inf" if docs_examined > 0 else None

    cache_bytes = _get(after, "wiredTiger", "cache", "bytes currently in the cache")
    cache_max = _get(after, "wiredTiger", "cache", "maximum bytes configured")
    cache_pct = round(100 * cache_bytes / cache_max, 1) if cache_bytes is not None and cache_max else None
    if "wiredTiger" not in after:
        notes.append(
            "serverStatus has no wiredTiger section (connected through mongos, or not a WiredTiger node), "
            "so the cache fields are unavailable. Connect directly to a shard member for cache stats."
        )

    # There is no single "pages evicted" counter; WiredTiger splits it into clean and dirty pages.
    evicted_parts = [_rate(before, after, ("wiredTiger", "cache", k), elapsed_s)
                     for k in ("modified pages evicted", "unmodified pages evicted")]
    evicted = round(sum(evicted_parts), 2) if all(p is not None for p in evicted_parts) else None

    current, available = _get(after, "connections", "current"), _get(after, "connections", "available")
    conn_pct = (round(100 * current / (current + available), 1)
                if current is not None and available is not None and current + available > 0 else None)

    return {
        "connections_current": current,
        "connections_available": available,
        "connections_pct_used": conn_pct,
        "wt_cache_bytes_used": cache_bytes,
        "wt_cache_bytes_max": cache_max,
        "wt_cache_pct_used": cache_pct,
        "wt_pages_evicted_per_sec": evicted,
        "wt_pages_read_into_cache_per_sec": _rate(
            before, after, ("wiredTiger", "cache", "pages read into cache"), elapsed_s),
        "opcounters_per_sec": op_rates,
        "docs_examined_per_sec": docs_examined,
        "keys_examined_per_sec": keys_examined,
        "docs_returned_per_sec": docs_returned,
        "examined_to_returned_ratio": ratio,
        "collection_scans_per_sec": collection_scans,
        "resident_mem_mb": _get(after, "mem", "resident"),
        "page_faults_total": _get(after, "extra_info", "page_faults"),
        "notes": notes,
    }


def describe_source(client, hello, server_status):
    """Which host(s) this snapshot came from, so the merge can match it to a cluster."""
    try:
        address = "%s:%s" % client.address if client.address else None
    except Exception:  # e.g. several mongos behind one URI
        address = None
    is_mongos = hello.get("msg") == "isdbgrid" or server_status.get("process") == "mongos"
    hosts = set(hello.get("hosts", []) + hello.get("passives", []))
    for h in (hello.get("me"), address, server_status.get("host")):
        if h:
            hosts.add(h)
    return {
        "is_mongos": is_mongos,
        "set_name": hello.get("setName"),
        "server_status_host": server_status.get("host"),
        "hosts": sorted(hosts),
    }


def get_data_footprint(client, database_names):
    """Data + index size per database. Failures are recorded, not dropped."""
    result, errors = {}, []
    for dbname in database_names:
        db = client[dbname]
        try:
            dbstats = db.command("dbStats")
        except Exception as e:
            result[dbname] = {"error": str(e)}
            errors.append(f"dbStats on {dbname}: {e}")
            continue
        colls = []
        for coll_name in db.list_collection_names():
            try:
                cs = db.command("collStats", coll_name)
            except Exception as e:
                errors.append(f"collStats on {dbname}.{coll_name}: {e}")
                continue
            colls.append({
                "name": coll_name,
                "count": cs.get("count"),
                "size_bytes": cs.get("size"),
                "storage_size_bytes": cs.get("storageSize"),
                "total_index_size_bytes": cs.get("totalIndexSize"),
            })
        colls.sort(key=lambda c: (c.get("size_bytes") or 0) + (c.get("total_index_size_bytes") or 0), reverse=True)
        result[dbname] = {
            "data_size_bytes": dbstats.get("dataSize"),
            "index_size_bytes": dbstats.get("indexSize"),
            "storage_size_bytes": dbstats.get("storageSize"),
            "collections": len(colls),
            "top_collections_by_footprint": colls[:10],
        }
    return result, errors


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uri", help="MongoDB connection string; prefer the MONGODB_URI env var so the "
                                  "secret never needs to be a CLI arg")
    ap.add_argument("--databases", nargs="*", help="Databases to inspect; omit to auto-discover")
    ap.add_argument("--sample-interval", type=int, default=60,
                    help="Seconds between the two serverStatus samples used to compute rates (default 60)")
    ap.add_argument("--out-dir", default="./rightsizing-report")
    args = ap.parse_args(argv)

    uri = args.uri or os.environ.get("MONGODB_URI")
    if not uri:
        sys.exit("No connection string found. Set the MONGODB_URI env var (or pass --uri).")
    if args.uri:
        print("WARNING: --uri puts the password in shell history and the process list; "
              "prefer the MONGODB_URI env var.", file=sys.stderr)

    try:
        from pymongo import MongoClient
    except ImportError:
        sys.exit("This script requires pymongo: pip install pymongo")

    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    client.admin.command("ping")  # fail fast on bad creds/network before waiting a full interval

    databases = args.databases or [
        d for d in client.list_database_names() if d not in ("admin", "local", "config")
    ]

    print(f"Sampling serverStatus twice, {args.sample_interval}s apart, to compute rates...")
    before = client.admin.command("serverStatus")
    t0 = time.time()
    time.sleep(args.sample_interval)
    after = client.admin.command("serverStatus")
    elapsed = time.time() - t0
    hello = client.admin.command("hello")

    footprint, errors = get_data_footprint(client, databases)
    diagnostics = {
        "sampled_at": utc_now(),
        "sample_interval_s": round(elapsed, 1),
        "source": describe_source(client, hello, after),
        "server_status_summary": summarize_server_status(before, after, elapsed),
        "data_footprint": footprint,
        "errors": errors,
    }

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, "db_diagnostics.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(diagnostics, f, indent=2, default=str)

    print(json.dumps(diagnostics, indent=2, default=str))
    if errors:
        print(f"WARNING: {len(errors)} dbStats/collStats call(s) failed; see 'errors' in the output.",
              file=sys.stderr)
    print(f"\n[written to {out_path}]")


if __name__ == "__main__":
    main()
