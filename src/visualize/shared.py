"""
Helpers shared between the two visualize renderers (`visualize_old` — overlay
view, `visualize_new` — per-node memory view).

Everything in here is pure data-shaping or Plotly-primitive wiring — no
HTML, CSS, or JS. That boundary is what lets the two renderers diverge in
their user-facing layout without duplicating the extraction-walking, tier
spec resolution, bytes auto-scaling, or SystemMemoryMetrics plumbing.

Imports expect `src/` on `sys.path` (both renderers set it via
`sys.path.append(_SRC_DIR)` before importing this module).
"""

import plotly.colors

from atlas_tier_spec import load_search_tier_spec, load_tier_spec
from common.disk_iops_metrics import DiskIopsMetrics
from common.disk_throughput_metrics import DiskThroughputMetrics
from common.search_memory_metrics import SearchMemoryMetrics
from common.system_memory_metrics import SystemMemoryMetrics


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Bytes per gibibyte. 1024**3 (binary) matches BYTE_SCALES so a tier
#: ceiling of 16 GiB lands on a round "16 GB" tick after auto-scaling.
BYTES_PER_GB = 1024 ** 3

#: Fixed palette so overlays (horizontal stat lines in the overlay view,
#: single-trace tiles in the per-node view) can match a node's own color.
#: Plotly's auto color cycle would otherwise drift later entries off.
PALETTE = plotly.colors.qualitative.Plotly

#: Y-axis display labels that qualify for 1024-based auto-scaling.
BYTE_UNITS = {"bytes", "bytes/sec"}

#: Scale thresholds for the bytes auto-scaler. Walked in descending order
#: so the largest matching unit wins (e.g. 2 TiB picks TB, not GB).
BYTE_SCALES = (
    (1024 ** 4, "TB"),
    (1024 ** 3, "GB"),
    (1024 ** 2, "MB"),
    (1024,      "KB"),
)


# ---------------------------------------------------------------------------
# Bytes y-axis auto-scaling
# ---------------------------------------------------------------------------

def scale_bytes_unit(traces, unit, extra_max=None):
    """For bytes-based y-axes, pick a scale factor and matching label from
    the figure's max value so a 5 GB memory series renders as 5 instead of
    5e9. Scale is 1024-based (binary); non-bytes units pass through
    unchanged. Returns (scale, display_label); callers divide every y by
    `scale`.

    `extra_max` lets a caller force the scale to accommodate a value
    above the data's own max — e.g. a tier memory ceiling at 16 GiB when
    the actual series tops out at 10 GiB. Without it the scale would be
    picked from data alone, and the ceiling line (or y-axis range) would
    land in a different unit than the data."""
    if unit not in BYTE_UNITS:
        return 1, unit
    max_val = extra_max or 0
    for _, series in traces:
        if not series:
            continue
        for _, v in series:
            if v is not None and v > max_val:
                max_val = v
    if max_val < 1024:
        return 1, unit
    suffix = "/sec" if unit == "bytes/sec" else ""
    for threshold, label in BYTE_SCALES:
        if max_val >= threshold:
            return threshold, f"{label}{suffix}"
    return 1, unit


# ---------------------------------------------------------------------------
# Trace labels (base + role suffix)
# ---------------------------------------------------------------------------

def short_role(role):
    """Trim Atlas typeName to the useful suffix so legend labels stay short.
    REPLICA_PRIMARY / SHARD_PRIMARY -> PRIMARY. SHARD_CONFIG_SECONDARY ->
    CONFIG_SECONDARY. SHARD_MONGOS -> MONGOS."""
    if not role:
        return ""
    r = str(role)
    for prefix in ("REPLICA_", "SHARD_"):
        if r.startswith(prefix):
            r = r[len(prefix):]
    return r


def trace_label(base, role):
    """`buildkite-runner-shard-00-00:27017` + REPLICA_PRIMARY ->
    `buildkite-runner-shard-00-00:27017 (PRIMARY)`. The `(ROLE)` suffix is
    what the overlay view's role-toggle JS regex reads; keep the format
    stable."""
    short = short_role(role=role)
    return f"{base} ({short})" if short else base


# ---------------------------------------------------------------------------
# Point-tuple → Plotly xs/ys split
# ---------------------------------------------------------------------------

def series_to_xy(series):
    """[(iso_ts, v), ...] -> (xs, ys). Plotly renders ISO 8601 strings as datetime."""
    if not series:
        return [], []
    xs, ys = [], []
    for ts, v in series:
        xs.append(ts)
        ys.append(v)
    return xs, ys


# ---------------------------------------------------------------------------
# Tier spec resolution (shared with the extractor via atlas_tier_spec)
# ---------------------------------------------------------------------------

def resolve_tier_spec(provider, instance_size, generation, cls):
    """Load the TierSpec for one region via the shared atlas_tier_spec
    module (which drives extract.py's _resolve_tier_specs). Returns a plain
    dict so the hardware-panel formatters don't need to know about the
    dataclass. Empty dict on lookup failure — callers that render tier
    cells will show '-' in the affected columns."""
    try:
        spec = load_tier_spec(
            provider=provider,
            instance_size=instance_size,
            generation=generation,
            cls=cls,
        )
    except (LookupError, FileNotFoundError):
        return {}
    return {
        "vcpus":                    spec.vcpus,
        "memory_gb":                spec.memory_gb,
        "storage_min_gb":           spec.storage_min_gb,
        "storage_max_gb":           spec.storage_max_gb,
        "extended_storage_max_gb":  spec.extended_storage_max_gb,
        "disk_iops_min":            spec.disk_iops_min,
        "disk_iops_max":            spec.disk_iops_max,
        "max_disk_iops":            spec.max_disk_iops,
        "max_connections_per_node": spec.max_connections_per_node,
        "network_performance":      spec.network_performance,
    }


def primary_region_memory_gb(extraction):
    """Physical memory ceiling (GB) for the mongod sections, from
    `config.regions[0]`. For heterogeneous shard-tier clusters we'd need
    per-node attribution; today the extraction config doesn't carry that,
    so the common homogeneous case wins and multi-tier clusters eat a
    small inaccuracy on the used% chart. Returns None when the lookup
    fails — the synthesizer no-ops in that case."""
    regions = ((extraction.get("config") or {}).get("regions") or [])
    if not regions:
        return None
    r = regions[0]
    spec = resolve_tier_spec(
        provider=r.get("provider"), 
        instance_size=r.get("instance_size"),
        generation=r.get("generation"), 
        cls=r.get("class"),
    )
    return spec.get("memory_gb")


def primary_region_provisioned_iops(extraction):
    """Provisioned IOPS ceiling (per partition) for the mongod sections,
    computed from `config.regions[0]` + the per-provider tier catalog.
    Routes through `DiskIopsMetrics.calc_provisioned_iops` so the per-
    provider formulas (GCP + AWS today; Azure follow-up) live in one
    place. Returns None when the formula can't be evaluated (missing
    disk size, unknown provider / EBS volume type, catalog miss) — the
    per-node disk IOPS chart then auto-ranges its y-axis instead of
    locking to a ceiling.

    AWS-specific inputs:
      - `region.ebs_volume_type` picks the gp3 baseline formula vs
        io2 "configured" path.
      - `region.disk_iops` is the user-selected IOPS on io2 clusters
        (ignored for gp3). Named "disk_iops" in the extraction region
        shape; mapped to `configured_iops` here."""
    regions = ((extraction.get("config") or {}).get("regions") or [])
    if not regions:
        return None
    r = regions[0]
    spec = resolve_tier_spec(
        provider=r.get("provider"), instance_size=r.get("instance_size"),
        generation=r.get("generation"), cls=r.get("class"),
    )
    return DiskIopsMetrics.calc_provisioned_iops(
        provider=r.get("provider"),
        generation=r.get("generation"),
        disk_size_gb=r.get("disk_size_gb"),
        tier_iops_max=spec.get("disk_iops_max"),
        instance_size=r.get("instance_size"),
        ebs_volume_type=r.get("ebs_volume_type"),
        configured_iops=r.get("disk_iops"),
    )


def primary_region_provisioned_throughput(extraction):
    """Provisioned disk-throughput ceiling (bytes/sec) for the mongod
    sections, computed from `config.regions[0]` + the per-provider tier
    catalog. Routes through
    `DiskThroughputMetrics.calc_provisioned_throughput`:

      - AWS: gp3 base formula + Gen 2 extra-IOPS kicker + io2 PIOPS
        formula + NVMe constant, with per-tier EC2 bandwidth caps.
      - GCP: Gen 1 pd-ssd formula `0.48 * disk_size_gb + 240`, capped
        at the per-vCPU pd-ssd instance limit. Gen 2 (Hyperdisk Balanced)
        not implemented yet.
      - Azure: not implemented.

    Returns None when the formula can't be evaluated — the per-node Disk
    Throughput chart then auto-ranges with no ceiling line."""
    regions = ((extraction.get("config") or {}).get("regions") or [])
    if not regions:
        return None
    r = regions[0]
    # vCPU count feeds the GCP pd-ssd per-instance cap and comes from the
    # tier catalog (AWS branches ignore the kwarg).
    spec = resolve_tier_spec(
        provider=r.get("provider"), instance_size=r.get("instance_size"),
        generation=r.get("generation"), cls=r.get("class"),
    )
    return DiskThroughputMetrics.calc_provisioned_throughput(
        provider=r.get("provider"),
        generation=r.get("generation"),
        instance_size=r.get("instance_size"),
        ebs_volume_type=r.get("ebs_volume_type"),
        disk_size_gb=r.get("disk_size_gb"),
        provisioned_iops=r.get("disk_iops"),
        tier_class=r.get("class"),
        vcpus=spec.get("vcpus"),
    )


def resolve_search_tier_spec(provider, instance_size):
    """Load the SearchTierSpec for one Search Node spec via the shared
    atlas_tier_spec module. Returns a plain dict so downstream formatters
    don't need to know about the dataclass. Empty dict on lookup failure
    (unknown provider / instance size, missing per-provider catalog file —
    today only GCP ships)."""
    try:
        spec = load_search_tier_spec(
            provider=provider, instance_size=instance_size,
        )
    except (LookupError, FileNotFoundError):
        return {}
    return {
        "vcpus":               spec.vcpus,
        "memory_gb":           spec.memory_gb,
        "storage_gb":          spec.storage_gb,
        "disk_iops_read":      spec.disk_iops_read,
        "disk_iops_write":     spec.disk_iops_write,
        "network_performance": spec.network_performance,
    }


def search_memory_gb(extraction):
    """Physical memory ceiling (GB) for dedicated Atlas Search Nodes, from
    `search.specs[0]`. Routes through the Search tier catalog
    (atlas_{provider}_search_tier_spec.json) rather than the mongod catalog
    — Search instance sizes (S10 / S20 / … / S140, each with HIGHCPU_NVME /
    LOWCPU_NVME / STORAGE_NVME variants) don't exist in the latter. Returns
    None when there are no dedicated Search Node specs or the lookup
    fails."""
    specs = ((extraction.get("search") or {}).get("specs") or [])
    if not specs:
        return None
    s = specs[0]
    spec = resolve_search_tier_spec(
        provider=s.get("cloud_provider"),
        instance_size=s.get("instance_size"),
    )
    return spec.get("memory_gb")


# ---------------------------------------------------------------------------
# Extraction → sections
# ---------------------------------------------------------------------------

def collect_mongod_sections(extraction):
    """Return a dict {section_name: [(trace_label, data_dict), ...]}.

    'trace_label' includes the node's role (e.g. "...-shard-00-00:27017
    (PRIMARY)") so a primary is instantly distinguishable from its
    secondaries in the Plotly legend.
    'data_dict' is the node's `data` field ({"host": {...}, "disks": {...}}).
    Sections:
      - "Compute nodes": replica_set nodes OR all shards flattened
      - "mongos routers": sharded only, when routers present
    """
    sections = {}
    t = extraction.get("type")
    if t == "replica_set":
        sections["Compute nodes"] = [
            (trace_label(base=n.get("label") or "unknown", role=n.get("role")),
             n.get("data") or {})
            for n in extraction.get("nodes") or []
        ]
    elif t == "sharded":
        compute = []
        for rs_name, nodes in sorted((extraction.get("shards") or {}).items()):
            for n in nodes:
                base = f"{rs_name} / {n.get('label') or 'unknown'}"
                compute.append((trace_label(base=base, role=n.get("role")),
                                n.get("data") or {}))
        if compute:
            sections["Compute nodes (all shards)"] = compute
        routers = extraction.get("routers") or []
        if routers:
            sections["mongos routers"] = [
                (trace_label(base=n.get("label") or "unknown", role=n.get("role")),
                 n.get("data") or {})
                for n in routers
            ]
    return sections


def collect_search_sections(search):
    """Return a dict for the dedicated-Search-Node subtree. Empty if the
    cluster has no dedicated Search Nodes.

    Produces a Per-Search-Node section when either:
      - search_nodes[] carries real per-node metrics, OR
      - specs declare dedicated nodes but search_nodes[] is empty (discovery
        failed, e.g. no permission on /search/indexes). The section renders
        the discovery_error note so the user sees that dedicated nodes exist
        even without the charts.

    FTS on co-located mongot is intentionally ignored — see
    extract_search_data for the rationale.
    """
    out = {}
    if not search:
        return out
    nodes = search.get("search_nodes") or []
    has_specs = bool(search.get("specs"))
    if nodes:
        out["Atlas Search - per Search Node"] = [
            (n.get("process_id") or "unknown", n.get("data") or {}) for n in nodes
        ]
    elif has_specs:
        # Advertised but we couldn't fetch per-node metrics. Keep the section
        # so the discovery_error becomes visible.
        out["Atlas Search - per Search Node"] = []
    return out


# ---------------------------------------------------------------------------
# Disk-series window trimming
# ---------------------------------------------------------------------------
#
# Disk-partition metrics are fetched over a wider window than host metrics
# (`extraction.disk_days`, default 60) because Atlas can rename the per-
# partition device under the hood on fleet maintenances and the wider fetch
# gives the extractor a better chance of joining the pre-rename slice to
# the current partitionName. The viewer wants the two aligned on the x-axis,
# so both renderers trim disks to the host window at render time.

def earliest_host_timestamp(extraction):
    """Earliest ISO-8601 timestamp across every host-metric series in the
    extraction. ISO Zulu strings sort lexically — no parsing needed. Returns
    None when the extraction has no host data at all."""
    best = None
    def check(host):
        nonlocal best
        for s in (host or {}).values():
            if not s:
                continue
            t = s[0][0]
            if best is None or t < best:
                best = t
    for node in extraction.get("nodes") or []:
        check((node.get("data") or {}).get("host"))
    for shard in (extraction.get("shards") or {}).values():
        for node in shard:
            check((node.get("data") or {}).get("host"))
    for router in extraction.get("routers") or []:
        check((router.get("data") or {}).get("host"))
    return best


def trim_disks_in_place(extraction, start):
    """Trim disk-partition series in-place to points at/after `start`.
    `start` is the ISO-8601 timestamp returned by `earliest_host_timestamp`;
    `None` is a no-op. Mutates the extraction dict so every downstream reader
    (including per-node and overlay renderers) sees the trimmed series."""
    if not start:
        return
    def trim(nodes):
        for n in nodes:
            disks = (n.get("data") or {}).get("disks") or {}
            for metrics in disks.values():
                for metric, series in list(metrics.items()):
                    metrics[metric] = [p for p in (series or []) if p[0] >= start]
    trim(extraction.get("nodes") or [])
    for shard in (extraction.get("shards") or {}).values():
        trim(shard)
    trim(extraction.get("routers") or [])


# ---------------------------------------------------------------------------
# Derived memory series via SystemMemoryMetrics
# ---------------------------------------------------------------------------

def synthesize_memory_series(entries, total_memory_gb):
    """Attach two derived host series per entry, both via SystemMemoryMetrics:
      - MEMORY_USED_PERCENTAGE: 100 * used / tier_ceiling
      - MEMORY_USED_BYTES:      the raw used series, normalized to bytes via
                                Series.as_bytes() (so KB → B happens in one
                                place, not sprinkled through the viewer).
    Mutates entries in place; idempotent. Silent when the tier ceiling is
    unknown or SYSTEM_MEMORY_USED is missing — the derived charts just omit
    the trace for that entry."""
    if not total_memory_gb or total_memory_gb <= 0:
        return
    for _, data in entries:
        host = data.get("host") or {}
        if "MEMORY_USED_PERCENTAGE" in host and "MEMORY_USED_BYTES" in host:
            continue
        if not host.get("SYSTEM_MEMORY_USED"):
            continue
        try:
            mem = SystemMemoryMetrics.create_from_json(
                host_json=host, total_memory_gb=total_memory_gb,
            )
        except ValueError:
            continue
        if mem.used_percentage.points:
            host["MEMORY_USED_PERCENTAGE"] = list(mem.used_percentage.points)
        if mem.used.points:
            host["MEMORY_USED_BYTES"] = list(mem.used.points)
        data["host"] = host


def synthesize_search_memory_series(entries, total_memory_gb):
    """Search-side analogue of `synthesize_memory_series`. Attaches the two
    derived host series each Search Node tile needs, via SearchMemoryMetrics
    against the mongot process's resident memory:
      - MEMORY_USED_PERCENTAGE: 100 * resident / tier_ceiling
      - MEMORY_USED_BYTES:      the resident series in canonical bytes
    Keys match the mongod synthesizer so the per-node renderer doesn't need
    to branch by section type — the chart title "Memory Used" reads as
    "resident memory" in the Atlas Search section header context. Mutates
    entries in place; idempotent. Silent when the ceiling is unknown or
    FTS_PROCESS_RESIDENT_MEMORY is missing."""
    if not total_memory_gb or total_memory_gb <= 0:
        return
    for _, data in entries:
        host = data.get("host") or {}
        if "MEMORY_USED_PERCENTAGE" in host and "MEMORY_USED_BYTES" in host:
            continue
        if not host.get("FTS_PROCESS_RESIDENT_MEMORY"):
            continue
        try:
            mem = SearchMemoryMetrics.create_from_json(
                host_json=host, total_memory_gb=total_memory_gb,
            )
        except ValueError:
            continue
        if mem.resident_percentage.points:
            host["MEMORY_USED_PERCENTAGE"] = list(mem.resident_percentage.points)
        if mem.resident.points:
            host["MEMORY_USED_BYTES"] = list(mem.resident.points)
        data["host"] = host
