#!/usr/bin/env python3
"""
Render an extraction.json as an interactive Plotly HTML dashboard.

One Plotly figure per metric; every node is a separate trace on the same
figure, so a hot primary stands out next to its idle secondaries. Click a
legend entry to hide/show a trace. Shift-click or box-select to zoom; the
chart toolbar in the top-right also exposes pan / reset.

CLI:
  python src/visualize/visualize.py --extraction <path/to/extraction.json>
                                    [--out <path/to/visualization.html>]
                                    [--no-open]

Default --out: visualization.html next to the input extraction.json
(parallel to how rightsize.py places rightsizing.md).
"""

import argparse
import html
import json
import os
import re
import sys
import webbrowser

import plotly.colors
import plotly.graph_objects as go
import plotly.io as pio

# Reach the shared src/ modules (atlas_tier_spec, constants.*). Append rather
# than insert so an unrelated top-level `common` doesn't shadow the extraction
# package when both are on sys.path.
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from atlas_tier_spec import load_tier_spec  # noqa: E402
from common.series import Series  # noqa: E402
from common.system_memory_metrics import SystemMemoryMetrics  # noqa: E402
from constants.atlas_mongo_metrics import ALL_METRICS as _MONGO_METRICS  # noqa: E402
from constants.atlas_mongos_metrics import ALL_METRICS as _MONGOS_METRICS  # noqa: E402
from constants.atlas_search_metrics import ALL_METRICS as _SEARCH_METRICS  # noqa: E402


# ---------------------------------------------------------------------------
# Metric → unit resolution
# ---------------------------------------------------------------------------
#
# The authoritative per-metric unit map comes from constants/atlas_*_metrics.py
# (verified against live Atlas responses — see the comment at the top of
# atlas_mongo_metrics.py). The visualizer only needs:
#   - a y-axis display label ("%", "bytes", "ms", ...)
#   - a raw-to-bytes multiplier for byte-family units (so KB/MB-reported
#     metrics get normalized before _scale_bytes_unit picks GB/TB)
# so we translate the Atlas DataMetricUnits enum through two lookup tables
# rather than carrying the full name through the render pipeline.

# Atlas emits mongod, mongos, and FTS/search metrics across three endpoints.
# Merge their unit maps so one lookup covers every metric the extractor can
# produce. Last-wins is fine because the overlapping metric names (CONNECTIONS,
# SYSTEM_*, etc.) carry the same units in every catalog.
_ATLAS_METRIC_UNITS = {**_MONGO_METRICS, **_MONGOS_METRICS, **_SEARCH_METRICS}

_ATLAS_UNIT_TO_DISPLAY = {
    "PERCENT":              "%",
    "SCALAR":               "count",
    "SCALAR_PER_SECOND":    "/sec",
    "MILLISECONDS":         "ms",
    "BYTES":                "bytes",
    "KILOBYTES":            "bytes",
    "MEGABYTES":            "bytes",
    "GIGABYTES":            "bytes",
    "BYTES_PER_SECOND":     "bytes/sec",
    "KILOBYTES_PER_SECOND": "bytes/sec",
    "MEGABYTES_PER_SECOND": "bytes/sec",
}

_ATLAS_UNIT_TO_BYTES = {
    "BYTES":                1,
    "KILOBYTES":            1024,
    "MEGABYTES":            1024 ** 2,
    "GIGABYTES":            1024 ** 3,
    "BYTES_PER_SECOND":     1,
    "KILOBYTES_PER_SECOND": 1024,
    "MEGABYTES_PER_SECOND": 1024 ** 2,
}

# Fallback patterns for derived / local-only metrics the Atlas catalog
# doesn't know about (currently just the MEMORY_USED_PERCENTAGE series
# synthesized by _synthesize_memory_percent via SystemMemoryMetrics).
_UNIT_PATTERNS = [
    (re.compile(r"^MEMORY_USED_PERCENTAGE$"), "%"),
    (re.compile(r"^MEMORY_USED_BYTES$"),      "bytes"),
]


def _unit_for(metric_name):
    """Y-axis label. Consults the authoritative atlas_*_metrics unit catalog
    first; falls back to the local _UNIT_PATTERNS for synthesized metrics
    that aren't in the catalog. Unknown metrics render without a label."""
    atlas_unit = _ATLAS_METRIC_UNITS.get(metric_name)
    if atlas_unit:
        return _ATLAS_UNIT_TO_DISPLAY.get(atlas_unit, "")
    for pattern, unit in _UNIT_PATTERNS:
        if pattern.search(metric_name):
            return unit
    return ""


def _raw_to_bytes(metric_name):
    """Multiplier that converts the raw API value to canonical bytes.
    Returns 1 for non-byte metrics or for anything the Atlas catalog
    doesn't know, so the raw value passes through unchanged."""
    atlas_unit = _ATLAS_METRIC_UNITS.get(metric_name)
    return _ATLAS_UNIT_TO_BYTES.get(atlas_unit, 1)


_BYTE_UNITS = {"bytes", "bytes/sec"}
_BYTE_SCALES = (
    (1024 ** 4, "TB"),
    (1024 ** 3, "GB"),
    (1024 ** 2, "MB"),
    (1024,      "KB"),
)

# Fixed palette so each trace's horizontal p5/p50/p95 overlay (see
# `_STATS_OVERLAY_METRICS` + stats loop in `_metric_figure`) can match the
# trace's own color — Plotly's auto color cycle would otherwise assign the
# overlay lines colors from later in the cycle, breaking the visual link.
_PALETTE = plotly.colors.qualitative.Plotly

# Metrics that get a per-trace horizontal p5/p50/p95 overlay. Scoped
# narrowly today (just MEMORY_USED_PERCENTAGE — the chart the evaluator's
# memory trigger reasons about) because overlays double or quadruple
# trace count and would clutter charts where percentiles aren't the main
# question.
_STATS_OVERLAY_METRICS = frozenset({"MEMORY_USED_PERCENTAGE"})

# Human-friendly chart titles for metrics whose SCREAMING_SNAKE_CASE API
# name would read as noise in the UI. The raw API name stays as the dict
# key everywhere (host dicts, priority map, _STATS_OVERLAY_METRICS,
# data-metric attributes in JS); this map only overrides what the viewer
# sees in the chart title and the right-side chart-visibility panel.
_METRIC_DISPLAY_NAMES = {
    "MEMORY_USED_PERCENTAGE": "Memory Used %",
    "MEMORY_USED_BYTES":      "Memory Used",
}


def _display_name(metric_name):
    return _METRIC_DISPLAY_NAMES.get(metric_name, metric_name)


def _scale_bytes_unit(traces, unit, extra_max=None):
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
    if unit not in _BYTE_UNITS:
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
    for threshold, label in _BYTE_SCALES:
        if max_val >= threshold:
            return threshold, f"{label}{suffix}"
    return 1, unit


# ---------------------------------------------------------------------------
# Flattening the three extraction shapes into (section, trace_label, data) tuples
# ---------------------------------------------------------------------------

def _short_role(role):
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


def _trace_label(base, role):
    """`buildkite-runner-shard-00-00:27017` + REPLICA_PRIMARY ->
    `buildkite-runner-shard-00-00:27017 (PRIMARY)`."""
    short = _short_role(role)
    return f"{base} ({short})" if short else base


def _synthesize_memory_series(entries, total_memory_gb):
    """Attach two derived host series per entry, both via SystemMemoryMetrics:
      - MEMORY_USED_PERCENTAGE: 100 * used / tier_ceiling
      - MEMORY_USED_BYTES:      the raw used series, normalized to bytes via
                                Series.as_bytes() (so KB → B happens in one
                                place, not sprinkled through the viewer).
    Mutates entries in place; idempotent. Silent when the tier ceiling is
    unknown or SYSTEM_MEMORY_USED is missing — the raw hidden metrics
    would then show nothing and the derived charts just omit the trace."""
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


def _collect_mongod_sections(extraction):
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
            (_trace_label(base=n.get("label") or "unknown", role=n.get("role")),
             n.get("data") or {})
            for n in extraction.get("nodes") or []
        ]
    elif t == "sharded":
        compute = []
        for rs_name, nodes in sorted((extraction.get("shards") or {}).items()):
            for n in nodes:
                base = f"{rs_name} / {n.get('label') or 'unknown'}"
                compute.append((_trace_label(base=base, role=n.get("role")),
                                n.get("data") or {}))
        if compute:
            sections["Compute nodes (all shards)"] = compute
        routers = extraction.get("routers") or []
        if routers:
            sections["mongos routers"] = [
                (_trace_label(base=n.get("label") or "unknown", role=n.get("role")),
                 n.get("data") or {})
                for n in routers
            ]
    return sections


def _collect_search_sections(search):
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
# Figure construction
# ---------------------------------------------------------------------------

def _series_to_xy(series):
    """[(iso_ts, v), ...] -> (xs, ys). Plotly renders ISO 8601 strings as datetime."""
    if not series:
        return [], []
    xs, ys = [], []
    for ts, v in series:
        xs.append(ts)
        ys.append(v)
    return xs, ys


#: Bytes per gibibyte — used to turn tier memory_gb into a y-axis ceiling
#: in canonical bytes. 1024**3 (binary) matches _BYTE_SCALES so the ceiling
#: lands at a round "16 GB" tick on a 16 GiB tier.
_BYTES_PER_GB = 1024 ** 3


def _metric_figure(metric_name, traces, include_empty=False, total_memory_gb=None):
    """One go.Figure. `traces` = list of (label, series). Empty series are
    skipped by default; pass include_empty=True to still add a labeled trace
    (useful for sections where "no data" is itself the signal — e.g. FTS on
    mongod when dedicated Search Nodes handle all queries).

    Bytes-based y-axes are auto-scaled per figure to KB/MB/GB/TB based on
    the figure's max value (see _scale_bytes_unit) so a 5 GiB memory
    series reads as `5` instead of `5e9`. A per-metric pre-multiplier
    (via _raw_to_bytes, driven by the atlas_*_metrics unit catalog)
    normalizes raw-API values that aren't actually bytes (SYSTEM_MEMORY_*
    is KILOBYTES, MEMORY_RESIDENT/VIRTUAL/MAPPED is MEGABYTES, etc.) to
    canonical bytes before auto-scaling runs.

    `total_memory_gb` is the tier's physical memory ceiling, used only
    for the memory charts: it caps the y-axis at the ceiling for
    MEMORY_USED_BYTES (so headroom is visible at a glance) and
    participates in scale selection so a 16 GiB ceiling on 10 GiB data
    still picks GB. MEMORY_USED_PERCENTAGE caps at 100 regardless. Pass
    None for metrics that don't want a tier-aware ceiling (all non-memory
    metrics; also memory charts in sections where the tier didn't
    resolve)."""
    fig = go.Figure()
    unit = _unit_for(metric_name)
    pre_mul = _raw_to_bytes(metric_name) if unit in _BYTE_UNITS else 1
    if pre_mul != 1:
        traces = [
            (label, [(ts, v * pre_mul if v is not None else None)
                     for ts, v in (series or [])])
            for label, series in traces
        ]
    # Ceiling in canonical bytes; only applied to the memory-bytes chart.
    ceiling_bytes = (
        total_memory_gb * _BYTES_PER_GB
        if total_memory_gb and metric_name == "MEMORY_USED_BYTES"
        else None
    )
    scale, unit = _scale_bytes_unit(traces=traces, unit=unit, extra_max=ceiling_bytes)
    show_stats = metric_name in _STATS_OVERLAY_METRICS
    # Precompute x-range once so each stat overlay spans the full chart
    # width even if an individual trace covers a shorter sub-window.
    if show_stats:
        all_ts = [p[0] for _, s in traces for p in (s or [])]
        x_bounds = [min(all_ts), max(all_ts)] if all_ts else None
    else:
        x_bounds = None
    for i, (label, series) in enumerate(traces):
        color = _PALETTE[i % len(_PALETTE)]
        xs, ys = _series_to_xy(series)
        if scale != 1:
            ys = [v / scale if v is not None else None for v in ys]
        if not xs:
            if include_empty:
                fig.add_trace(go.Scatter(x=[], y=[], mode="lines", name=label,
                                         line={"color": color}, legendgroup=label))
            continue
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=label,
                                 line={"color": color}, legendgroup=label))
        if show_stats and x_bounds:
            # Route through Series.stats() so the chart's percentile labels
            # come from the same code path the evaluator uses (DescriptiveStats
            # — p5/p50/p95/min/max/n). Wrap the already-scaled points so the
            # horizontal line hits the same y-axis the trace sits on.
            stats = Series.from_raw(name=metric_name, raw=list(zip(xs, ys))).stats()
            if stats is None:
                continue
            for stat_name, stat_val, dash in (
                ("p5",  stats.p5,  "dot"),
                ("p50", stats.p50, "dashdot"),
                ("p95", stats.p95, "dash"),
            ):
                fig.add_trace(go.Scatter(
                    x=x_bounds, y=[stat_val, stat_val],
                    mode="lines",
                    name=f"{label} {stat_name}={stat_val:g}",
                    line={"color": color, "dash": dash, "width": 1},
                    legendgroup=label,
                    showlegend=True,
                    hoverinfo="name",
                ))
    # Default layout = stacked view: legend on the right so long hostnames
    # don't overlap the time axis. The grid-view toggle swaps to a bottom
    # legend via Plotly.relayout (see view-toggle JS in the HTML template)
    # because grid cells are too narrow for a right-side legend.
    fig.update_layout(
        title=_display_name(metric_name),
        xaxis_title="time",
        yaxis_title=unit or None,
        height=380,
        margin={"l": 60, "r": 20, "t": 50, "b": 50},
        legend={"orientation": "v", "yanchor": "top", "y": 1, "xanchor": "left", "x": 1.02},
    )
    # Lock the y-axis top to the tier memory ceiling / 100% so headroom
    # is obvious. Applied after update_layout so update_yaxes wins.
    if ceiling_bytes is not None:
        fig.update_yaxes(range=[0, ceiling_bytes / scale])
    elif metric_name == "MEMORY_USED_PERCENTAGE":
        fig.update_yaxes(range=[0, 100])
    return fig


#: Raw system-memory series the user explicitly asked us to hide — the
#: derived MEMORY_USED_PERCENTAGE chart (computed by SystemMemoryMetrics
#: against the physical tier ceiling) tells the whole story and the raw
#: bytes series would clutter the memory group. If you need to inspect
#: the raw signals ad-hoc, drop a name from this set.
_HIDDEN_HOST_METRICS = frozenset({
    "SYSTEM_MEMORY_USED",
    "SYSTEM_MEMORY_FREE",
    "SYSTEM_MEMORY_AVAILABLE",
    "SYSTEM_MEMORY_BUFFERS",
    "SYSTEM_MEMORY_CACHED",
    "SYSTEM_MEMORY_SHARED",
})


def _collect_metric_names(entries, scope):
    """Union of metric names across entries, with `_HIDDEN_HOST_METRICS`
    filtered out when scope=="host". `scope` is "host" or a partition name
    under "disks"."""
    names = set()
    for _, data in entries:
        if scope == "host":
            names.update((data.get("host") or {}).keys())
        else:
            names.update(((data.get("disks") or {}).get(scope) or {}).keys())
    if scope == "host":
        names -= _HIDDEN_HOST_METRICS
    # Preserve a stable, roughly-grouped order.
    priority = {
        # Memory first — the user wants these at the top of each host section
        # both on the page and in the right-side chart-visibility panel
        # (which mirrors page order).
        "MEMORY_USED_PERCENTAGE": -2, "MEMORY_USED_BYTES": -1,
        "SYSTEM_NORMALIZED_CPU_USER": 0, "SYSTEM_NORMALIZED_CPU_KERNEL": 1,
        "SYSTEM_NORMALIZED_CPU_IOWAIT": 2,
        "CONNECTIONS": 20,
        "GLOBAL_LOCK_CURRENT_QUEUE_READERS": 30, "GLOBAL_LOCK_CURRENT_QUEUE_WRITERS": 31,
        "TICKETS_AVAILABLE_READS": 32, "TICKETS_AVAILABLE_WRITE": 33,
        "OP_EXECUTION_TIME_READS": 40, "OP_EXECUTION_TIME_WRITES": 41,
        "EXTRA_INFO_PAGE_FAULTS": 50,
        "CACHE_BYTES_READ_INTO": 51, "CACHE_BYTES_WRITTEN_FROM": 52,
        "CACHE_FILL_RATIO": 60, "DIRTY_FILL_RATIO": 61,
        "CACHE_PRESSURE_PERCENTAGE": 62,
        "SYSTEM_NETWORK_IN": 70, "SYSTEM_NETWORK_OUT": 71,
        "DISK_PARTITION_IOPS_READ": 100, "DISK_PARTITION_IOPS_WRITE": 101,
        "DISK_PARTITION_LATENCY_READ": 110, "DISK_PARTITION_LATENCY_WRITE": 111,
        "DISK_PARTITION_THROUGHPUT_READ": 120, "DISK_PARTITION_THROUGHPUT_WRITE": 121,
        "DISK_PARTITION_SPACE_PERCENT_USED": 130,
        "DISK_PARTITION_SPACE_USED": 131, "DISK_PARTITION_SPACE_FREE": 132,
    }
    return sorted(names, key=lambda n: (priority.get(n, 999), n))


def _section_figures(entries, scope, include_empty=False, total_memory_gb=None):
    """Build one figure per metric in `entries`. Returns [(metric_name, fig), ...].
    When include_empty=True, metrics with no data in any node still render
    (empty chart + legend of nodes), useful for the FTS section where the
    absence of data is itself what the user wants to see.

    `total_memory_gb` is forwarded to `_metric_figure` so the memory
    charts (MEMORY_USED_BYTES, MEMORY_USED_PERCENTAGE) can lock their
    y-axis top to the tier ceiling."""
    out = []
    for metric in _collect_metric_names(entries=entries, scope=scope):
        traces = []
        for label, data in entries:
            if scope == "host":
                series = (data.get("host") or {}).get(metric)
            else:
                series = ((data.get("disks") or {}).get(scope) or {}).get(metric)
            traces.append((label, series))
        fig = _metric_figure(metric_name=metric, traces=traces,
                             include_empty=include_empty,
                             total_memory_gb=total_memory_gb)
        if fig.data or include_empty:
            out.append((metric, fig))
    return out


def _disk_partitions(entries):
    """All partition names seen across the entries."""
    parts = set()
    for _, data in entries:
        parts.update((data.get("disks") or {}).keys())
    return sorted(parts)


def _earliest_host_timestamp(extraction):
    """Earliest ISO-8601 timestamp across every host-metric series in the
    extraction. ISO Zulu strings sort lexically — no parsing needed."""
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


def _trim_disks_in_place(extraction, start):
    """Trim disk-partition series in-place to points at/after `start`.

    Disks are extracted over a wider window (extraction.disk_days, default
    60) than host metrics (default 7). Trimming here aligns the x-axis of
    disk charts with host charts so the viewer sees the same 7-day slice
    the evaluator uses, instead of 60 days of disk against 7 of host."""
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
# Tier spec resolution — delegates to the shared atlas_tier_spec module so
# the viz, extractor, and evaluator all read the same catalog.
# ---------------------------------------------------------------------------

def _resolve_tier_spec(provider, instance_size, generation, cls):
    """Load the TierSpec for one region via the shared atlas_tier_spec
    module (which drives extract.py's _resolve_tier_specs). Returns a plain
    dict so the _fmt_* helpers that render the hardware panel don't need to
    know about the dataclass. Empty dict on lookup failure — the hardware
    panel will render '-' in the affected columns."""
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


def _primary_region_memory_gb(extraction):
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
    spec = _resolve_tier_spec(
        provider=r.get("provider"), instance_size=r.get("instance_size"),
        generation=r.get("generation"), cls=r.get("class"),
    )
    return spec.get("memory_gb")


def _search_memory_gb(extraction):
    """Physical memory ceiling (GB) for dedicated Atlas Search Nodes, from
    `search.specs[0]`. Search Nodes run on their own tier (often different
    from the mongod shards), so the mongod memory ceiling would misrepresent
    their used%. Returns None when there are no dedicated Search Node specs
    or the lookup fails."""
    specs = ((extraction.get("search") or {}).get("specs") or [])
    if not specs:
        return None
    s = specs[0]
    spec = _resolve_tier_spec(
        provider=s.get("cloud_provider"), instance_size=s.get("instance_size"),
        generation=s.get("generation"), cls=s.get("class"),
    )
    return spec.get("memory_gb")


def _tier_iops_range(spec):
    """Tier-allowed IOPS range as a display string, or None if unknown."""
    lo, hi = spec.get("disk_iops_min"), spec.get("disk_iops_max")
    if lo is not None and hi is not None:
        return f"{lo:,}-{hi:,}" if lo != hi else f"{lo:,}"
    single = spec.get("max_disk_iops")
    if single is not None:
        return f"{single:,}"
    return None


def _tier_storage_range(spec):
    """Tier-allowed storage range as a display string, or None if unknown."""
    lo, hi = spec.get("storage_min_gb"), spec.get("storage_max_gb")
    ext = spec.get("extended_storage_max_gb")
    if lo is None and hi is None:
        return None
    base = f"{lo}-{hi} GB" if lo != hi else f"{lo} GB"
    return f"{base} (ext {ext} GB)" if ext else base


def _derive_gcp_iops(disk_size_gb, spec):
    """GCP doesn't expose a provisioned diskIOPS; the IOPS cap is derived
    from the storage size. Atlas's default storage class on GCP is PD-SSD,
    which gives 30 IOPS/GB (read and write) with a per-tier floor and
    cap taken from the tier catalog. Returns None when the inputs are
    insufficient to compute."""
    if disk_size_gb is None:
        return None
    lo = spec.get("disk_iops_min")
    hi = spec.get("disk_iops_max")
    computed = int(disk_size_gb) * 30
    if lo is not None:
        computed = max(computed, lo)
    if hi is not None:
        computed = min(computed, hi)
    return computed


def _fmt_iops_cell(provisioned, spec, provider=None, disk_size_gb=None):
    """Configured IOPS big, tier range as subtext. For GCP (no provisioned
    diskIOPS), derive from disk size using the GCP PD-SSD formula clamped
    to the tier catalog range. Falls back to the tier range when no
    computation is possible; '-' when neither is known."""
    tier_range = _tier_iops_range(spec)
    if provisioned is None and (provider or "").upper() == "GCP":
        provisioned = _derive_gcp_iops(disk_size_gb=disk_size_gb, spec=spec)
    if provisioned is not None:
        provisioned_display = f"{provisioned:,}"
        if tier_range and tier_range != provisioned_display:
            return (f"<strong>{provisioned_display}</strong>"
                    f'<br><span style="color:#777;font-size:12px">tier: {tier_range}</span>')
        return f"<strong>{provisioned_display}</strong>"
    return tier_range or "-"


def _fmt_storage_cell(disk_size_gb, spec):
    tier_range = _tier_storage_range(spec)
    if disk_size_gb is not None:
        provisioned_display = f"{disk_size_gb:g} GB"
        if tier_range and tier_range != provisioned_display:
            return (f"<strong>{provisioned_display}</strong>"
                    f'<br><span style="color:#777;font-size:12px">tier: {tier_range}</span>')
        return f"<strong>{provisioned_display}</strong>"
    return tier_range or "-"


def _fmt_memory(spec):
    mem = spec.get("memory_gb")
    return f"{mem} GB" if mem is not None else "-"


def _fmt(value, suffix=""):
    return f"{value}{suffix}" if value is not None else "-"


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 24px; margin-right: 304px; color: #222; }}
    header {{ border-bottom: 1px solid #ccc; padding-bottom: 12px; margin-bottom: 20px; }}
    header h1 {{ margin: 0 0 4px; font-size: 20px; }}
    header .meta {{ color: #666; font-size: 13px; }}
    nav {{ margin: 16px 0; font-size: 13px; }}
    nav a {{ margin-right: 14px; }}
    h2 {{ margin-top: 36px; padding-top: 8px; border-top: 1px solid #eee; }}
    h3 {{ margin-top: 24px; color: #444; font-size: 15px; }}
    .fig {{ margin: 10px 0 24px; min-width: 0; }}
    .empty {{ color: #888; font-style: italic; }}
    .section-note {{ margin: 0 0 12px; padding: 8px 12px; background: #f3f6fb;
                     border-left: 3px solid #4a79c7; font-size: 13px; color: #334; }}
    table.hw {{ border-collapse: collapse; font-size: 13px; margin: 4px 0 12px; }}
    table.hw th, table.hw td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left;
                                vertical-align: top; }}
    table.hw th {{ background: #f6f6f6; font-weight: 600; }}
    table.hw tr:nth-child(even) td {{ background: #fafafa; }}
    .hw-note {{ color: #777; font-size: 12px; margin: -4px 0 12px; }}
    .view-toggle {{ display: inline-flex; gap: 0; margin: 8px 0 4px;
                    border: 1px solid #bbb; border-radius: 4px; overflow: hidden;
                    font-size: 13px; }}
    .view-toggle button {{ padding: 6px 14px; border: 0; background: #fff; cursor: pointer;
                           border-right: 1px solid #ddd; }}
    .view-toggle button:last-child {{ border-right: 0; }}
    .view-toggle button.active {{ background: #4a79c7; color: #fff; }}
    .chart-grid {{ display: block; }}
    .chart-grid.grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
                        gap: 12px 16px; }}
    .chart-grid.grid .fig {{ margin: 0; }}
    @media (max-width: 1100px) {{
      .chart-grid.grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 720px) {{
      .chart-grid.grid {{ grid-template-columns: 1fr; }}
    }}
    .role-toggle {{ display: inline-flex; gap: 6px; margin-left: 16px; vertical-align: top; }}
    .role-toggle button {{ padding: 6px 12px; border: 1px solid #bbb; border-radius: 4px;
                           background: #fff; cursor: pointer; font-size: 13px; }}
    .role-toggle button.active {{ background: #4a79c7; color: #fff; border-color: #4a79c7; }}
    .right-panel {{ position: fixed; right: 0; top: 0; bottom: 0; width: 280px;
                    background: #f8f9fb; border-left: 1px solid #ddd;
                    overflow-y: auto; padding: 16px 14px; font-size: 13px; z-index: 10; }}
    .right-panel h2 {{ margin: 0 0 12px; font-size: 15px; padding: 0; border: 0; }}
    .right-panel h3 {{ margin: 14px 0 4px; font-size: 13px; color: #333; font-weight: 600;
                       border-bottom: 1px solid #ddd; padding-bottom: 2px; }}
    .right-panel label {{ display: block; padding: 2px 0; cursor: pointer; color: #333; }}
    .right-panel input[type=checkbox] {{ margin-right: 6px; vertical-align: middle; }}
    .right-panel .section-bulk {{ font-size: 11px; color: #666; margin-left: 20px;
                                  cursor: pointer; text-decoration: underline; }}
    .right-panel .section-bulk + .section-bulk {{ margin-left: 8px; }}
  </style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="meta">{meta}</div>
</header>
<nav>{nav}</nav>
<div class="view-toggle" role="group" aria-label="Chart layout">
  <button type="button" data-view="stacked" class="active">Stacked</button>
  <button type="button" data-view="grid">Grid 3x</button>
</div>
<div class="role-toggle" role="group" aria-label="Node role visibility"></div>
{body}
<aside class="right-panel" aria-label="Chart visibility">
  <h2>Charts</h2>
  <div id="chart-toggles"></div>
</aside>
<script>
(function() {{
  // --- layout toggle (stacked / grid) ---
  const buttons = document.querySelectorAll('.view-toggle button');
  const grids = document.querySelectorAll('.chart-grid');
  const STORAGE_KEY = 'rightsize-viz-layout';
  // Legend position swaps with view: right-side when stacked (long hostnames
  // need room), bottom when grid (cells too narrow for a side legend).
  const LEGEND_STACKED = {{"orientation": "v", "yanchor": "top", "y": 1, "xanchor": "left", "x": 1.02}};
  const LEGEND_GRID = {{"orientation": "h", "yanchor": "bottom", "y": -0.35, "xanchor": "left", "x": 0}};
  function applyLayout(view) {{
    grids.forEach(g => g.classList.toggle('grid', view === 'grid'));
    buttons.forEach(b => b.classList.toggle('active', b.dataset.view === view));
    const legend = view === 'grid' ? LEGEND_GRID : LEGEND_STACKED;
    if (window.Plotly) {{
      document.querySelectorAll('.js-plotly-plot').forEach(p => {{
        Plotly.relayout(p, {{legend: legend}});
      }});
    }}
    // Plotly reads the parent width on first render; resize after re-flow.
    requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
  }}
  buttons.forEach(b => b.addEventListener('click', () => {{
    const view = b.dataset.view;
    try {{ localStorage.setItem(STORAGE_KEY, view); }} catch (e) {{}}
    applyLayout(view);
  }}));
  let initial = 'stacked';
  try {{
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'grid' || saved === 'stacked') initial = saved;
  }} catch (e) {{}}
  applyLayout(initial);

  // --- role toggle (PRIMARY / SECONDARY / MONGOS / ...) ---
  // Trace names end in "(ROLE)" — see _trace_label() in visualize.py.
  const roleRe = /\\(([A-Z_]+)\\)\\s*$/;
  const plots = () => Array.from(document.querySelectorAll('.js-plotly-plot'));
  const uniqueRoles = () => {{
    const r = new Set();
    plots().forEach(p => (p.data || []).forEach(t => {{
      const m = roleRe.exec(t.name || '');
      if (m) r.add(m[1]);
    }}));
    return Array.from(r).sort();
  }};
  const roleState = {{}};
  const roleContainer = document.querySelector('.role-toggle');
  uniqueRoles().forEach(role => {{
    roleState[role] = true;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = role;
    btn.classList.add('active');
    btn.addEventListener('click', () => {{
      roleState[role] = !roleState[role];
      btn.classList.toggle('active', roleState[role]);
      plots().forEach(p => {{
        const vis = (p.data || []).map(t => {{
          const m = roleRe.exec(t.name || '');
          const r = m ? m[1] : null;
          return r && roleState[r] === false ? 'legendonly' : true;
        }});
        if (window.Plotly) Plotly.restyle(p, {{visible: vis}});
      }});
    }});
    roleContainer.appendChild(btn);
  }});

  // --- right-panel chart visibility toggles ---
  const panel = document.getElementById('chart-toggles');
  document.querySelectorAll('.chart-grid').forEach(grid => {{
    // Find the preceding h2 for this grid's section title.
    let h = grid.previousElementSibling;
    while (h && h.tagName !== 'H2') h = h.previousElementSibling;
    const sectionTitle = h ? h.textContent : 'Charts';
    const figs = grid.querySelectorAll('.fig');
    if (!figs.length) return;
    const header = document.createElement('h3');
    header.textContent = sectionTitle;
    panel.appendChild(header);

    const bulkWrap = document.createElement('div');
    const makeBulk = (label, checked) => {{
      const a = document.createElement('a');
      a.href = '#';
      a.textContent = label;
      a.className = 'section-bulk';
      a.addEventListener('click', (ev) => {{
        ev.preventDefault();
        figs.forEach(f => {{
          const cb = f._toggleCb;
          if (cb && cb.checked !== checked) {{ cb.checked = checked; cb.dispatchEvent(new Event('change')); }}
        }});
      }});
      return a;
    }};
    bulkWrap.appendChild(makeBulk('all', true));
    bulkWrap.appendChild(makeBulk('none', false));
    panel.appendChild(bulkWrap);

    figs.forEach(fig => {{
      const metric = fig.dataset.metric || 'metric';
      const label = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = true;
      cb.addEventListener('change', () => {{
        fig.style.display = cb.checked ? '' : 'none';
        if (cb.checked) requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
      }});
      fig._toggleCb = cb;
      label.appendChild(cb);
      label.appendChild(document.createTextNode(' ' + metric));
      panel.appendChild(label);
    }});
  }});
}})();
</script>
</body>
</html>
"""


def _slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _search_summary(extraction):
    """Human-readable summary of the dedicated Atlas Search Node deployment,
    or None when no dedicated Search Nodes are attached. Co-located mongot
    is intentionally ignored."""
    search = extraction.get("search") or {}
    specs = (search or {}).get("specs") or []
    if not specs:
        return None
    state = search.get("state")
    parts = []
    for s in specs:
        bits = []
        if s.get("node_count"):
            bits.append(f"{s['node_count']}x")
        if s.get("instance_size"):
            bits.append(s["instance_size"])
        loc_bits = []
        if s.get("cloud_provider"):
            loc_bits.append(s["cloud_provider"])
        if s.get("region_name"):
            loc_bits.append(s["region_name"])
        if loc_bits:
            bits.append("on " + "/".join(loc_bits))
        if s.get("shard_id"):
            bits.append(f"(shard {s['shard_id']})")
        parts.append(" ".join(bits).strip())
    summary = "; ".join(parts)
    if state:
        summary += f" - state {state}"
    return summary


def _render_hardware_panel(config):
    """Table of provider / region / instance plus resolved hardware specs for
    each `config.regions[]` row. Older extractions (pre-regions[]) fall back
    to a note telling the user to re-run extraction."""
    regions = (config or {}).get("regions") or []
    disk_size_gb = (config or {}).get("disk_size_gb")
    if not regions:
        tiers = ", ".join((config or {}).get("tiers") or []) or "unknown"
        return (
            '<h2 id="cluster-hardware">Cluster hardware</h2>'
            f'<p class="section-note">tier: {html.escape(tiers)} '
            '- re-run extraction to populate per-region specs '
            '(provider, region, memory, vCPU, IOPS, storage, max connections).</p>'
        )

    rows = []
    for r in regions:
        spec = _resolve_tier_spec(
            provider=r.get("provider"), instance_size=r.get("instance_size"),
            generation=r.get("generation"), cls=r.get("class"),
        )
        bits = []
        if r.get("class"):
            bits.append(r["class"])
        if r.get("storage"):
            bits.append(r["storage"])
        if r.get("generation"):
            bits.append(r["generation"])
        detail = " / ".join(bits)
        instance_display = html.escape(r.get("instance_size") or "unknown")
        if detail:
            instance_display += f'<br><span style="color:#777;font-size:12px">{html.escape(detail)}</span>'
        provider = r.get("provider") or "-"
        if r.get("backing_provider") and r["backing_provider"] != provider:
            provider = f'{provider} (on {r["backing_provider"]})'
        # Prefer per-region disk size; the config-level value is a fallback
        # for older extractions and typically matches region 0 anyway.
        region_size = r.get("disk_size_gb") if r.get("disk_size_gb") is not None else disk_size_gb
        # Nodes cell: total + breakdown by role when there's more than one
        # kind. Older extractions (pre-breakdown) just see the total.
        total = r.get("node_count")
        parts = []
        if r.get("electable_count"):
            parts.append(f"{r['electable_count']} electable")
        if r.get("read_only_count"):
            parts.append(f"{r['read_only_count']} read-only")
        if r.get("analytics_count"):
            parts.append(f"{r['analytics_count']} analytics")
        node_cell = _fmt(total)
        if len(parts) > 1:
            node_cell += (
                f'<br><span style="color:#777;font-size:12px">'
                f'{html.escape(" + ".join(parts))}</span>'
            )
        rows.append(
            "<tr>"
            f"<td>{html.escape(provider)}</td>"
            f"<td>{html.escape(r.get('region') or '-')}</td>"
            f"<td>{instance_display}</td>"
            f"<td>{node_cell}</td>"
            f"<td>{_fmt(spec.get('vcpus'))}</td>"
            f"<td>{html.escape(_fmt_memory(spec))}</td>"
            f"<td>{_fmt_iops_cell(provisioned=r.get('disk_iops'), spec=spec, provider=r.get('provider'), disk_size_gb=region_size)}</td>"
            f"<td>{_fmt_storage_cell(disk_size_gb=region_size, spec=spec)}</td>"
            f"<td>{_fmt(spec.get('max_connections_per_node'))}</td>"
            "</tr>"
        )
    return (
        '<h2 id="cluster-hardware">Cluster hardware</h2>'
        '<table class="hw">'
        "<thead><tr>"
        "<th>Provider</th><th>Region</th><th>Instance</th><th>Nodes</th>"
        "<th>vCPUs</th><th>Memory</th><th>Disk IOPS</th><th>Storage</th>"
        "<th>Max conn/node</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def _render_html(extraction, section_figs):
    """Assemble the final HTML string from section_figs = [(section_title, [(metric, fig), ...])]."""
    cluster = extraction.get("cluster", "unknown")
    project = extraction.get("project_name") or extraction.get("project_id") or ""
    ctype = extraction.get("type", "unknown")
    config = extraction.get("config") or {}
    tiers = ", ".join(config.get("tiers") or []) or "unknown"
    meta_bits = [f"type: <code>{html.escape(ctype)}</code>",
                 f"tier: {html.escape(tiers)}"]
    if project:
        meta_bits.insert(0, f"project: {html.escape(project)}")
    search_note = _search_summary(extraction)
    if search_note:
        meta_bits.append(f"search: {html.escape(search_note)}")
    search_discovery_error = (extraction.get("search") or {}).get("search_nodes_discovery_error")

    nav_links = ['<a href="#cluster-hardware">Cluster hardware</a>']
    nav_links.extend(
        f'<a href="#{_slugify(title)}">{html.escape(title)}</a>'
        for title, figs in section_figs
    )
    nav_links = " ".join(nav_links)
    body_parts = [_render_hardware_panel(config)]
    search_note_rendered = False
    for title, figs in section_figs:
        body_parts.append(f'<h2 id="{_slugify(title)}">{html.escape(title)}</h2>')
        # Prepend the search spec summary to the first Atlas Search section so
        # readers see the tier/node_count context before the charts.
        if search_note and title.startswith("Atlas Search") and not search_note_rendered:
            body_parts.append(
                f'<p class="section-note"><strong>Dedicated Search Nodes:</strong> '
                f'{html.escape(search_note)}</p>'
            )
            # Surface the discovery error (if any) on the per-Search-Node
            # section — otherwise users see "no metrics" with no explanation.
            if search_discovery_error and "per Search Node" in title:
                body_parts.append(
                    f'<p class="section-note"><strong>Per-node metrics unavailable:</strong> '
                    f'{html.escape(search_discovery_error)}</p>'
                )
            search_note_rendered = True
        if not figs:
            body_parts.append('<p class="empty">No metrics in this section.</p>')
            continue
        body_parts.append('<div class="chart-grid">')
        for metric, fig in figs:
            fragment = pio.to_html(fig, include_plotlyjs=False, full_html=False)
            body_parts.append(
                f'<div class="fig" data-metric="{html.escape(_display_name(metric))}">{fragment}</div>'
            )
        body_parts.append('</div>')

    return _HTML_TEMPLATE.format(
        title=html.escape(f"{cluster} - metric visualization"),
        meta=" | ".join(meta_bits),
        nav=nav_links,
        body="\n".join(body_parts),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def visualize(extraction_path, out=None, open_browser=True):
    """Render extraction.json → visualization.html; return the output path."""
    with open(extraction_path, encoding="utf-8") as f:
        extraction = json.load(f)

    # Align disk charts with the host evaluation window. Extractions fetch
    # disks over `extraction.disk_days` (default 60) but evaluate against
    # the host window — show the viewer the same slice.
    _trim_disks_in_place(extraction=extraction,
                         start=_earliest_host_timestamp(extraction=extraction))

    # Resolve the mongod tier's physical memory ceiling from the extraction
    # config so SystemMemoryMetrics can compute used% against the real
    # instance total (not against used+free, which excludes buffers/cache).
    # Single-tier homogeneous clusters are the common case; mixed-region
    # or shard-specific tiers aren't attributed per-node in the extraction
    # today, so we take regions[0] and let heterogeneous clusters eat a
    # small inaccuracy rather than block the chart entirely.
    mongod_memory_gb = _primary_region_memory_gb(extraction=extraction)
    # Dedicated Search Nodes may run on a different tier (search.specs[]).
    search_memory_gb = _search_memory_gb(extraction=extraction)

    sections = []
    # --- mongod sections (replica set, or sharded + routers) ---
    for section_name, entries in _collect_mongod_sections(extraction=extraction).items():
        _synthesize_memory_series(entries=entries, total_memory_gb=mongod_memory_gb)
        host_figs = _section_figures(entries=entries, scope="host",
                                     total_memory_gb=mongod_memory_gb)
        sections.append((section_name, host_figs))
        for part in _disk_partitions(entries=entries):
            part_figs = _section_figures(entries=entries, scope=part)
            if part_figs:
                sections.append((f"{section_name} - disk partition '{part}'", part_figs))

    # --- Dedicated Search Node section (orthogonal to mongod shape) ---
    for section_name, entries in _collect_search_sections(search=extraction.get("search") or {}).items():
        _synthesize_memory_series(entries=entries, total_memory_gb=search_memory_gb)
        host_figs = _section_figures(entries=entries, scope="host",
                                     total_memory_gb=search_memory_gb)
        sections.append((section_name, host_figs))

    # --- Free-tier stub: nothing to plot ---
    if not any(figs for _, figs in sections):
        sections.append(("No measurements available", []))

    html_text = _render_html(extraction=extraction, section_figs=sections)

    out_path = out or os.path.join(
        os.path.dirname(os.path.abspath(extraction_path)) or ".",
        "visualization.html",
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    if open_browser:
        webbrowser.open(f"file://{os.path.abspath(out_path)}")
    return out_path


def console_main(argv=None):
    """CLI wrapper: parses argv and calls `visualize`."""
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--extraction", required=True,
                    help="Path to extraction.json (from src/extraction/)")
    ap.add_argument("--out", default=None,
                    help="Output HTML path (default: visualization.html next to --extraction)")
    ap.add_argument("--no-open", action="store_true",
                    help="Do not auto-open the HTML in the default browser")
    args = ap.parse_args(argv)

    try:
        path = visualize(extraction_path=args.extraction, out=args.out,
                         open_browser=not args.no_open)
    except OSError as e:
        sys.exit(f"Could not read extraction: {e}")
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in extraction: {e}")

    print(f"[written to {path}]")
    return 0


if __name__ == "__main__":
    sys.exit(console_main())
