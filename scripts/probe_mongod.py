#!/usr/bin/env python3
"""Manually fetch mongod host / disk metrics from the Atlas Admin API.

Mirrors probe_search.py but hits the mongod endpoints instead:
    host : /groups/{groupId}/processes/{processId}/measurements
    disk : /groups/{groupId}/processes/{processId}/disks/{partition}/measurements

Query uses `m=NAME` (singular) — different from the Search endpoint which
uses `metrics=NAME`. Response container is `measurements[]`.

Usage:
    ~/.pyenv/versions/rightsizing/bin/python scripts/probe_mongod.py \\
        --group-id 674f42f21212e000bcbc3735 \\
        --process-id cluster0-shard-00-00.jds2f.mongodb.net:27017 \\
        [--granularity PT1M] [--period PT1H] [--disk data]
"""

import argparse
import json
import os
import sys
import requests
from requests.auth import HTTPDigestAuth


# Quick .env loader — avoids needing python-dotenv.
def _load_env(path):
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(os.path.join(os.path.dirname(__file__), "..", ".env"))


# Mirrors common.HOST_METRICS plus a few network metrics the extractor doesn't
# currently request. Overshoot is safe: unrecognized names will 404 the whole
# query, so we use the known-good extractor list by default.
HOST_METRICS = [
    "SYSTEM_NORMALIZED_CPU_USER",
    "SYSTEM_NORMALIZED_CPU_KERNEL",
    "SYSTEM_NORMALIZED_CPU_IOWAIT",
    "SYSTEM_MEMORY_USED",
    "SYSTEM_MEMORY_FREE",
    "CONNECTIONS",
    "TICKETS_AVAILABLE_READS",
    "TICKETS_AVAILABLE_WRITE",
    "GLOBAL_LOCK_CURRENT_QUEUE_READERS",
    "GLOBAL_LOCK_CURRENT_QUEUE_WRITERS",
    "OP_EXECUTION_TIME_READS",
    "OP_EXECUTION_TIME_WRITES",
    "EXTRA_INFO_PAGE_FAULTS",
    "CACHE_BYTES_READ_INTO",
    "CACHE_BYTES_WRITTEN_FROM",
    "CACHE_FILL_RATIO",
    "DIRTY_FILL_RATIO",
    "CACHE_PRESSURE_PERCENTAGE",
]

DISK_METRICS = [
    "DISK_PARTITION_IOPS_READ",
    "DISK_PARTITION_IOPS_WRITE",
    "DISK_PARTITION_SPACE_PERCENT_USED",
    "DISK_PARTITION_SPACE_USED",
    "DISK_PARTITION_SPACE_FREE",
    "DISK_PARTITION_LATENCY_READ",
    "DISK_PARTITION_LATENCY_WRITE",
    "DISK_PARTITION_THROUGHPUT_READ",
    "DISK_PARTITION_THROUGHPUT_WRITE",
]


def get_auth():
    """Return (auth, extra_headers). Supports OAuth (ATLAS_CLIENT_ID /
    ATLAS_CLIENT_SECRET) and legacy digest (ATLAS_PUBLIC_KEY / ATLAS_PRIVATE_KEY)."""
    cid = os.environ.get("ATLAS_CLIENT_ID")
    secret = os.environ.get("ATLAS_CLIENT_SECRET")
    if cid and secret:
        resp = requests.post(
            "https://cloud.mongodb.com/api/oauth/token",
            auth=(cid, secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        return None, {"Authorization": f"Bearer {resp.json()['access_token']}"}
    pub = os.environ.get("ATLAS_PUBLIC_KEY")
    priv = os.environ.get("ATLAS_PRIVATE_KEY")
    if pub and priv:
        return HTTPDigestAuth(pub, priv), {}
    sys.exit("Missing ATLAS_CLIENT_ID/ATLAS_CLIENT_SECRET or ATLAS_PUBLIC_KEY/ATLAS_PRIVATE_KEY in env")


def console_main():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter, description=__doc__,
    )
    ap.add_argument("--group-id", required=True)
    ap.add_argument("--process-id", required=True,
                    help="Full host:port, e.g. cluster0-shard-00-00.<domain>:27017")
    ap.add_argument("--granularity", default="PT1M")
    ap.add_argument("--period", default="PT1H")
    ap.add_argument("--disk", default=None,
                    help="Partition name (e.g. 'data'). When set, queries the "
                         "disk measurements endpoint with DISK_METRICS instead "
                         "of the host endpoint with HOST_METRICS.")
    ap.add_argument("--metrics", nargs="*", default=None,
                    help="Override metric list. Defaults to HOST_METRICS "
                         "or DISK_METRICS depending on --disk.")
    ap.add_argument("--full", action="store_true", help="Also dump the full JSON response")
    args = ap.parse_args()

    auth, headers = get_auth()
    headers["Accept"] = "application/vnd.atlas.2025-03-12+json"

    if args.disk:
        url = (f"https://cloud.mongodb.com/api/atlas/v2/groups/{args.group_id}"
               f"/processes/{args.process_id}/disks/{args.disk}/measurements")
        metrics = args.metrics or DISK_METRICS
    else:
        url = (f"https://cloud.mongodb.com/api/atlas/v2/groups/{args.group_id}"
               f"/processes/{args.process_id}/measurements")
        metrics = args.metrics or HOST_METRICS

    params = [("granularity", args.granularity), ("period", args.period)]
    params += [("m", m) for m in metrics]

    print(f"GET {url}")
    print(f"auth: {'digest' if auth else 'oauth'}")
    print(f"params: granularity={args.granularity} period={args.period} "
          f"metrics={len(metrics)}")
    resp = requests.get(url, params=params, headers=headers, auth=auth, timeout=30)
    print(f"status: {resp.status_code}")
    if not resp.ok:
        print(resp.text[:2000])
        sys.exit(1)

    body = resp.json()
    _summarize_response(body)

    if args.full:
        print("\n--- full response ---")
        print(json.dumps(body, indent=2))


def stack_0000():
    group_id = "65de35aacee49637479edebd"
    process_id = "stack-0000-shard-00-00.hm0op.mongodb.net:27016"  # fill in
    granularity = "PT1M"
    period = "PT1H"

    auth, headers = get_auth()
    headers["Accept"] = "application/vnd.atlas.2025-03-12+json"

    # 1. List collection-level metric NAMES (there's no equivalent "list names"
    #    endpoint for host/hardware metrics — those names are only enumerated
    #    in the OpenAPI spec's m= parameter enum).
    url = f"https://cloud.mongodb.com/api/atlas/v2/groups/{group_id}/collStats/metrics"
    print(f"GET {url}")
    print(f"auth: {'digest' if auth else 'oauth'}")
    resp = requests.get(url, headers=headers, auth=auth, timeout=30)
    print(f"status: {resp.status_code}")
    if not resp.ok:
        print(resp.text[:2000])
        sys.exit(1)
    print(json.dumps(resp.json(), indent=2))

    # 2. Enumerate host/hardware metric TYPES for one mongod process. There's
    #    no dedicated "list names" endpoint, but calling /measurements with no
    #    m= returns every metric applicable to the process — we strip the data
    #    points and keep only name + units.
    url = (f"https://cloud.mongodb.com/api/atlas/v2/groups/{group_id}"
           f"/processes/{process_id}/measurements")
    params = [("granularity", granularity), ("period", period)]
    print(f"\nGET {url}")
    print(f"params: granularity={granularity} period={period} (no m=)")
    resp = requests.get(url, params=params, headers=headers, auth=auth, timeout=30)
    print(f"status: {resp.status_code}")
    if not resp.ok:
        print(resp.text[:2000])
        sys.exit(1)
    body = resp.json()
    types = [{"name": m.get("name"), "units": m.get("units")}
             for m in body.get("measurements", [])]
    print(json.dumps({"processId": process_id, "metrics": types}, indent=2))


def stack_0000_mongos():
    group_id = "69f540390d7996cda4bdefb2"
    process_id = "atlas-gwpbup-config-00-00.c0xht1.mongodb.net:27016"  # fill in
    granularity = "PT1M"
    period = "PT1H"

    auth, headers = get_auth()
    headers["Accept"] = "application/vnd.atlas.2025-03-12+json"

    # 2. Enumerate host/hardware metric TYPES for one mongod process. There's
    #    no dedicated "list names" endpoint, but calling /measurements with no
    #    m= returns every metric applicable to the process — we strip the data
    #    points and keep only name + units.
    url = (f"https://cloud.mongodb.com/api/atlas/v2/groups/{group_id}"
           f"/processes/{process_id}/measurements")
    params = [("granularity", granularity), ("period", period)]
    print(f"\nGET {url}")
    print(f"params: granularity={granularity} period={period} (no m=)")
    resp = requests.get(url, params=params, headers=headers, auth=auth, timeout=30)
    print(f"status: {resp.status_code}")
    if not resp.ok:
        print(resp.text[:2000])
        sys.exit(1)
    body = resp.json()
    types = [{"name": m.get("name"), "units": m.get("units")}
             for m in body.get("measurements", [])]
    print(json.dumps({"processId": process_id, "metrics": types}, indent=2))


def list_processes():
    group_id = "674f42f21212e000bcbc3735"

    """Dump every /processes entry for a project with its typeName and the
    topology fields that disambiguate role. Follows pagination so a project
    with >100 processes isn't truncated.

    Use this to figure out what Atlas is calling what — e.g. verifying that
    gather_info.py's SHARD_MONGOS filter picks the right rows."""
    auth, headers = get_auth()
    headers["Accept"] = "application/vnd.atlas.2025-03-12+json"

    results, page = [], 1
    while True:
        url = f"https://cloud.mongodb.com/api/atlas/v2/groups/{group_id}/processes"
        params = {"pageNum": page, "itemsPerPage": 500}
        resp = requests.get(url, params=params, headers=headers, auth=auth, timeout=30)
        if not resp.ok:
            print(f"GET {url} -> {resp.status_code}")
            print(resp.text[:2000])
            sys.exit(1)
        body = resp.json()
        batch = body.get("results") or []
        results.extend(batch)
        if len(batch) < 500:
            break
        page += 1

    # Tabular dump: fixed-width columns so grep / column-k works.
    print(f"GET https://cloud.mongodb.com/api/atlas/v2/groups/{group_id}/processes")
    print(f"total: {len(results)} process(es)")
    print()
    header = f"{'typeName':<18} {'port':>5}  {'hostname':<60} {'userAlias':<60} {'replicaSetName':<36} {'shardName':<20}"
    print(header)
    print("-" * len(header))
    for p in sorted(results, key=lambda x: (x.get("typeName") or "", x.get("hostname") or "")):
        print(
            f"{(p.get('typeName') or '-'):<18} "
            f"{(p.get('port') or 0):>5}  "
            f"{(p.get('hostname') or '-'):<60} "
            f"{(p.get('userAlias') or '-'):<60} "
            f"{(p.get('replicaSetName') or '-'):<36} "
            f"{(p.get('shardName') or '-'):<20}"
        )
    # Role tally so the user sees the SHARD_MONGOS count at a glance.
    tally = {}
    for p in results:
        t = p.get("typeName") or "UNKNOWN"
        tally[t] = tally.get(t, 0) + 1
    print()
    print("tally by typeName:")
    for t, n in sorted(tally.items()):
        print(f"  {t:<18} {n}")




def armen_cluster2_mongos():
    group_id = "674f42f21212e000bcbc3735"
    process_id = "atlas-wzoov2-config-00-00.jds2f.mongodb.net:27016"
    granularity = "PT1M"
    period = "PT1H"

    auth, headers = get_auth()
    headers["Accept"] = "application/vnd.atlas.2025-03-12+json"

    # 2. Enumerate host/hardware metric TYPES for one mongod process. There's
    #    no dedicated "list names" endpoint, but calling /measurements with no
    #    m= returns every metric applicable to the process — we strip the data
    #    points and keep only name + units.
    url = (f"https://cloud.mongodb.com/api/atlas/v2/groups/{group_id}"
           f"/processes/{process_id}/measurements")
    params = [("granularity", granularity), ("period", period)]
    print(f"\nGET {url}")
    print(f"params: granularity={granularity} period={period} (no m=)")
    resp = requests.get(url, params=params, headers=headers, auth=auth, timeout=30)
    print(f"status: {resp.status_code}")
    if not resp.ok:
        print(resp.text[:2000])
        sys.exit(1)
    body = resp.json()
    types = [{"name": m.get("name"), "units": m.get("units")}
             for m in body.get("measurements", [])]
    print(json.dumps({"processId": process_id, "metrics": types}, indent=2))



if __name__ == "__main__":
    # Diagnostic: list every process in the project with its typeName so we
    # can see what Atlas is actually calling 'mongos' vs 'config' vs 'shard'.
    # armen_cluster2_mongos()
    list_processes()