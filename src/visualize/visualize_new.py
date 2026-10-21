#!/usr/bin/env python3
"""
Per-node memory + CPU + disk view — a focused companion to visualize_old.py's
overlay dashboard.

Each section renders, in order:
  - CPU chart grid(s) — multi-trace tiles (User / Kernel / IOWait / … or
    Read / Write) with P5/P50/P95 overlays per trace,
  - the memory chart grid (Memory Used % with P5/P50/P95 overlays),
  - disk chart grids (IOPS, Latency, Throughput, Space Used %) for every
    partition under `data.disks`, same multi-trace + overlay treatment.
Tiles sit in a 2–3 column responsive grid. A sticky top navbar toggles
individual nodes, and each section carries a P5 / P50 / P95 button group
that governs the overlay lines on every tile (CPU, memory, disk).

Other extraction data (cache, connections, hardware panel) is intentionally
skipped — this view stays scoped to the primary rightsizing signals. See
visualize_old.py for the full dashboard.

CLI:
  python src/visualize/visualize_new.py --extraction <path/to/extraction.json>
                                        [--out <path/to/visualization_new.html>]
                                        [--no-open]
"""

import argparse
import html
import json
import os
import sys
import webbrowser

import plotly.graph_objects as go
import plotly.io as pio

# Reach the shared src/ modules. Append (not insert) so an unrelated top-level
# `common` doesn't shadow the extraction package when both are on sys.path.
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from common.cache_activity import CacheActivity  # noqa: E402
from common.cache_ratio_metrics import CacheRatioMetrics  # noqa: E402
from common.cpu_normalized_metrics import CPUNormalizedMetrics  # noqa: E402
from common.disk_iops_metrics import DiskIopsMetrics  # noqa: E402
from common.disk_latency_metrics import DiskLatencyMetrics  # noqa: E402
from common.disk_size_metrics import DiskSizeMetrics  # noqa: E402
from common.disk_throughput_metrics import DiskThroughputMetrics  # noqa: E402
from common.queues import Queues  # noqa: E402
from common.search_cpu_normalized_metrics import SearchCPUNormalizedMetrics  # noqa: E402
from common.series import Series  # noqa: E402
from common.tickets_available_metrics import TicketsAvailableMetrics  # noqa: E402
from shared import (  # noqa: E402
    BYTES_PER_GB,
    PALETTE,
    collect_mongod_sections,
    collect_search_sections,
    earliest_host_timestamp,
    primary_region_memory_gb,
    primary_region_provisioned_iops,
    primary_region_provisioned_throughput,
    scale_bytes_unit,
    search_memory_gb,
    series_to_xy,
    synthesize_memory_series,
    synthesize_search_memory_series,
    trim_disks_in_place,
)


# The only memory metric this view renders — the absolute-bytes companion
# was dropped because the percentage already answers "how close to the
# ceiling", which is what rightsizing needs.
_MEMORY_METRICS = ("MEMORY_USED_PERCENTAGE",)

_METRIC_DISPLAY = {
    "MEMORY_USED_PERCENTAGE": "Memory Used %",
}

_METRIC_UNIT = {
    "MEMORY_USED_PERCENTAGE": "%",
}


# ---------------------------------------------------------------------------
# Per-node figure construction
# ---------------------------------------------------------------------------

def _node_figure(metric_name, node_label, series, color, total_memory_gb):
    """Build one single-trace figure for one node × one memory metric.

    The y-axis is capped at the tier memory ceiling (for MEMORY_USED_BYTES)
    or 100% (for MEMORY_USED_PERCENTAGE) so each tile tells the same
    "how close to the ceiling" story at a glance. Stats overlay (p5/p50/
    p95) renders on both metrics via Series.stats(), with `meta.stat`
    marking each line so the section-level toggle buttons can address
    them without a name-regex hack.
    """
    fig = go.Figure()
    unit = _METRIC_UNIT[metric_name]

    # Memory-bytes gets a tier-ceiling y-max; percentage caps at 100.
    ceiling_bytes = (
        total_memory_gb * BYTES_PER_GB
        if metric_name == "MEMORY_USED_BYTES" and total_memory_gb
        else None
    )
    scale, y_label = scale_bytes_unit(
        traces=[(node_label, series)], unit=unit, extra_max=ceiling_bytes,
    )

    xs, ys = series_to_xy(series)
    if scale != 1:
        ys = [v / scale if v is not None else None for v in ys]

    if xs:
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", name=node_label,
            line={"color": color}, showlegend=False,
            meta={"stat": None},
        ))
        # Stats overlay: feed the already-scaled points through Series.stats()
        # so the horizontal lines land on the same y-axis the trace sits on.
        stats = Series.from_raw(name=metric_name, raw=list(zip(xs, ys))).stats()
        if stats is not None:
            x_bounds = [xs[0], xs[-1]]
            for stat_name, stat_val, dash in (
                ("p5",  stats.p5,  "dot"),
                ("p50", stats.p50, "dashdot"),
                ("p95", stats.p95, "dash"),
            ):
                fig.add_trace(go.Scatter(
                    x=x_bounds, y=[stat_val, stat_val],
                    mode="lines",
                    name=f"{stat_name}={stat_val:g}",
                    line={"color": color, "dash": dash, "width": 1},
                    showlegend=False,
                    hoverinfo="name",
                    meta={"stat": stat_name},
                ))

    fig.update_layout(
        title={"text": _display_title(node_label=node_label),
               "font": {"size": 11}},
        xaxis_title=None,
        yaxis_title=y_label or None,
        height=320,
        margin={"l": 50, "r": 10, "t": 32, "b": 36},
        showlegend=False,
    )
    if ceiling_bytes is not None:
        fig.update_yaxes(range=[0, ceiling_bytes / scale])
    elif metric_name == "MEMORY_USED_PERCENTAGE":
        fig.update_yaxes(range=[0, 100])
    return fig


# ---------------------------------------------------------------------------
# Per-node CPU figure + builders
# ---------------------------------------------------------------------------

def _display_title(node_label):
    """Drop the shard-name prefix (`{shard} / {host:port} (ROLE)` → `{host:port}
    (ROLE)`) when rendering a per-node tile's title. The full label with
    the prefix is still used for `data-node` and the navbar — those need
    to stay globally unique in case the same host:port appears under
    multiple shards — but inside a section the prefix is just noise
    (every tile in a shard carries the same one)."""
    if " / " in node_label:
        return node_label.split(" / ", 1)[-1]
    return node_label


def _node_multi_trace_figure(node_label, trace_specs, unit="%", y_max=None,
                             y_max_label=None):
    """Generalized multi-trace per-node tile. `trace_specs` is a list of
    (trace_name, Series) tuples; one scatter line is emitted per entry,
    colors drawn from PALETTE in order so a given role (User / Kernel /
    Read / Write / …) uses the same color across every tile in a grid.

    `unit` controls both the y-axis label and auto-scaling. For "bytes" or
    "bytes/sec" the figure's own max is piped through `scale_bytes_unit`
    (1024-based) so a 5 GiB/sec throughput chart reads "5 GB/sec" instead
    of raw bytes; the ys are divided by the scale factor to match.

    `y_max` caps the y-axis. Set 100 for per-core-normalized percentages
    and for DISK_PARTITION_SPACE_PERCENT_USED; leave None for raw rates
    (IOPS, latency ms, throughput bytes/sec, raw Search CPU).

    Each trace carries P5/P50/P95 horizontal overlays (dot / dashdot /
    dash, same color as the trace) tagged with `meta.stat` so the
    section-level P95 / P50 / P5 buttons hide them without a name hack."""
    # Include y_max in the max-value hunt so a tall ceiling (e.g. a 1.5 GiB/sec
    # NVMe throughput cap against a trace that only reaches a few MB/sec)
    # picks a scale that fits BOTH the data and the ceiling. Without this,
    # the hline would land in a different unit than the trace and look
    # orders of magnitude off.
    scale, display_unit = scale_bytes_unit(
        traces=[(name, series.points if series else [])
                for name, series in trace_specs],
        unit=unit,
        extra_max=y_max,
    )
    fig = go.Figure()
    for (name, series), color in zip(trace_specs, PALETTE):
        xs, ys = series_to_xy(series=series.points if series else [])
        if scale != 1:
            ys = [v / scale if v is not None else None for v in ys]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", name=name,
            line={"color": color},
            hovertemplate=f"{name}: %{{y:.2f}} {display_unit}<extra></extra>",
            legendgroup=name,
            meta={"stat": None},
        ))
        if not xs:
            continue
        stats = Series.from_raw(name=name, raw=list(zip(xs, ys))).stats()
        if stats is None:
            continue
        x_bounds = [xs[0], xs[-1]]
        for stat_name, stat_val, dash in (
            ("p5",  stats.p5,  "dot"),
            ("p50", stats.p50, "dashdot"),
            ("p95", stats.p95, "dash"),
        ):
            fig.add_trace(go.Scatter(
                x=x_bounds, y=[stat_val, stat_val],
                mode="lines",
                name=f"{name} {stat_name}={stat_val:g}",
                line={"color": color, "dash": dash, "width": 1},
                showlegend=False,
                hoverinfo="name",
                legendgroup=name,
                meta={"stat": stat_name},
            ))
    fig.update_layout(
        title={"text": _display_title(node_label=node_label),
               "font": {"size": 11}},
        xaxis_title=None,
        yaxis_title=display_unit,
        height=320,
        margin={"l": 50, "r": 10, "t": 32, "b": 36},
        showlegend=False,
    )
    # y_max is in the raw metric unit (bytes/sec, /sec, ms, %). The axis
    # draws the SCALED values, so divide by `scale` before setting the
    # range + hline — otherwise a bytes/sec ceiling would land miles off
    # a KB/MB/GB-scaled axis.
    y_max_scaled = y_max / scale if y_max is not None else None
    if y_max_scaled is not None:
        fig.update_yaxes(range=[0, y_max_scaled])
    if y_max_scaled is not None and y_max_label:
        # Visible ceiling line (e.g. provisioned IOPS, max throughput). Red
        # dashed so it stands out from the trace colors and the P5/P50/P95
        # dashes. Annotation sits just under the line on the right so it
        # doesn't collide with the tile title centered at the top.
        if scale != 1:
            # Byte-scaled axis — show the ceiling in the scaled unit for
            # legibility (e.g. "Max Throughput: 1.50 GB/sec" vs raw bytes).
            annot = f"{y_max_label}: {y_max_scaled:,.2f} {display_unit}"
        else:
            annot = f"{y_max_label}: {y_max:,}"
        fig.add_hline(
            y=y_max_scaled,
            line_color="#c0392b", line_dash="dash", line_width=1,
            annotation_text=annot,
            annotation_position="bottom right",
            annotation_font_size=10,
            annotation_font_color="#c0392b",
        )
    return fig


def _grid_legend_html(trace_names):
    """Static HTML legend for one chart grid (CPU or Disk), rendered once
    per grid instead of once per tile. Each item is a colored swatch +
    trace name; colors track PALETTE in the same order
    `_node_multi_trace_figure` zips through, so the grid legend matches
    every tile's line colors exactly."""
    items = []
    for name, color in zip(trace_names, PALETTE):
        items.append(
            f'<span class="legend-item">'
            f'<span class="swatch" style="background:{color}"></span>'
            f'{html.escape(name)}'
            f'</span>'
        )
    return f'<div class="chart-legend">{"".join(items)}</div>'


def _mongod_cpu_builder(host):
    """Return a list of (chart_title, trace_specs, y_max) for a mongod/mongos
    host. Builds a single `CPU %` chart with the traces that drive the CPU
    bottleneck verdict: User, Kernel, their timestamp-aligned sum
    (User+Kernel — the signal CPURightsizing evaluates against the up/down
    thresholds), IOWait (disk-bound indicator), and IRQ. Nice / SoftIRQ /
    Steal / Guest are omitted — low signal for rightsizing on Atlas hosts.
    y_max=100 — these are per-core normalized percentages, so sibling
    tiles share one visual scale and saturation reads at a glance.
    Returns [] if the CPU family is missing (host silently skips its
    CPU grid rather than erroring)."""
    try:
        cpu = CPUNormalizedMetrics.create_from_json(host_json=host)
    except ValueError:
        return []
    return [(
        "CPU %",
        [
            ("User",          cpu.user),
            ("Kernel",        cpu.kernel),
            ("User + Kernel", cpu.user_plus_kernel()),
            ("IOWait",        cpu.iowait),
            ("IRQ",           cpu.irq),
        ],
        100,
    )]


def _search_cpu_builder(host):
    """Return a list of (chart_title, trace_specs, y_max) for a Search
    (mongot) host. Two charts, both capped at 100% so sibling tiles share
    a visual scale and saturation reads at a glance:
      - raw process CPU% — Atlas emits this as a per-core value, so it
        stays in [0, 100] in practice (sum across cores is tracked by the
        Normalized variant). Clip anything above 100 to the ceiling.
      - per-core normalized CPU% — divided by vCPU count, bounded [0, 100]."""
    try:
        scpu = SearchCPUNormalizedMetrics.create_from_json(host_json=host)
    except ValueError:
        return []
    return [
        ("CPU %",
         [("User", scpu.cpu_user), ("Kernel", scpu.cpu_kernel)],
         100),
        ("Normalized CPU %",
         [("User", scpu.normalized_cpu_user),
          ("Kernel", scpu.normalized_cpu_kernel)],
         100),
    ]


def _mongod_disk_builder(data, iops_cap=None, throughput_cap=None):
    """Return [(chart_title, trace_specs, y_max, unit, y_max_label), ...]
    for every partition in `data.disks`. Four chart families per partition
    — IOPS, Latency, Throughput, Space Used %. mongos routers carry an
    empty `disks: {}`, so this returns [] for them and the section emits
    no disk grids. Individual families are silently skipped (and the
    others still render) when a partition is missing that family's
    primary metric.

    `iops_cap` is the provisioned-IOPS ceiling (same across every node in
    the cluster, computed once per extraction via
    `primary_region_provisioned_iops`). When supplied, it locks the Disk
    IOPS chart's y-axis AND draws a labeled dashed line at that value so
    the ceiling is a visible reference, not just an implicit top. None
    lets the IOPS axis auto-range with no reference line.

    `throughput_cap` plays the same role for the Disk Throughput chart,
    computed via `primary_region_provisioned_throughput`. Expressed in
    BYTES_PER_SECOND so the figure's `scale_bytes_unit` auto-scales it
    along with the trace values (chart shows e.g. "MB/sec" / "GB/sec").

    The 5-tuple's `y_max_label` is only set on IOPS and Throughput (the
    other two families either have no natural ceiling or use the axis top
    tacitly, like Space Used % at 100)."""
    disks = (data or {}).get("disks") or {}
    out = []
    for partition in sorted(disks):
        pj = disks[partition] or {}
        # Only suffix the chart title with the partition name when the
        # node has more than one — persona has exactly one named "data"
        # and the suffix would be noise.
        suffix = f" — {partition}" if len(disks) > 1 else ""
        try:
            iops = DiskIopsMetrics.create_from_json(
                partition_json=pj, provisioned_iops=iops_cap,
            )
            out.append((
                f"Disk IOPS{suffix}",
                [("Read", iops.read), ("Write", iops.write)],
                iops_cap, "/sec",
                "Provisioned IOPS" if iops_cap else None,
            ))
            # Only render the % tile when we actually have a ceiling to
            # divide by — otherwise used_percentage is an empty series
            # and the tile would be blank.
            if iops_cap:
                out.append((
                    f"Disk IOPS %{suffix}",
                    [("Used %", iops.used_percentage)],
                    100, "%", None,
                ))
        except ValueError:
            pass
        try:
            lat = DiskLatencyMetrics.create_from_json(partition_json=pj)
            out.append((
                f"Disk Latency{suffix}",
                [("Read", lat.read), ("Write", lat.write)],
                None, "ms", None,
            ))
        except ValueError:
            pass
        try:
            thr = DiskThroughputMetrics.create_from_json(partition_json=pj)
            out.append((
                f"Disk Throughput{suffix}",
                [("Read", thr.read), ("Write", thr.write)],
                throughput_cap, "bytes/sec",
                "Max Throughput" if throughput_cap else None,
            ))
        except ValueError:
            pass
        try:
            sz = DiskSizeMetrics.create_from_json(partition_json=pj)
            out.append((
                f"Disk Space Used %{suffix}",
                [("Space Used", sz.space_percent_used)],
                100, "%", None,
            ))
        except ValueError:
            pass
    return out


def _search_disk_builder(data):
    """Search Nodes carry no `data.disks` key; this always returns [] so
    the Atlas Search section has no disk grids."""
    return []


def _mongod_engine_builder(host):
    """Return [(chart_title, trace_specs, y_max, unit, y_max_label), ...]
    for the WT / server-engine grids. All four families (cache I/O, cache
    fill, WT tickets, global-lock queues) are mongod-only — mongos routers
    and Search Nodes don't emit any of them. Missing families are silently
    skipped via try/except, so hosts without a given family just render
    one fewer grid. Return shape matches the disk builder's 5-tuple so
    `_section_html` reuses the same render loop verbatim."""
    out = []
    try:
        ca = CacheActivity.create_from_json(host_json=host)
        out.append((
            "Cache I/O",
            [("Read Into", ca.bytes_read_into),
             ("Written From", ca.bytes_written_from)],
            None, "bytes/sec", None,
        ))
    except ValueError:
        pass
    try:
        cr = CacheRatioMetrics.create_from_json(host_json=host)
        out.append((
            "Cache Fill %",
            [("Fill", cr.fill_ratio),
             ("Dirty Fill", cr.dirty_fill_ratio)],
            100, "%", None,
        ))
    except ValueError:
        pass
    try:
        tk = TicketsAvailableMetrics.create_from_json(host_json=host)
        out.append((
            "WT Tickets Available",
            [("Reads Available", tk.reads_available),
             ("Writes Available", tk.writes_available)],
            None, "count", None,
        ))
    except ValueError:
        pass
    try:
        q = Queues.create_from_json(host_json=host)
        out.append((
            "Global Lock Queue",
            [("Readers", q.queue_readers),
             ("Writers", q.queue_writers)],
            None, "count", None,
        ))
    except ValueError:
        pass
    return out


def _search_engine_builder(host):
    """Search Nodes don't emit any WT / lock-queue / ticket metrics; this
    always returns [] so the Atlas Search section has no engine grids."""
    return []


# ---------------------------------------------------------------------------
# Section HTML assembly
# ---------------------------------------------------------------------------

def _slugify(s):
    import re
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _section_html(section_name, entries, total_memory_gb,
                  synthesizer, cpu_builder, disk_builder, engine_builder):
    """One section = one section header with a stats toggle, then CPU chart
    grids, then the memory chart grid, then disk grids, then engine grids
    (WT cache / tickets / global-lock queues). Each grid holds N per-node
    tiles.

    `synthesizer` populates the MEMORY_USED_* host keys this view renders
    (mongod sections pass `synthesize_memory_series`; Search sections pass
    `synthesize_search_memory_series`). `cpu_builder` takes a host dict and
    returns a list of (chart_title, trace_specs, y_max) for the CPU grids.
    `disk_builder` takes the full `data` dict (needs `data.disks`) and
    `engine_builder` takes a host dict; both return the 5-tuple
    (chart_title, trace_specs, y_max, unit, y_max_label) that the shared
    `_node_multi_trace_figure` understands. One builder of each type per
    section type.

    Returns (html_fragment, node_labels_ordered). Empty sections (nothing
    to plot) return ("", [])."""
    if not entries:
        return "", []
    # Mutates entries' host dicts in place with MEMORY_USED_PERCENTAGE +
    # MEMORY_USED_BYTES.
    synthesizer(entries=entries, total_memory_gb=total_memory_gb)

    # Preserve a stable node palette (same color per node across every metric
    # grid) and remember which nodes actually had any renderable data —
    # memory, CPU, or any disk partition is enough to count the node as
    # "live". Each live entry carries the full `data` dict so the downstream
    # disk loop can reach `data.disks` without re-looking it up by label.
    live_entries = []
    for i, (label, data) in enumerate(entries):
        host = (data or {}).get("host") or {}
        disks = (data or {}).get("disks") or {}
        has_memory = bool(host.get("MEMORY_USED_PERCENTAGE") or host.get("MEMORY_USED_BYTES"))
        has_cpu = bool(host.get("SYSTEM_NORMALIZED_CPU_USER") or host.get("FTS_PROCESS_CPU_USER"))
        has_disk = bool(disks)
        has_engine = bool(host.get("CACHE_BYTES_READ_INTO") or host.get("TICKETS_AVAILABLE_READS"))
        if has_memory or has_cpu or has_disk or has_engine:
            live_entries.append((i, label, host, data))
    if not live_entries:
        return "", []

    slug = _slugify(section_name)
    parts = [
        f'<section data-section="{slug}">',
        '  <div class="section-header">',
        f'    <h2>{html.escape(section_name)}</h2>',
        '    <div class="stats-toggle">',
        '      <button type="button" data-stat="p95" class="active">P95</button>',
        '      <button type="button" data-stat="p50" class="active">P50</button>',
        '      <button type="button" data-stat="p5"  class="active">P5</button>',
        '    </div>',
        '  </div>',
    ]
    node_labels_ordered = [label for _, label, _, _ in live_entries]

    # ---- CPU grids first ----
    # Pre-compute each live entry's chart list once (dataclass instantiation
    # inside the builder); discover (title, y_max) + their count from the
    # first entry that produced any charts, so later entries line up
    # positionally. Each builder entry is (chart_title, trace_specs, y_max).
    per_entry_cpu = {}
    cpu_chart_specs = []  # list of (title, y_max) in order
    for _, label, host, _ in live_entries:
        charts = cpu_builder(host=host)
        per_entry_cpu[label] = charts
        if charts and not cpu_chart_specs:
            cpu_chart_specs = [(title, y_max) for title, _, y_max in charts]

    for idx, (title, y_max) in enumerate(cpu_chart_specs):
        # Trace names come from the first entry that actually produced this
        # chart (any entry has the same shape — the builder is deterministic
        # from the dataclass — but gracefully skip entries that returned [])
        trace_names = []
        for _, label, _, _ in live_entries:
            charts = per_entry_cpu.get(label) or []
            if idx < len(charts):
                trace_names = [name for name, _ in charts[idx][1]]
                break
        parts.append(f'  <h3>{html.escape(title)}</h3>')
        parts.append('  ' + _grid_legend_html(trace_names=trace_names))
        parts.append(f'  <div class="chart-grid grid" data-metric="cpu-{idx}">')
        for _, label, _, _ in live_entries:
            charts = per_entry_cpu.get(label) or []
            if idx >= len(charts):
                continue
            _, trace_specs, _ = charts[idx]
            fig = _node_multi_trace_figure(
                node_label=label, trace_specs=trace_specs,
                unit="%", y_max=y_max,
            )
            fragment = pio.to_html(fig, include_plotlyjs=False, full_html=False)
            parts.append(
                f'    <div class="fig" data-node="{html.escape(label)}">{fragment}</div>'
            )
        parts.append('  </div>')

    # ---- Memory grids ----
    for metric in _MEMORY_METRICS:
        parts.append(f'  <h3>{html.escape(_METRIC_DISPLAY[metric])}</h3>')
        parts.append(f'  <div class="chart-grid grid" data-metric="{html.escape(metric)}">')
        for palette_idx, label, host, _ in live_entries:
            series = host.get(metric)
            if not series:
                continue
            color = PALETTE[palette_idx % len(PALETTE)]
            fig = _node_figure(
                metric_name=metric, node_label=label,
                series=series, color=color, total_memory_gb=total_memory_gb,
            )
            fragment = pio.to_html(fig, include_plotlyjs=False, full_html=False)
            parts.append(
                f'    <div class="fig" data-node="{html.escape(label)}">{fragment}</div>'
            )
        parts.append('  </div>')

    # ---- Disk grids last ----
    # Builder entry shape differs from CPU's: 5-tuple
    # (title, trace_specs, y_max, unit, y_max_label). Disk spans several
    # units (/sec, ms, bytes/sec, %) in one section, and the IOPS tile
    # draws a visible provisioned-IOPS ceiling line via `y_max_label`;
    # the other three families leave y_max_label=None.
    per_entry_disk = {}
    disk_chart_specs = []  # list of (title, y_max, unit, y_max_label) in order
    for _, label, _, data in live_entries:
        charts = disk_builder(data=data)
        per_entry_disk[label] = charts
        if charts and not disk_chart_specs:
            disk_chart_specs = [(title, y_max, unit, y_max_label)
                                for title, _, y_max, unit, y_max_label in charts]

    for idx, (title, y_max, unit, y_max_label) in enumerate(disk_chart_specs):
        trace_names = []
        for _, label, _, _ in live_entries:
            charts = per_entry_disk.get(label) or []
            if idx < len(charts):
                trace_names = [name for name, _ in charts[idx][1]]
                break
        parts.append(f'  <h3>{html.escape(title)}</h3>')
        parts.append('  ' + _grid_legend_html(trace_names=trace_names))
        parts.append(f'  <div class="chart-grid grid" data-metric="disk-{idx}">')
        for _, label, _, _ in live_entries:
            charts = per_entry_disk.get(label) or []
            if idx >= len(charts):
                continue
            _, trace_specs, _, _, _ = charts[idx]
            fig = _node_multi_trace_figure(
                node_label=label, trace_specs=trace_specs,
                unit=unit, y_max=y_max, y_max_label=y_max_label,
            )
            fragment = pio.to_html(fig, include_plotlyjs=False, full_html=False)
            parts.append(
                f'    <div class="fig" data-node="{html.escape(label)}">{fragment}</div>'
            )
        parts.append('  </div>')

    # ---- Engine grids last ----
    # Shape matches the disk builder (5-tuple), so this loop is a mirror
    # of the one above — only the input source differs (engine_builder
    # reads `host`, disk_builder reads `data`).
    per_entry_engine = {}
    engine_chart_specs = []  # list of (title, y_max, unit, y_max_label) in order
    for _, label, host, _ in live_entries:
        charts = engine_builder(host=host)
        per_entry_engine[label] = charts
        if charts and not engine_chart_specs:
            engine_chart_specs = [(title, y_max, unit, y_max_label)
                                  for title, _, y_max, unit, y_max_label in charts]

    for idx, (title, y_max, unit, y_max_label) in enumerate(engine_chart_specs):
        trace_names = []
        for _, label, _, _ in live_entries:
            charts = per_entry_engine.get(label) or []
            if idx < len(charts):
                trace_names = [name for name, _ in charts[idx][1]]
                break
        parts.append(f'  <h3>{html.escape(title)}</h3>')
        parts.append('  ' + _grid_legend_html(trace_names=trace_names))
        parts.append(f'  <div class="chart-grid grid" data-metric="engine-{idx}">')
        for _, label, _, _ in live_entries:
            charts = per_entry_engine.get(label) or []
            if idx >= len(charts):
                continue
            _, trace_specs, _, _, _ = charts[idx]
            fig = _node_multi_trace_figure(
                node_label=label, trace_specs=trace_specs,
                unit=unit, y_max=y_max, y_max_label=y_max_label,
            )
            fragment = pio.to_html(fig, include_plotlyjs=False, full_html=False)
            parts.append(
                f'    <div class="fig" data-node="{html.escape(label)}">{fragment}</div>'
            )
        parts.append('  </div>')
    parts.append('</section>')
    return "\n".join(parts), node_labels_ordered


# ---------------------------------------------------------------------------
# HTML page template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 0; color: #222; background: #fafbfc; }}
    header.page-header {{ padding: 16px 24px 10px; background: #fff;
                          border-bottom: 1px solid #ddd; }}
    header.page-header h1 {{ margin: 0 0 4px; font-size: 18px; }}
    header.page-header .meta {{ color: #666; font-size: 13px; }}
    nav.node-nav {{ position: sticky; top: 0; z-index: 20; background: #fff;
                    border-bottom: 1px solid #ddd; padding: 10px 24px;
                    display: flex; flex-wrap: wrap; gap: 6px 14px;
                    align-items: center; font-size: 13px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.04); }}
    nav.node-nav strong {{ font-weight: 600; color: #333; }}
    nav.node-nav label {{ display: inline-flex; align-items: center;
                          gap: 4px; cursor: pointer; padding: 2px 6px;
                          border-radius: 3px; }}
    nav.node-nav label:hover {{ background: #f0f3f8; }}
    nav.node-nav input[type=checkbox] {{ margin: 0; }}
    nav.node-nav .nav-bulk {{ padding: 3px 10px; border: 1px solid #bbb;
                              border-radius: 3px; background: #fff;
                              cursor: pointer; font-size: 12px; }}
    nav.node-nav .nav-bulk:hover {{ background: #f0f3f8; }}
    main {{ padding: 20px 24px 40px; }}
    section {{ margin-bottom: 32px; background: #fff; border: 1px solid #e3e6ea;
               border-radius: 6px; padding: 18px 20px 24px; }}
    section .section-header {{ display: flex; justify-content: space-between;
                               align-items: center; gap: 16px; margin-bottom: 4px; }}
    section .section-header h2 {{ margin: 0; font-size: 16px; }}
    section h3 {{ margin: 20px 0 8px; font-size: 14px; color: #444;
                  font-weight: 600; }}
    .chart-legend {{ display: flex; flex-wrap: wrap; gap: 6px 16px;
                     margin: 0 0 10px; font-size: 12px; color: #555; }}
    .chart-legend .legend-item {{ display: inline-flex; align-items: center;
                                   gap: 6px; }}
    .chart-legend .swatch {{ display: inline-block; width: 16px; height: 3px;
                             background: #000; border-radius: 1px; }}
    .stats-toggle {{ display: inline-flex; gap: 0;
                     border: 1px solid #bbb; border-radius: 4px; overflow: hidden; }}
    .stats-toggle button {{ padding: 4px 12px; border: 0; background: #fff;
                            cursor: pointer; border-right: 1px solid #ddd;
                            font-size: 12px; }}
    .stats-toggle button:last-child {{ border-right: 0; }}
    .stats-toggle button.active {{ background: #4a79c7; color: #fff; }}
    .chart-grid {{ display: block; }}
    .chart-grid.grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
                        gap: 10px 14px; }}
    .fig {{ min-width: 0; background: #fff; }}
    @media (max-width: 1100px) {{
      .chart-grid.grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 720px) {{
      .chart-grid.grid {{ grid-template-columns: 1fr; }}
    }}
    .empty {{ color: #888; font-style: italic; }}
  </style>
</head>
<body>
<header class="page-header">
  <h1>{title}</h1>
  <div class="meta">{meta}</div>
</header>
<nav class="node-nav" aria-label="Node visibility">
  <strong>Nodes:</strong>
  {node_checkboxes}
  <button type="button" class="nav-bulk" data-action="all">all</button>
  <button type="button" class="nav-bulk" data-action="none">none</button>
</nav>
<main>
{body}
</main>
<script>
(function() {{
  // Persistence stores the HIDDEN node set — anything not in the saved
  // list defaults to visible. That way nodes added in a later extraction
  // (e.g. a Search Node section appearing after a tier catalog update)
  // show up by default instead of being silently hidden because the old
  // saved VISIBLE list didn't know about them. Key renamed from
  // '…per-node-visible' so users with the old visible-set JSON get a
  // clean start rather than inverted semantics.
  const NODE_KEY = 'rightsize-viz-per-node-hidden';
  const STAT_KEY = 'rightsize-viz-stat-visibility';

  // -------- node visibility --------
  const nodeChecks = document.querySelectorAll('nav.node-nav input[type=checkbox]');
  function applyNodeState(label, visible) {{
    document.querySelectorAll('.fig[data-node="' + CSS.escape(label) + '"]').forEach(f => {{
      f.style.display = visible ? '' : 'none';
    }});
  }}
  function saveNodes() {{
    const hidden = [];
    nodeChecks.forEach(cb => {{ if (!cb.checked) hidden.push(cb.dataset.node); }});
    try {{ localStorage.setItem(NODE_KEY, JSON.stringify(hidden)); }} catch (e) {{}}
    // Plotly reads parent width on first render; nudge survivors to re-measure.
    requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
  }}
  nodeChecks.forEach(cb => {{
    cb.addEventListener('change', () => {{
      applyNodeState(cb.dataset.node, cb.checked);
      saveNodes();
    }});
  }});
  document.querySelectorAll('nav.node-nav .nav-bulk').forEach(btn => {{
    btn.addEventListener('click', () => {{
      const target = btn.dataset.action === 'all';
      nodeChecks.forEach(cb => {{
        if (cb.checked !== target) {{
          cb.checked = target;
          applyNodeState(cb.dataset.node, target);
        }}
      }});
      saveNodes();
    }});
  }});
  // Restore saved node visibility: only explicitly-hidden nodes get
  // hidden on load; everything else (including nodes new since last
  // visit) stays visible.
  try {{
    const saved = JSON.parse(localStorage.getItem(NODE_KEY) || 'null');
    if (Array.isArray(saved)) {{
      const hiddenSet = new Set(saved);
      nodeChecks.forEach(cb => {{
        if (hiddenSet.has(cb.dataset.node)) {{
          cb.checked = false;
          applyNodeState(cb.dataset.node, false);
        }}
      }});
    }}
  }} catch (e) {{}}

  // -------- stats overlay toggle (per section, applied globally via localStorage) --------
  // Trace's `meta.stat` is set to "p5" / "p50" / "p95" for the overlay lines,
  // and `null` for the main data trace (see _node_figure in visualize_new.py).
  const statState = {{ p5: true, p50: true, p95: true }};
  try {{
    const saved = JSON.parse(localStorage.getItem(STAT_KEY) || 'null');
    if (saved && typeof saved === 'object') Object.assign(statState, saved);
  }} catch (e) {{}}

  function visFromMeta(meta) {{
    const stat = meta && meta.stat;
    if (!stat) return true;  // main data trace — always visible
    return statState[stat] === false ? 'legendonly' : true;
  }}
  function applyStats() {{
    document.querySelectorAll('.js-plotly-plot').forEach(p => {{
      const vis = (p.data || []).map(t => visFromMeta(t.meta));
      if (window.Plotly) Plotly.restyle(p, {{visible: vis}});
    }});
    try {{ localStorage.setItem(STAT_KEY, JSON.stringify(statState)); }} catch (e) {{}}
  }}

  document.querySelectorAll('.stats-toggle button').forEach(btn => {{
    const stat = btn.dataset.stat;
    btn.classList.toggle('active', statState[stat] !== false);
    btn.addEventListener('click', () => {{
      statState[stat] = !statState[stat];
      // Keep every same-named button in sync across sections (global state).
      document.querySelectorAll('.stats-toggle button[data-stat="' + stat + '"]').forEach(b => {{
        b.classList.toggle('active', statState[stat]);
      }});
      applyStats();
    }});
  }});
  // Apply any saved stat state on load (after Plotly has mounted the figures).
  applyStats();
}})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def visualize(extraction_path, out=None, open_browser=True):
    """Render extraction.json → per-node memory HTML; return the output path.

    `out` defaults to visualization_new.html next to the input."""
    with open(extraction_path, encoding="utf-8") as f:
        extraction = json.load(f)

    # Disk-partition series come from a wider fetch (extraction.disk_days,
    # default 60 — see src/config.yaml) than host metrics (default_days, 7).
    # Trim them to the host window so disk tiles share an x-axis with the
    # CPU and memory tiles instead of showing 60 days of IOPS against 7
    # days of everything else.
    trim_disks_in_place(extraction=extraction,
                        start=earliest_host_timestamp(extraction=extraction))

    mongod_mem_gb = primary_region_memory_gb(extraction=extraction)
    search_mem_gb = search_memory_gb(extraction=extraction)
    mongod_iops_cap = primary_region_provisioned_iops(extraction=extraction)
    mongod_throughput_cap = primary_region_provisioned_throughput(extraction=extraction)

    body_parts = []
    all_node_labels = []  # unique, in render order
    seen = set()

    def record_nodes(labels):
        for lbl in labels:
            if lbl not in seen:
                seen.add(lbl)
                all_node_labels.append(lbl)

    # Pre-bind the provisioned-IOPS + provisioned-throughput ceilings onto
    # the mongod disk builder so `_section_html` can keep its
    # builder-takes-just-data contract.
    def _bound_mongod_disk_builder(data):
        return _mongod_disk_builder(data=data, iops_cap=mongod_iops_cap,
                                    throughput_cap=mongod_throughput_cap)

    for section_name, entries in collect_mongod_sections(extraction=extraction).items():
        frag, labels = _section_html(
            section_name=section_name, entries=entries,
            total_memory_gb=mongod_mem_gb,
            synthesizer=synthesize_memory_series,
            cpu_builder=_mongod_cpu_builder,
            disk_builder=_bound_mongod_disk_builder,
            engine_builder=_mongod_engine_builder,
        )
        if frag:
            body_parts.append(frag)
            record_nodes(labels)

    for section_name, entries in collect_search_sections(
        search=extraction.get("search") or {}
    ).items():
        frag, labels = _section_html(
            section_name=section_name, entries=entries,
            total_memory_gb=search_mem_gb,
            synthesizer=synthesize_search_memory_series,
            cpu_builder=_search_cpu_builder,
            disk_builder=_search_disk_builder,
            engine_builder=_search_engine_builder,
        )
        if frag:
            body_parts.append(frag)
            record_nodes(labels)

    if not body_parts:
        body_parts.append(
            '<p class="empty">No memory or CPU data available for this '
            'extraction (tier catalog may be missing the instance size, or '
            'the host-level metrics are absent).</p>'
        )

    node_checkboxes = "\n  ".join(
        f'<label><input type="checkbox" data-node="{html.escape(lbl)}" checked> '
        f'{html.escape(_display_title(node_label=lbl))}</label>'
        for lbl in all_node_labels
    )

    cluster = extraction.get("cluster", "unknown")
    project = extraction.get("project_name") or extraction.get("project_id") or ""
    ctype = extraction.get("type", "unknown")
    tiers = ", ".join(((extraction.get("config") or {}).get("tiers") or [])) or "unknown"
    meta_bits = [f"type: <code>{html.escape(ctype)}</code>",
                 f"tier: {html.escape(tiers)}"]
    if project:
        meta_bits.insert(0, f"project: {html.escape(project)}")
    if mongod_mem_gb:
        meta_bits.append(f"mongod ceiling: {mongod_mem_gb} GB")
    if search_mem_gb:
        meta_bits.append(f"search ceiling: {search_mem_gb} GB")
    if mongod_iops_cap:
        meta_bits.append(f"disk IOPS ceiling: {mongod_iops_cap:,}/sec")
    if mongod_throughput_cap:
        _mib = 1024 * 1024
        meta_bits.append(f"disk throughput ceiling: {mongod_throughput_cap / _mib:,.0f} MiB/sec")

    html_text = _HTML_TEMPLATE.format(
        title=html.escape(f"{cluster} - per-node memory + CPU + disk"),
        meta=" | ".join(meta_bits),
        node_checkboxes=node_checkboxes,
        body="\n".join(body_parts),
    )

    out_path = out or os.path.join(
        os.path.dirname(os.path.abspath(extraction_path)) or ".",
        "visualization_new.html",
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    if open_browser:
        webbrowser.open(f"file://{os.path.abspath(out_path)}")
    return out_path


def console_main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--extraction", required=True,
                    help="Path to extraction.json (from src/extraction/)")
    ap.add_argument("--out", default=None,
                    help="Output HTML path (default: visualization_new.html next to --extraction)")
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
