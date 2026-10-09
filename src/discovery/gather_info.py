#!/usr/bin/env python3
"""
Discover every Atlas project the API credentials can see, and every cluster in
each project. Writes a JSON inventory (org info + per-project cluster list) to
a folder named after the org so multi-org environments don't overwrite each
other.

Default output path:
    <project root>/<OUTPUT_DIR>/<org_slug>/inventory.json

OUTPUT_DIR is read from the environment (default: "output"). Override the full
path with --out. The `output/` folder itself lives at the project root, not
where you happen to invoke the script from.

Useful as the first step before running rightsizing.py or atlas_db_diagnostics.py
across many projects/clusters — you get the group IDs you need for --group-id
without hunting through the Atlas UI.

Auth (env only): same as rightsizing.py.
  ATLAS_CLIENT_ID / ATLAS_CLIENT_SECRET (preferred, OAuth2), OR
  ATLAS_PUBLIC_KEY / ATLAS_PRIVATE_KEY (legacy API key, HTTP Digest)

Read-only. Never modifies a project or cluster.

Usage:
  python gather_info.py                        # writes to the default per-org path
  python gather_info.py --out ./inventory.json # override the whole path

Only dependency: `requests` (already required by rightsizing.py).
"""

import argparse
import json
import os
import re
import sys

# Put src/ on sys.path so `common.atlas_api` resolves when this file is run
# directly (e.g. `python src/discovery/gather_info.py`) — Python only adds
# the script's own directory (src/discovery/) by default, not its parent.
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from common.atlas_api import AtlasClient, AtlasAPIError, utc_now  # noqa: E402
from constants.atlas_process_types import MONGOS_TYPES  # noqa: E402


# Project root = 3 levels up from src/discovery/gather_info.py. Anchoring here
# means the default output folder lives at the project root regardless of the
# shell cwd from which the script is invoked.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_OUTPUT_DIR_NAME = os.environ.get("OUTPUT_DIR", "output")

# Dedicated Search Nodes listen on this port. Confirmed empirically against
# a live Atlas cluster on 2026-10-08 (older topologies used 27020). Not
# returned by any API — /search/indexes gives short hostnames only,
# /search/deployment has no hostnames, mongot does not appear in /processes.
# If Atlas changes this again, update here and in
# src/extraction/extract_search_data.py (same constant, duplicated).
SEARCH_NODE_PORT = 28000


def _slugify(name):
    """Make a filesystem-safe folder name from an arbitrary org name."""
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", (name or "").strip()).strip("_")
    return slug or "unknown_org"


def cluster_tiers(cluster_cfg):
    """Every instanceSize seen across regionConfigs, deduplicated. A cluster with
    one tier returns one entry; a multi-region cluster with mismatched tiers
    returns them all."""
    tiers = set()
    for spec in cluster_cfg.get("replicationSpecs", []):
        for rc in spec.get("regionConfigs", []):
            # Dedicated replica sets nest instanceSize under electableSpecs;
            # sharded clusters put it directly on the regionConfig.
            electable = rc.get("electableSpecs") or {}
            size = electable.get("instanceSize") or rc.get("instanceSize")
            if size:
                tiers.add(size)
    return sorted(tiers)


def _cluster_regions(cluster_cfg):
    """Per-regionConfig breakdown with the hardware fields that make the
    inventory self-describing: provider, region, provisioned instance_size,
    node_count, per-region disk_iops and (AWS) ebs_volume_type.

    Prefers effectiveElectableSpecs (reflects autoscale drift), then
    electableSpecs (requested), then the regionConfig-level field (sharded
    v2 shape). Mirrors extraction.common.summarize_config()['regions'] so
    inventory consumers see the same shape as extraction.json."""
    rows = []
    for spec in (cluster_cfg or {}).get("replicationSpecs", []):
        for rc in spec.get("regionConfigs", []):
            effective = rc.get("effectiveElectableSpecs") or {}
            electable = rc.get("electableSpecs") or {}
            instance_size = (
                effective.get("instanceSize")
                or electable.get("instanceSize")
                or rc.get("instanceSize")
            )
            node_count = (
                effective.get("nodeCount")
                or electable.get("nodeCount")
                or rc.get("nodeCount")
            )
            disk_iops = (
                effective.get("diskIOPS")
                if effective.get("diskIOPS") is not None else
                electable.get("diskIOPS")
                if electable.get("diskIOPS") is not None else
                rc.get("diskIOPS")
            )
            # Atlas 2024-05-30+ nests diskSizeGB under electableSpecs; the
            # top-level cluster.diskSizeGB is absent on newer-API responses.
            disk_size_gb = (
                effective.get("diskSizeGB")
                if effective.get("diskSizeGB") is not None else
                electable.get("diskSizeGB")
                if electable.get("diskSizeGB") is not None else
                rc.get("diskSizeGB")
            )
            ebs_volume_type = (
                effective.get("ebsVolumeType")
                or electable.get("ebsVolumeType")
                or rc.get("ebsVolumeType")
            )
            rows.append({
                "provider": rc.get("providerName"),
                "backing_provider": rc.get("backingProviderName"),
                "region": rc.get("regionName"),
                "instance_size": instance_size,
                "node_count": node_count,
                "disk_iops": disk_iops,
                "disk_size_gb": disk_size_gb,
                "ebs_volume_type": ebs_volume_type,
            })
    return rows


def _extract_mongod_hosts(cluster_cfg):
    """Pull mongod host process IDs (host:port) and short hostnames out of
    the cluster's standard connection string.

    Returns (process_ids, short_hostnames) — parallel lists. Both empty when
    connectionStrings.standard is missing (paused/pending clusters, tiny
    tiers with no direct connection string, etc.).

    For sharded clusters connectionStrings.standard lists mongos endpoints,
    not shard members. Add /processes filtering per shard if you need the
    per-shard mongod IDs."""
    if not cluster_cfg:
        return [], []
    std = (cluster_cfg.get("connectionStrings") or {}).get("standard") or ""
    if not std:
        return [], []
    # 'mongodb://host1:port,host2:port,host3:port/?opts=...'
    after_scheme = std.split("://", 1)[-1]
    hosts_part = after_scheme.split("/", 1)[0]
    process_ids = [h.strip() for h in hosts_part.split(",") if h.strip()]
    # Short = first DNS label of the host part (strip port, then strip domain).
    short_names = [pid.split(":", 1)[0].split(".", 1)[0] for pid in process_ids]
    return process_ids, short_names


def _extract_mongos_hosts(cluster_cfg, project_processes):
    """Pull mongos (host:port, short-hostname) parallel lists from the project's
    /processes response, scoped to the given cluster.

    SHARDED-ONLY: replica-set clusters have no mongos; returns ([], []).

    Matching: connectionStrings.standard lists the mongos endpoints by
    userAlias for THIS cluster (e.g. 'data-products-config-00-00'). We
    build the set of expected userAliases from that string and match
    /processes entries by typeName == SHARD_MONGOS *and* userAlias. Domain
    alone isn't enough — multiple clusters in a project share a DNS domain
    (e.g. '.c0xht1.mongodb.net'), so a domain-only filter bundles their
    mongos together. The returned host:port uses the internal `hostname`
    field (not userAlias) because that's what the /measurements endpoint
    expects."""
    if not cluster_cfg or not project_processes:
        return [], []
    client_facing_ids, _ = _extract_mongod_hosts(cluster_cfg)
    expected_aliases = {pid.split(":", 1)[0] for pid in client_facing_ids}
    if not expected_aliases:
        return [], []
    process_ids, short_names = [], []
    for p in project_processes:
        if p.get("typeName") not in MONGOS_TYPES:
            continue
        alias = p.get("userAlias") or ""
        if alias not in expected_aliases:
            continue
        hostname = p.get("hostname") or ""
        port = p.get("port")
        pid = f"{hostname}:{port}" if port else hostname
        process_ids.append(pid)
        short_names.append(hostname.split(".", 1)[0])
    return process_ids, short_names


def summarize_cluster(cfg, project_processes=None):
    tiers = cluster_tiers(cfg)
    process_ids, short_hostnames = _extract_mongod_hosts(cfg)
    mongos_ids, mongos_short = _extract_mongos_hosts(
        cluster_cfg=cfg, project_processes=project_processes or [])
    regions = _cluster_regions(cfg)
    disk_size_gb = cfg.get("diskSizeGB")
    if disk_size_gb is None:
        for r in regions:
            if r.get("disk_size_gb") is not None:
                disk_size_gb = r["disk_size_gb"]
                break
    return {
        "name": cfg.get("name"),
        "cluster_type": cfg.get("clusterType"),
        "mongodb_version": cfg.get("mongoDBVersion"),
        "state": cfg.get("stateName"),
        "paused": cfg.get("paused"),
        "tier": tiers[0] if len(tiers) == 1 else (tiers or None),
        "disk_size_gb": disk_size_gb,
        "regions": regions,
        "create_date": cfg.get("createDate"),
        "mongod_process_ids": process_ids,
        "mongod_hostnames": short_hostnames,
        "mongos_process_ids": mongos_ids,
        "mongos_hostnames": mongos_short,
    }


def _fetch_search_deployment(client, project_id, cluster_name):
    """Return the dedicated-Search-Nodes deployment for a cluster, or None if
    the cluster has no dedicated Search Nodes (Atlas 404s in that case).
    Any other Atlas error is re-raised."""
    try:
        return client.get(f"/groups/{project_id}/clusters/{cluster_name}/search/deployment")
    except AtlasAPIError as e:
        if "404" in str(e):
            return None
        raise


def _discover_search_node_hostnames(client, project_id, cluster_name):
    """Auto-discover per-Search-Node short hostnames via /search/indexes.

    Each Atlas Search index carries a `statusDetail[]` array with one entry
    per Search Node hosting the index; each entry has a `hostname` field.
    Returns a sorted list of unique short hostnames, or an empty list when
    the cluster has no Search indexes / the endpoint isn't accessible."""
    try:
        indexes = client.get(
            f"/groups/{project_id}/clusters/{cluster_name}/search/indexes"
        )
    except AtlasAPIError:
        return []
    if not isinstance(indexes, list):
        return []
    hosts = set()
    for idx in indexes:
        for st in (idx.get("statusDetail") or []):
            h = st.get("hostname")
            if h:
                hosts.add(h)
    return sorted(hosts)


def _extract_cluster_domain(cluster_cfg):
    """Pull the connection-string domain (e.g. '.jds2f.mongodb.net') out of
    the cluster's standard connection string. Returns None if unparseable."""
    if not cluster_cfg:
        return None
    std = (cluster_cfg.get("connectionStrings") or {}).get("standard") or ""
    if not std:
        return None
    # 'mongodb://cluster0-shard-00-00.jds2f.mongodb.net:27017,...'
    first_host = std.split("://", 1)[-1].split("/", 1)[0].split(",", 1)[0]
    bare = first_host.split(":", 1)[0]
    # bare = 'cluster0-shard-00-00.jds2f.mongodb.net' → strip the first label
    _, _, tail = bare.partition(".")
    return f".{tail}" if tail else None


def summarize_search_deployment(deployment):
    """Compact summary of /search/deployment for the inventory.

    `dedicated_search_nodes` is True only when Atlas returned a non-empty
    specs array. That answers "are dedicated Search Nodes (S-tier) present?"
    — NOT "is mongot running?". Co-located mongot (the default when Search
    is enabled on M10+ without dedicated Search Nodes) is invisible here.

    `specs[]` is the aggregate Search-Node topology, matching Atlas's own
    /search/deployment shape: each entry describes an instance_size / count
    pair. Sum of node_count = total dedicated Search Node instances."""
    if not deployment:
        return {"dedicated_search_nodes": False, "state": None, "specs": []}
    specs = deployment.get("specs") or []
    if not specs:
        return {"dedicated_search_nodes": False, "state": deployment.get("stateName"), "specs": []}
    return {
        "dedicated_search_nodes": True,
        "state": deployment.get("stateName"),
        "specs": [
            {"instance_size": s.get("instanceSize"), "node_count": s.get("nodeCount")}
            for s in specs
        ],
    }


# ---------------------------------------------------------------------------
# CLI entrypoint
#
# Package uses relative imports, so run via -m from the project root:
#
#   python -m src.extraction.extract --group-id "$ATLAS_GROUP_ID" \
#                                    --cluster Cluster0 --days 7 \
#                                    --out ./extraction.json
#
# Prints the extractor's dict as JSON on stdout (or to --out). Reads Atlas
# credentials from the same env vars as scripts/rightsizing.py.
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None,
                    help=(f"Output path. Default: "
                          f"{_PROJECT_ROOT}/{_OUTPUT_DIR_NAME}/<org_slug>/inventory.json"))
    args = ap.parse_args(argv)

    try:
        client = AtlasClient()
    except AtlasAPIError as e:
        sys.exit(str(e))

    try:
        orgs = client.get_all("/orgs")
    except AtlasAPIError as e:
        sys.exit(f"Atlas API error listing orgs: {e}")
    if not orgs:
        sys.exit("No Atlas orgs visible to the credentials.")
    primary_org = orgs[0]
    if len(orgs) > 1:
        # Service accounts are usually single-org, but multi-org creds exist.
        # Use the first for the folder name; the inventory JSON records which.
        others = ", ".join(o.get("name", "?") for o in orgs[1:5])
        print(f"[warn] Credentials expose {len(orgs)} orgs; using "
              f"{primary_org.get('name')!r} for the output folder. Others: {others}",
              file=sys.stderr)

    try:
        groups = client.get_all("/groups")
    except AtlasAPIError as e:
        sys.exit(f"Atlas API error listing projects: {e}")

    projects, total_clusters = [], 0
    for g in sorted(groups, key=lambda x: (x.get("name") or "").lower()):
        pid, pname = g.get("id"), g.get("name")
        try:
            clusters = client.get_all(f"/groups/{pid}/clusters")
        except AtlasAPIError as e:
            projects.append({"id": pid, "name": pname, "org_id": g.get("orgId"),
                             "error": str(e), "clusters": []})
            print(f"[err]  {pname} ({pid}): {e}", file=sys.stderr)
            continue
        # One fetch per project — processes carry typeName (SHARD_MONGOS,
        # SHARD_CONFIG, REPLICA_PRIMARY, etc.) and are filtered per cluster
        # by DNS domain inside summarize_cluster.
        try:
            processes = client.get_all(f"/groups/{pid}/processes")
        except AtlasAPIError as e:
            processes = []
            print(f"[warn] {pname} ({pid}): /processes fetch failed, mongos "
                  f"hostnames will be empty: {e}", file=sys.stderr)
        summarized = []
        for c in clusters:
            entry = summarize_cluster(cfg=c, project_processes=processes)
            try:
                deployment = _fetch_search_deployment(client=client, project_id=pid,
                                                      cluster_name=entry["name"])
            except AtlasAPIError as e:
                entry["search"] = {"error": f"/search/deployment fetch: {e}"}
            else:
                entry["search"] = summarize_search_deployment(deployment=deployment)

            # Auto-discover per-Search-Node hostnames via /search/indexes →
            # statusDetail[].hostname. Requires at least one Search index to
            # exist on the cluster; otherwise the list is empty.
            short_hosts = _discover_search_node_hostnames(client=client, project_id=pid,
                                                          cluster_name=entry["name"])
            if short_hosts:
                # /clusters LIST already includes connectionStrings, so `c` has
                # the domain we need — no extra fetch required.
                domain = _extract_cluster_domain(c) or ""
                entry["search"]["node_process_ids"] = [
                    f"{h}{domain}:{SEARCH_NODE_PORT}" for h in short_hosts
                ]
                entry["search"]["node_hostnames"] = short_hosts
            else:
                entry["search"]["node_process_ids"] = []
                entry["search"]["node_hostnames"] = []

            summarized.append(entry)
        summarized.sort(key=lambda c: (c["name"] or "").lower())
        projects.append({
            "id": pid,
            "name": pname,
            "org_id": g.get("orgId"),
            "cluster_count": len(summarized),
            "clusters": summarized,
        })
        total_clusters += len(summarized)
        print(f"[ok]   {pname} ({pid}): {len(summarized)} cluster(s)")

    inventory = {
        "generated_at": utc_now(),
        "org": {"id": primary_org.get("id"), "name": primary_org.get("name")},
        "project_count": len(projects),
        "cluster_count": total_clusters,
        "projects": projects,
    }

    out_path = args.out or os.path.join(
        _PROJECT_ROOT, _OUTPUT_DIR_NAME,
        _slugify(primary_org.get("name")), "inventory.json",
    )
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=2, default=str)

    print(f"\nWrote {len(projects)} project(s), {total_clusters} cluster(s) to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
