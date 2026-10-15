# Visualization: turning an extraction.json into an interactive HTML dashboard

`src/visualize/visualize.py` consumes the same `extraction.json` as
`src/rightsizing/rightsize.py` and emits a single standalone
`visualization.html` with one Plotly figure per metric. Every node is a
separate trace on the same figure, so a hot primary is visually distinct
from its idle secondaries at a glance — the point of the tool is to show
the per-node spread the evaluator reduces to a single p95.

## When to use it

- To eyeball what the evaluator saw before trusting a verdict.
- To spot bimodal workloads (one hot shard, rest idle) that a summary
  statistic hides.
- To validate extraction gaps or partition renames (`disk_days` 60-day
  disk window intentionally gets trimmed to the host window on render —
  see `_trim_disks_in_place`).
- Not for sharing in reports; the HTML is standalone but is one file per
  cluster. `rightsize.py` → `rightsizing.md` is the reporting path.

## CLI

Single cluster:

```
python src/visualize/visualize.py --extraction <path/to/extraction.json>
                                  [--out <path/to/visualization.html>]
                                  [--no-open]
```

Default `--out`: `visualization.html` placed next to the input
`extraction.json` (same convention `rightsize.py` uses for `rightsizing.md`).
`--no-open` suppresses the `webbrowser.open` call — pass it when running
headless, in CI, or as part of a larger batch.

Bulk — mirrors `rightsize_bulk.py`:

```
python src/visualize/visualize_bulk.py --summary output/<org>/extraction_summary.json
```

Reads the `extraction_summary.json` written by `extract_bulk.py`,
iterates every row with `status == "ok"`, and renders a
`visualization.html` next to each `extraction.json`. Browser auto-open is
forced off (bulk runs would otherwise spawn 80+ tabs). Exit code is 0 if
every cluster rendered cleanly, 2 if any errored; `[skip] / [err] / [ok]`
lines are printed per cluster.

## Public API

```python
from visualize.visualize import visualize

out_path = visualize(extraction_path, out=None, open_browser=True)
```

Returns the written HTML path. Raises `OSError` on I/O failure or
`json.JSONDecodeError` on malformed input; the CLI wrapper converts both
into `sys.exit` messages.

## Extraction shapes it handles

The code branches on `extraction["type"]`:

- `replica_set` → one "Compute nodes" section containing every node in
  `extraction["nodes"]`.
- `sharded` → one "Compute nodes (all shards)" section flattening every
  node across `extraction["shards"][<rs_name>]` (keys sorted for stable
  legend order), plus a separate "mongos routers" section when
  `extraction["routers"]` is populated. Shard labels are prefixed
  `<rs_name> / <hostname>` so legend entries are unambiguous across shards.
- Dedicated Atlas Search Nodes, if present, add an
  "Atlas Search - per Search Node" section. The section is kept even
  when `search_nodes[]` is empty but `specs` declare dedicated nodes, so
  the `search_nodes_discovery_error` note surfaces (otherwise the user
  would see "no metrics" with no explanation). Co-located mongot (FTS on
  mongod) is intentionally ignored — see
  `src/extraction/extract_search_data.py` for the rationale.
- Free tier / nothing to plot → a stub section titled
  "No measurements available" is emitted so the page still renders.

Trace labels end in `(ROLE)` — e.g. `host:27017 (PRIMARY)` or
`shard-00 / host:27017 (SECONDARY)` — produced by `_trace_label()` /
`_short_role()`. The suffix is parsed back out by the role-toggle JS
(regex `/\(([A-Z_]+)\)\s*$/`); if you change the label format, update
both ends.

## Per-metric figure construction

- `_section_figures(entries, scope)` builds one `go.Figure` per metric
  name in the section. `scope="host"` reads `data["host"][<metric>]`;
  any other value is treated as a disk partition name and reads
  `data["disks"][<partition>][<metric>]`.
- `_collect_metric_names()` returns the union of metric names across
  entries, sorted by a hand-coded `priority` dict so related series are
  adjacent in the stacked view (CPU together, memory together, disk
  I/O together, etc.). Unknown metrics fall to the end but stay
  deterministic (alphabetical within the same priority).
- Empty series are skipped by default so the chart doesn't render blank
  axes. Pass `include_empty=True` only when the *absence* of data is
  itself the signal — currently unused but preserved for FTS-on-mongod
  sections if we ever re-enable them.
- Metrics in `_STATS_OVERLAY_METRICS` (today just
  `MEMORY_USED_PERCENTAGE`) get a per-trace horizontal p5 / p50 / p95
  overlay. Percentiles come from `Series.from_raw(...).stats()` —
  routing through the same `DescriptiveStats` the evaluator uses, not a
  parallel calculation — on the already-scaled values. Each overlay line
  is color-matched to its parent trace (explicit color assignment from
  `_PALETTE` so Plotly's auto-cycle doesn't drift the overlay color off
  the trace), legend-grouped via `legendgroup=<trace label>` (toggling
  the parent trace hides its 3 stat lines too), and drawn with distinct
  dash styles: `p5` dotted, `p50` dashdot, `p95` dash. Overlay lines
  span the chart's full x-range (precomputed once from the union of all
  traces' timestamps) even when an individual trace covers a shorter
  sub-window.
- Y-axis unit is driven by the authoritative Atlas metrics unit catalog:
  `constants/atlas_mongo_metrics.ALL_METRICS`,
  `constants/atlas_mongos_metrics.ALL_METRICS`, and
  `constants/atlas_search_metrics.ALL_METRICS` are merged into
  `_ATLAS_METRIC_UNITS` at import time (last-wins on duplicate keys —
  safe because overlapping metric names carry the same units in every
  catalog). `_unit_for()` consults the Atlas unit via `_ATLAS_METRIC_UNITS`
  → `_ATLAS_UNIT_TO_DISPLAY`, falling back to `_UNIT_PATTERNS` only for
  synthesized metrics the Atlas catalog doesn't know (today just
  `SYSTEM_MEMORY_USED_PERCENT`). Unknown metrics render without a label.
- Bytes-based y-axes (`bytes`, `bytes/sec`) auto-scale per figure via
  `_scale_bytes_unit()`: the figure's max value picks a 1024-based scale
  (KB / MB / GB / TB), every trace's `y` is divided by that scale, and
  the axis label is updated to match (e.g. `GB` or `MB/sec`). Values
  under 1 KiB fall through unchanged. The scale is per-figure, not
  per-trace, so inter-node comparisons on the same chart stay
  consistent.
- Several Atlas-reported metrics aren't in raw bytes (`SYSTEM_MEMORY_*`
  and `SWAP_USAGE_*` are KILOBYTES; `MEMORY_RESIDENT` / `MEMORY_VIRTUAL`
  / `MEMORY_MAPPED` and `JVM_*_MEMORY` are MEGABYTES). `_raw_to_bytes()`
  reads the per-metric Atlas unit from `_ATLAS_METRIC_UNITS` and looks
  it up in `_ATLAS_UNIT_TO_BYTES` (KB → 1024, MB → 1024², GB → 1024³).
  The multiplier is applied in `_metric_figure` before `_scale_bytes_unit`
  so the auto-scaler sees canonical bytes and picks the correct MB/GB/TB
  label. No per-metric overrides live in the visualizer anymore — the
  catalog is the single source of truth; if a new metric lands with an
  off-by-1024 scale, add a `units` entry to the appropriate
  `constants/atlas_*_metrics.py` instead of patching the visualizer.
- Two derived host metrics are synthesized by
  `_synthesize_memory_series()` via the shared `SystemMemoryMetrics`
  dataclass (`src/common/system_memory_metrics.py`):
  - `MEMORY_USED_PERCENTAGE`: `100 * used / tier_ceiling`. The
    denominator is the **physical tier ceiling** (`tier.memory_gb ×
    1024³ bytes`), not `used + free` — that latter form excludes
    buffers/cached/shared and falsely saturates at ~100% whenever the
    kernel uses spare RAM for page cache. Y-axis is locked to `[0,
    100]` so excursions above 100 (data glitches, tier mismatches)
    stand out immediately.
  - `MEMORY_USED_BYTES`: the raw `used` series after
    `Series.as_bytes()` normalization (so KB → B happens once, inside
    `SystemMemoryMetrics`, not sprinkled through the viewer). Y-axis is
    locked to `[0, tier.memory_gb × 1024³]`, with `_scale_bytes_unit`
    taught to accept an `extra_max` so a 16 GiB ceiling on 10 GiB data
    still picks GB (otherwise the ceiling line could land out of frame
    for very large tiers).
  `total_memory_gb` is resolved from the tier catalog
  (`_primary_region_memory_gb()` reads `config.regions[0]` for mongod
  sections; `_search_memory_gb()` reads `search.specs[0]` for dedicated
  Search Node sections — may return None since S-series tiers aren't in
  the per-provider catalog today, in which case both derived charts are
  omitted). `_metric_figure` takes `total_memory_gb` as a kwarg and
  only applies the ceiling when `metric_name == "MEMORY_USED_BYTES"`;
  the percentage ceiling is unconditional at 100. The 6 raw per-sample
  memory series the dataclass consumes (`SYSTEM_MEMORY_USED` / `FREE`
  / `AVAILABLE` / `BUFFERS` / `CACHED` / `SHARED`) are filtered out of
  every host section by `_HIDDEN_HOST_METRICS` so the two derived
  charts are the only memory tiles a reader sees — remove a name from
  that set to surface the raw series again for ad-hoc inspection.
  Caveat: heterogeneous shard-tier clusters aren't attributed per-node
  in the extraction config today, so we take `regions[0]` uniformly —
  multi-tier clusters will see a small inaccuracy on the smaller-tier
  nodes (both percent and absolute ceilings scale off the wrong tier).

## Disk-window alignment with the evaluator

`extraction.disk_days` defaults to 60 (vs. `default_days` 7 for host
metrics) because Atlas resets per-partition series under a new device
name on fleet maintenances; a wider fetch increases the chance of
joining the pre-rename series. The evaluator trims disks to the host
window at eval time (`src/rightsizing/node_eval.py`), so the viewer
would otherwise see 60 days of disk against 7 of host.
`_trim_disks_in_place(extraction, start=_earliest_host_timestamp(…))`
runs the same alignment at render time. ISO Zulu strings sort lexically,
so no datetime parsing is needed.

## Tier catalog resolution (hardware panel)

The "Cluster hardware" table delegates to `load_tier_spec()` from the
shared `src/atlas_tier_spec` module — the same catalog
`src/extraction/extract.py`'s `_resolve_tier_specs` uses, so the viz and
the extractor can't drift. `_resolve_tier_spec()` in the visualizer is
now a thin wrapper that calls `load_tier_spec(provider, instance_size,
generation, cls)` and reshapes the `TierSpec` dataclass into a plain
dict for the `_fmt_*` cell renderers. Missing / unrecognized tiers
return `{}` and render as `-` in the affected columns.

The lookup is per-region: each `config.regions[]` row from the
extraction maps to one `(provider, instance_size, generation, cls)`
tuple, so a mixed-region cluster can show different specs per row. The
old flat-vs-dedicated catalog merge, GCP provider alias (`google_cloud`
vs `gcp`), and `_source` fallback footnote are gone — the shared
module's per-provider JSON files are the single source of truth.

### Provisioned-vs-tier display rules

- **IOPS** (`_fmt_iops_cell`): shows the configured IOPS big, the tier
  range as grey subtext when it differs. On GCP there is no provisioned
  `diskIOPS`, so IOPS is derived as `disk_size_gb * 30` (PD-SSD gives
  30 IOPS/GB) clamped to the tier catalog's
  `[disk_iops_min, disk_iops_max]`. Falls back to the tier range if no
  computation is possible; `-` if neither is known.
- **Storage** (`_fmt_storage_cell`): same pattern — provisioned big,
  tier range (with optional extended cap) as subtext.
- **Memory / vCPUs / Max conn/node**: straight passthrough from the
  resolved spec, `-` when null.

### Older extractions

Extractions written before the `config.regions[]` shape existed fall
back to a note in the hardware panel asking the user to re-run
extraction. The config-level `disk_size_gb` is only used as a fallback
when a specific `regions[i].disk_size_gb` is null (and typically
matches region 0 anyway).

## HTML interactivity (vanilla JS, no build step)

Everything lives in `_HTML_TEMPLATE`. Plotly is loaded from
`cdn.plot.ly/plotly-latest.min.js`; `pio.to_html(fig,
include_plotlyjs=False, full_html=False)` emits each figure as a `<div>`
fragment that the script wires up on load.

- **Layout toggle (Stacked / Grid 3x)** — swaps `.chart-grid` between
  block and CSS-grid layouts. Legend position is swapped in parallel via
  `Plotly.relayout`: right-side legend when stacked (long hostnames
  need the room), bottom legend when grid (cells too narrow). State is
  persisted to `localStorage` under `rightsize-viz-layout`. Breakpoints
  drop to 2-up at 1100 px and 1-up at 720 px.
- **Role toggle** — buttons generated from the set of `(ROLE)` suffixes
  across all traces. Clicking hides/shows every trace of that role on
  every figure (`visible: 'legendonly'`). Lets you compare primaries
  across all shards without the secondary clutter.
- **Right-side chart-visibility panel** — fixed 280 px panel listing
  every figure grouped by section, with `all` / `none` bulk toggles per
  section. The body has `margin-right: 304px` to leave room; the panel
  is `position: fixed` so it stays visible on scroll.

A `requestAnimationFrame` → `window.dispatchEvent('resize')` is fired
after any layout change because Plotly reads the parent width only on
first render; without the resize, grid-mode charts render at
stacked-mode width.

## Output layout at a glance

```
<cluster> - metric visualization            [stacked|grid]  [PRIMARY|SECONDARY|...]
project / type: replica_set / tier: M30 / search: 2x S30 ...
[Cluster hardware] [Compute nodes] [... disk partition 'data'] ...

Cluster hardware
  Provider | Region | Instance | Nodes | vCPUs | Memory | Disk IOPS | Storage | Max conn/node

Compute nodes
  (one Plotly figure per host metric, every node as a trace)

Compute nodes - disk partition 'data'
  (one figure per disk metric, every node as a trace)

[Atlas Search - per Search Node]
  Dedicated Search Nodes: 2x S30 on AWS/US_EAST_1 - state IDLE
  (one figure per host metric, every Search Node as a trace)
```

Right panel: per-section checkboxes with `all` / `none` bulk toggles.

## Extending it

- **Adding a metric unit** — add the `(metric_name, "ATLAS_UNIT")` entry
  to the appropriate `src/constants/atlas_{mongo,mongos,search}_metrics.py`
  catalog; the visualizer picks it up automatically via
  `_ATLAS_METRIC_UNITS`. `_UNIT_PATTERNS` is only for synthesized
  (non-Atlas) metrics — don't add Atlas names there. If the Atlas unit
  enum value is new (not in `_ATLAS_UNIT_TO_DISPLAY` /
  `_ATLAS_UNIT_TO_BYTES`), add a row to those tables too.
- **Changing metric sort order** — edit the `priority` dict in
  `_collect_metric_names`. Lower number = earlier in the section.
- **Adding a section type** — add a collector that returns
  `{section_name: [(trace_label, data_dict)]}` and call it from
  `visualize()` alongside `_collect_mongod_sections` and
  `_collect_search_sections`. The `data_dict` must have a `host` key
  (and optionally `disks`) for `_section_figures` to find anything.
- **Changing trace label format** — update `_trace_label()` *and* the
  `roleRe` regex in the embedded JS (`/\(([A-Z_]+)\)\s*$/`). The role
  toggle depends on the `(ROLE)` suffix being the last token.
- **Adding a hardware-panel column** — extend `_SPEC_FIELDS` if the
  value comes from the tier catalog, add a formatter if it needs
  provisioned-vs-tier display, and update the `<thead>` + per-row
  `<td>` in `_render_hardware_panel`.
