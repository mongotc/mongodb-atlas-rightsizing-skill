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
import functools
import html
import json
import os
import re
import sys
import webbrowser

import plotly.graph_objects as go
import plotly.io as pio


# Tier catalogs live under src/constants/.
_CONSTANTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "constants"
)

# extraction config.regions[].provider (Atlas Admin API enum) -> keys used in
# the two tier catalogs. GCP = "google_cloud" in atlas_dedicated_tier_specs
# but "gcp" in the flat per-provider file name.
_PROVIDER_ALIASES = {
    "AWS":   {"file": "aws",   "catalog": "aws"},
    "GCP":   {"file": "gcp",   "catalog": "google_cloud"},
    "AZURE": {"file": "azure", "catalog": "azure"},
}


# ---------------------------------------------------------------------------
# Metric unit labels (y-axis titles). Not tunable, so inline is fine; migrate
# to src/constants/metrics.py if other callers start needing them.
# ---------------------------------------------------------------------------

_UNIT_PATTERNS = [
    (re.compile(r"^SYSTEM_NORMALIZED_CPU_"), "%"),
    (re.compile(r"^SYSTEM_MEMORY_"), "bytes"),
    (re.compile(r"^SYSTEM_NETWORK_"), "bytes/sec"),
    (re.compile(r"^CACHE_BYTES_"), "bytes/sec"),
    (re.compile(r"^DISK_PARTITION_IOPS_"), "ops/sec"),
    (re.compile(r"^DISK_PARTITION_LATENCY_"), "ms"),
    (re.compile(r"^DISK_PARTITION_THROUGHPUT_"), "bytes/sec"),
    (re.compile(r"^DISK_PARTITION_SPACE_PERCENT_USED$"), "%"),
    (re.compile(r"^DISK_PARTITION_SPACE_(USED|FREE)$"), "bytes"),
    (re.compile(r"^OP_EXECUTION_TIME_"), "ms"),
    (re.compile(r"^EXTRA_INFO_PAGE_FAULTS$"), "/sec"),
    (re.compile(r"_FILL_RATIO$"), "%"),
    (re.compile(r"^CACHE_PRESSURE_PERCENTAGE$"), "%"),
    (re.compile(r"^GLOBAL_LOCK_CURRENT_QUEUE_"), "count"),
    (re.compile(r"^TICKETS_AVAILABLE_"), "count"),
    (re.compile(r"^CONNECTIONS$"), "count"),
    (re.compile(r"^FTS_PROCESS_(NORMALIZED_)?CPU_"), "%"),
    (re.compile(r"^FTS_PROCESS_.*MEMORY$"), "bytes"),
    (re.compile(r"^FTS_DISK_USAGE$"), "bytes"),
]


def _unit_for(metric_name):
    for pattern, unit in _UNIT_PATTERNS:
        if pattern.search(metric_name):
            return unit
    return ""


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


def _metric_figure(metric_name, traces, include_empty=False):
    """One go.Figure. `traces` = list of (label, series). Empty series are
    skipped by default; pass include_empty=True to still add a labeled trace
    (useful for sections where "no data" is itself the signal — e.g. FTS on
    mongod when dedicated Search Nodes handle all queries)."""
    fig = go.Figure()
    for label, series in traces:
        xs, ys = _series_to_xy(series)
        if not xs:
            if include_empty:
                fig.add_trace(go.Scatter(x=[], y=[], mode="lines", name=label))
            continue
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=label))
    unit = _unit_for(metric_name)
    # Default layout = stacked view: legend on the right so long hostnames
    # don't overlap the time axis. The grid-view toggle swaps to a bottom
    # legend via Plotly.relayout (see view-toggle JS in the HTML template)
    # because grid cells are too narrow for a right-side legend.
    fig.update_layout(
        title=metric_name,
        xaxis_title="time",
        yaxis_title=unit or None,
        height=380,
        margin={"l": 60, "r": 20, "t": 50, "b": 50},
        legend={"orientation": "v", "yanchor": "top", "y": 1, "xanchor": "left", "x": 1.02},
    )
    return fig


def _collect_metric_names(entries, scope):
    """Union of metric names across entries. `scope` is "host" or a partition name
    under "disks"."""
    names = set()
    for _, data in entries:
        if scope == "host":
            names.update((data.get("host") or {}).keys())
        else:
            names.update(((data.get("disks") or {}).get(scope) or {}).keys())
    # Preserve a stable, roughly-grouped order.
    priority = {
        "SYSTEM_NORMALIZED_CPU_USER": 0, "SYSTEM_NORMALIZED_CPU_KERNEL": 1,
        "SYSTEM_NORMALIZED_CPU_IOWAIT": 2,
        "SYSTEM_MEMORY_USED": 10, "SYSTEM_MEMORY_FREE": 11,
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


def _section_figures(entries, scope, include_empty=False):
    """Build one figure per metric in `entries`. Returns [(metric_name, fig), ...].
    When include_empty=True, metrics with no data in any node still render
    (empty chart + legend of nodes), useful for the FTS section where the
    absence of data is itself what the user wants to see."""
    out = []
    for metric in _collect_metric_names(entries=entries, scope=scope):
        traces = []
        for label, data in entries:
            if scope == "host":
                series = (data.get("host") or {}).get(metric)
            else:
                series = ((data.get("disks") or {}).get(scope) or {}).get(metric)
            traces.append((label, series))
        fig = _metric_figure(metric_name=metric, traces=traces, include_empty=include_empty)
        if fig.data or include_empty:
            out.append((metric, fig))
    return out


def _disk_partitions(entries):
    """All partition names seen across the entries."""
    parts = set()
    for _, data in entries:
        parts.update((data.get("disks") or {}).keys())
    return sorted(parts)


# ---------------------------------------------------------------------------
# Tier spec resolution
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def _load_flat_tiers(provider_key):
    """Load src/constants/{provider_key}_tiers.json or return None if absent.
    `provider_key` is 'aws' | 'gcp' | 'azure'."""
    path = os.path.join(_CONSTANTS_DIR, f"{provider_key}_tiers.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@functools.lru_cache(maxsize=None)
def _load_dedicated_specs():
    path = os.path.join(_CONSTANTS_DIR, "atlas_dedicated_tier_specs.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _find_flat_row(flat, instance_size):
    """Look up a flat per-provider file row by hardware_spec_instance_size.
    Walks nested rows (gcp_tiers.json still has an M30 nested parent)."""
    if not flat:
        return None
    for row in flat.get("tiers", []):
        if row.get("hardware_spec_instance_size") == instance_size:
            return row
        for child in row.get("tiers", []) or []:
            if child.get("hardware_spec_instance_size") == instance_size:
                return child
    return None


def _find_catalog_row(catalog_key, base_tier, cls):
    """Fallback lookup by (cloud_provider, tier, class) in atlas_dedicated_tier_specs."""
    specs = _load_dedicated_specs()
    if not specs:
        return None
    for row in specs.get("tiers", []):
        if (row.get("cloud_provider") == catalog_key
                and row.get("tier") == base_tier
                and row.get("class") == cls):
            return row
    return None


_SPEC_FIELDS = (
    "vcpus", "memory_gb", "storage_min_gb", "storage_max_gb",
    "extended_storage_max_gb", "disk_iops_min", "disk_iops_max",
    "max_disk_iops", "max_connections_per_node", "network_performance",
)


def _resolve_tier_spec(provider, instance_size, base_tier, cls):
    """Pulled from the flat per-provider catalog first (generation-aware),
    with null fields backfilled from atlas_dedicated_tier_specs matched by
    (cloud_provider, tier, class). Returns an empty dict when neither
    catalog resolves. `_source` is 'flat' | 'catalog' | 'flat+catalog' | None."""
    alias = _PROVIDER_ALIASES.get((provider or "").upper())
    if not alias:
        return {}
    flat_row = _find_flat_row(flat=_load_flat_tiers(provider_key=alias["file"]),
                              instance_size=instance_size)
    catalog_row = _find_catalog_row(catalog_key=alias["catalog"],
                                    base_tier=base_tier, cls=cls)
    if not flat_row and not catalog_row:
        return {}
    merged = {}
    used_catalog = False
    for field in _SPEC_FIELDS:
        value = (flat_row or {}).get(field)
        if value is None and catalog_row is not None:
            value = catalog_row.get(field)
            if value is not None:
                used_catalog = True
        merged[field] = value
    if flat_row and used_catalog:
        source = "flat+catalog"
    elif flat_row:
        source = "flat"
    else:
        source = "catalog"
    merged["_source"] = source
    return merged


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
    saw_fallback = False
    for r in regions:
        spec = _resolve_tier_spec(
            provider=r.get("provider"), instance_size=r.get("instance_size"),
            base_tier=r.get("base_tier"), cls=r.get("class"),
        )
        if spec.get("_source") in ("catalog", "flat+catalog"):
            saw_fallback = True
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
        rows.append(
            "<tr>"
            f"<td>{html.escape(provider)}</td>"
            f"<td>{html.escape(r.get('region') or '-')}</td>"
            f"<td>{instance_display}</td>"
            f"<td>{_fmt(r.get('node_count'))}</td>"
            f"<td>{_fmt(spec.get('vcpus'))}</td>"
            f"<td>{html.escape(_fmt_memory(spec))}</td>"
            f"<td>{_fmt_iops_cell(provisioned=r.get('disk_iops'), spec=spec, provider=r.get('provider'), disk_size_gb=region_size)}</td>"
            f"<td>{_fmt_storage_cell(disk_size_gb=region_size, spec=spec)}</td>"
            f"<td>{_fmt(spec.get('max_connections_per_node'))}</td>"
            "</tr>"
        )
    footnote = (
        '<p class="hw-note">Some values backfilled from atlas_dedicated_tier_specs.json '
        '(generation-agnostic) when the flat per-provider file lacks a '
        'generation-specific entry.</p>' if saw_fallback else ""
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
        f"{footnote}"
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
                f'<div class="fig" data-metric="{html.escape(metric)}">{fragment}</div>'
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

    sections = []
    # --- mongod sections (replica set, or sharded + routers) ---
    for section_name, entries in _collect_mongod_sections(extraction=extraction).items():
        host_figs = _section_figures(entries=entries, scope="host")
        sections.append((section_name, host_figs))
        for part in _disk_partitions(entries=entries):
            part_figs = _section_figures(entries=entries, scope=part)
            if part_figs:
                sections.append((f"{section_name} - disk partition '{part}'", part_figs))

    # --- Dedicated Search Node section (orthogonal to mongod shape) ---
    for section_name, entries in _collect_search_sections(search=extraction.get("search") or {}).items():
        host_figs = _section_figures(entries=entries, scope="host")
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
