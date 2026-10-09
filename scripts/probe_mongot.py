#!/usr/bin/env python3
"""Manually fetch Search Node FTS metrics from the Atlas Admin API.

Bypasses the extractor so you can see Atlas's raw response. Loads
credentials from .env (ATLAS_CLIENT_ID / ATLAS_CLIENT_SECRET), takes
a group-id + process-id, and prints the measurements response.

Usage:
    ~/.pyenv/versions/rightsizing/bin/python scripts/probe_search.py \\
        --group-id 674f42f21212e000bcbc3735 \\
        --process-id cluster0-shard-00-search-c72yst.jds2f.mongodb.net:27020 \\
        [--granularity PT1M] [--period PT1H]

Try different granularity/period combos if the default returns empties.
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


# Canonical list — mirrors the /fts/metrics catalog Atlas publishes for a
# Search Node (hardwareMetrics + statusMetrics). Verified against
# /api/atlas/v2/groups/{gid}/hosts/{procId}/fts/metrics on 2026-10-07.
# Served by /fts/metrics/measurements (what probe_search.py queries below).
#
# INDEX_METRICS from the same catalog are intentionally NOT included —
# they live on a different endpoint:
# /fts/metrics/indexes/{database}/{collection}/measurements
# Mixing them in here would make Atlas reject the request.
METRICS = [
    # hardwareMetrics (8)
    "FTS_DISK_USAGE",                    # BYTES
    "FTS_PROCESS_CPU_USER",              # PERCENT
    "FTS_PROCESS_CPU_KERNEL",            # PERCENT
    "FTS_PROCESS_NORMALIZED_CPU_USER",   # PERCENT
    "FTS_PROCESS_NORMALIZED_CPU_KERNEL", # PERCENT
    "FTS_PROCESS_RESIDENT_MEMORY",       # BYTES
    # "FTS_PROCESS_VIRTUAL_MEMORY",        # BYTES
    # "FTS_PROCESS_SHARED_MEMORY",         # BYTES
    # statusMetrics (3)
    "JVM_CURRENT_MEMORY",                # MEGABYTES (not BYTES)
    "JVM_MAX_MEMORY",                    # MEGABYTES (not BYTES)
    "PAGE_FAULTS",                       # SCALAR_PER_SECOND
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group-id", required=True)
    ap.add_argument("--process-id", required=True,
                    help="Full host:port, e.g. cluster0-shard-00-search-xxx.<domain>:27020")
    ap.add_argument("--granularity", default="PT1M")
    ap.add_argument("--period", default="PT1H")
    ap.add_argument("--metrics", nargs="*", default=METRICS)
    args = ap.parse_args()

    auth, headers = get_auth()
    headers["Accept"] = "application/vnd.atlas.2025-03-12+json"
    url = (f"https://cloud.mongodb.com/api/atlas/v2/groups/{args.group_id}"
           f"/hosts/{args.process_id}/fts/metrics/measurements")
    params = [("granularity", args.granularity), ("period", args.period)]
    params += [("metrics", m) for m in args.metrics]

    print(f"GET {url}")
    print(f"auth: {'digest' if auth else 'oauth'}")
    print(f"params: granularity={args.granularity} period={args.period} "
          f"metrics={len(args.metrics)}")
    resp = requests.get(url, params=params, headers=headers, auth=auth, timeout=30)
    print(f"status: {resp.status_code}")
    if not resp.ok:
        print(resp.text[:2000])
        sys.exit(1)

    body = resp.json()
    print(f"top-level keys: {list(body.keys())}")
    print(f"echo: granularity={body.get('granularity')} period={body.get('period')} "
          f"start={body.get('start')} end={body.get('end')} "
          f"processId={body.get('processId')} hostId={body.get('hostId')}")

    for container in ("measurements", "hardwareMeasurements", "ftsMeasurements"):
        if container in body:
            print(f"\n--- {container} ({len(body[container])} entries) ---")
            for m in body[container]:
                pts = m.get("dataPoints") or []
                non_null = sum(1 for p in pts if p.get("value") is not None)
                sample = next((p for p in pts if p.get("value") is not None), None)
                print(f"  {m.get('name'):40s} units={m.get('units'):10s} "
                      f"total={len(pts):4d} non_null={non_null:4d} "
                      f"sample={sample}")

    # Dump the whole thing optionally
    if "--full" in sys.argv:
        print("\n--- full response ---")
        print(json.dumps(body, indent=2))


def stack_9999():
    group_id = "68eeb0319504d9287e9f717f"
    # process_id = "stack-9999-shard-00-search-grvjpi.qbghmu.mongodb.net:27020"
    process_id = "stack-9999-shard-00-search-rbvben.qbghmu.mongodb.net:27020"

   
    # get types
    # -------
    auth, headers = get_auth()
    headers["Accept"] = "application/vnd.atlas.2025-03-12+json"
    url = (f"https://cloud.mongodb.com/api/atlas/v2/groups/{group_id}"
           f"/hosts/{process_id}/fts/metrics")
    params=[]
    # params = [("granularity", args.granularity), ("period", args.period)]
    # params += [("metrics", m) for m in args.metrics]

    print(f"GET {url}")
    print(f"auth: {'digest' if auth else 'oauth'}")
    # print(f"params: granularity={args.granularity} period={args.period} "
        #   f"metrics={len(args.metrics)}")
    resp = requests.get(url, params=params, headers=headers, auth=auth, timeout=30)
    print(f"status: {resp.status_code}")
    if not resp.ok:
        print(resp.text[:2000])
        sys.exit(1)

    body = resp.json()
    # pretty print json
    print(json.dumps(body, indent=2))


    # get values
    # ----------
    # ISO 8601: granularity (bucket size) + period (lookback window).
    # Atlas caps points-per-request, so these are the safe pairings:
    #   PT1M + PT1H   (60 points)   — spot-check last hour
    #   PT1M + PT6H   (360 points)  — spot-check last 6 h
    #   PT5M + P1D    (288 points)  — last day
    #   PT1H + P7D    (168 points)  — last 7 days   <- default below
    #   P1D  + P30D   (30 points)   — last 30 days
    # PT1M + P7D would request 10,080 points and Atlas will reject it.
    # granularity = "PT1H"
    granularity = "P1D"
    period = "P30D"
    metrics = METRICS

    url = (f"https://cloud.mongodb.com/api/atlas/v2/groups/{group_id}"
           f"/hosts/{process_id}/fts/metrics/measurements")
    params = [("granularity", granularity), ("period", period)]
    params += [("metrics", m) for m in metrics]
    resp = requests.get(url, params=params, headers=headers, auth=auth, timeout=30)
    print(resp.request.url)
    print(f"status: {resp.status_code}")
    if not resp.ok:
        print(resp.text[:2000])
        sys.exit(1)

    body = resp.json()
    # pretty print json
    print(json.dumps(body, indent=2))

def probe_mongot():
    group_id = "674f42f21212e000bcbc3735"
    cluster_name = "Cluster0"
    # process_id = "cluster0-shard-00-search-c72yst.jds2f.mongodb.net:27020"
    process_id = "cluster0-shard-00-search-c72yst.jds2f.mongodb.net:28000"

    auth, headers = get_auth()
    headers["Accept"] = "application/vnd.atlas.2025-03-12+json"

    # 0. List Atlas Search indexes for the cluster. This is how gather_info.py
    #    discovers Search Node hostnames: each index's statusDetail[] has one
    #    entry per Search Node hosting it, each carrying a .hostname field.
    #    Empty list == no Search indexes defined → no hostnames discoverable.
    url = (f"https://cloud.mongodb.com/api/atlas/v2/groups/{group_id}"
           f"/clusters/{cluster_name}/search/indexes")
    print(f"GET {url}")
    resp = requests.get(url, headers=headers, auth=auth, timeout=30)
    print(f"status: {resp.status_code}")
    if not resp.ok:
        print(resp.text[:2000])
        sys.exit(1)
        
    print(json.dumps(resp.json(), indent=2))
    

    indexes = resp.json() if isinstance(resp.json(), list) else []
    print(f"indexes: {len(indexes)}")
    all_hosts = set()
    for idx in indexes:
        hosts = sorted({(st.get("hostname") or "") for st in (idx.get("statusDetail") or []) if st.get("hostname")})
        all_hosts.update(hosts)
        print(f"  - {idx.get('name'):30s}  db={idx.get('database'):20s}  "
              f"coll={idx.get('collectionName'):20s}  nodes={hosts}")
    print(f"unique search-node hostnames: {sorted(all_hosts)}")
    print()

    # get types
    # -------
    url = (f"https://cloud.mongodb.com/api/atlas/v2/groups/{group_id}"
           f"/hosts/{process_id}/fts/metrics")
    params=[]
    # params = [("granularity", args.granularity), ("period", args.period)]
    # params += [("metrics", m) for m in args.metrics]

    # print(f"GET {url}")
    # print(f"auth: {'digest' if auth else 'oauth'}")
    # # print(f"params: granularity={args.granularity} period={args.period} "
    #     #   f"metrics={len(args.metrics)}")
    # resp = requests.get(url, params=params, headers=headers, auth=auth, timeout=30)
    # print(f"status: {resp.status_code}")
    # if not resp.ok:
    #     print(resp.text[:2000])
    #     sys.exit(1)

    # body = resp.json()
    # # pretty print json
    # print(json.dumps(body, indent=2))


    # get values
    # ----------
    # ISO 8601: granularity (bucket size) + period (lookback window).
    # Atlas caps points-per-request, so these are the safe pairings:
    #   PT1M + PT1H   (60 points)   — spot-check last hour
    #   PT1M + PT6H   (360 points)  — spot-check last 6 h
    #   PT5M + P1D    (288 points)  — last day
    #   PT1H + P7D    (168 points)  — last 7 days   <- default below
    #   P1D  + P30D   (30 points)   — last 30 days
    # PT1M + P7D would request 10,080 points and Atlas will reject it.
    granularity = "PT1H"
    # granularity = "P1D"
    period = "P7D"
    metrics = METRICS

    url = (f"https://cloud.mongodb.com/api/atlas/v2/groups/{group_id}"
           f"/hosts/{process_id}/fts/metrics/measurements")
    # params = [("granularity", granularity), ("period", period)]
    # params += [("metrics", m) for m in metrics]
    
    params = {
        "granularity": granularity,
        "period": period,
        # "metrics": METRICS,   # list -> repeated metrics=... keys
    }
        
    resp = requests.get(url, params=params, headers=headers, auth=auth, timeout=30)
    print(resp.request.url)
    print(f"status: {resp.status_code}")
    if not resp.ok:
        print(resp.text[:2000])
        sys.exit(1)

    body = resp.json()
    # pretty print json
    print(json.dumps(body, indent=2))


if __name__ == "__main__":
    probe_mongot()
