"""Per-mongod-node evaluation.

Applies the tunable thresholds to one node's metric bundle
(`data = {"host": {metric: series}, "disks": {partition: {metric: series}}}`,
straight out of extraction.json) and returns per-metric triggers, borderline
signals, down-check flags, a summary table, coverage and any missing core
metrics.

Ported from scripts/rightsizing.py:475-611; behavior is identical when the
same threshold values are supplied.
"""

from __future__ import annotations
import operator
from typing import Any, Optional, TypedDict
from stats import breach_days, combine, pctl, summarize, sustained_days_required
from thresholds import Thresholds


CORE_HOST_METRICS = (
    "SYSTEM_NORMALIZED_CPU_USER",
    "SYSTEM_NORMALIZED_CPU_KERNEL",
    "SYSTEM_MEMORY_USED",
    "SYSTEM_MEMORY_FREE",
)
CORE_DISK_METRIC = "DISK_PARTITION_SPACE_PERCENT_USED"


# Series = [(timestamp, value), ...]. Timestamps are ISO-8601 strings as
# returned by extraction; values are numeric. We don't rely on either being
# a specific type here.
Series = list[tuple[Any, float]]

# summarize() returns {"p5", "p50", "p95", "max", "n"} or None for empty series.
Summary = Optional[dict[str, float]]

Trigger = dict[str, str]  # {"id": ..., "text": ...}


class NodeData(TypedDict, total=False):
    host: dict[str, Series]
    disks: dict[str, dict[str, Series]]


class Window(TypedDict, total=False):
    granularity: str
    period: str
    days: float
    label: str
    expected_samples: int


class EvalContext(TypedDict, total=False):
    window: Window
    provisioned_iops: Optional[int]
    max_connections: Optional[tuple[int, int]]


class EvalResult(TypedDict):
    triggers: list[Trigger]
    borderline: list[str]
    down_checks: dict[str, Optional[bool]]
    summary: dict[str, Summary]
    coverage: float
    compute_coverage: float
    disk_coverage: float
    disk_sparse: bool
    missing: list[str]


# Below this per-node disk-coverage threshold (measured over the host eval
# window after trimming), we treat the node's disk data as absent: no disk
# triggers fire, the disk down-check is `None` (unknown, which blocks
# scale_down), and the group aggregator logs the node. Atlas's device-rename
# series resets can push disk_coverage well below 50% for individual nodes
# while compute metrics stay complete — see docstring of this module and the
# `extraction.disk_days` knob in src/config.yaml.
DISK_SPARSE_THRESHOLD = 0.50


# (trigger, borderline, summary). trigger and borderline are None when the
# metric didn't fire; summary is None only when `points` was empty.
CheckResult = tuple[Optional[Trigger], Optional[str], Summary]


def check_high(
    tid: str,
    label: str,
    points: Optional[Series],
    threshold: float,
    *,
    thresholds: Thresholds,
    window_days: float,
    unit: str = "",
    sustained: bool = False,
    threshold_text: Optional[str] = None,
    suffix: str = "",
) -> CheckResult:
    """Pure function: judge whether `points` breaches `threshold`.

    Returns (trigger_or_none, borderline_or_none, summary). The caller is
    responsible for appending the first two to its own lists; the summary
    is returned so callers can inspect p95 for down-check conditions.

    Keyword-only `thresholds` and `window_days` are the shared evaluator
    context — passed in rather than closed over so this is testable in
    isolation."""
    s = summarize(points=points)
    if not s:
        return None, None, None
    limit = threshold_text or f"{round(threshold, 2)}{unit}"
    if s["p95"] > threshold:
        if sustained:
            days = breach_days(points=points, threshold=threshold)
            need = sustained_days_required(window_days=window_days, default_days=thresholds.sustained_days)
            if days < need:
                return None, (
                    f"{label} p95 {s['p95']}{unit} > {limit}, but only on {days} day(s) "
                    f"(needs {need} to count as sustained)"
                ), s
            return {
                "id": tid,
                "text": f"{label} p95 {s['p95']}{unit} > {limit}, on {days} day(s){suffix}",
            }, None, s
        return {
            "id": tid,
            "text": f"{label} p95 {s['p95']}{unit} > {limit}{suffix}",
        }, None, s
    if s["p95"] >= threshold * (1 - thresholds.near_threshold):
        return None, (
            f"{label} p95 {s['p95']}{unit} is within "
            f"{int(thresholds.near_threshold * 100)}% of the {limit} trigger"
        ), s
    return None, None, s


def _earliest_host_timestamp(host):
    """Earliest ISO-8601 timestamp across all host series. Returns None when
    no host series carry data. Timestamps are UTC Zulu strings, which sort
    lexically — no need to parse."""
    best = None
    for s in host.values():
        if not s:
            continue
        t = s[0][0]
        if best is None or t < best:
            best = t
    return best


def _trim_disks_to_window(disks, start):
    """Return a copy of `disks` with every per-metric series filtered to
    points at or after `start`. Used to align disk-partition data (fetched
    over a wider window) with the host evaluation window."""
    if not start:
        return disks
    out = {}
    for part, metrics in disks.items():
        out[part] = {
            name: [p for p in (series or []) if p[0] >= start]
            for name, series in metrics.items()
        }
    return out


def _per_node_disk_coverage(disks, expected):
    """Coverage of the per-partition CORE_DISK_METRIC series over the host
    eval window. Returns 1.0 when the node has no disks (not applicable —
    e.g. a mongos router) so the group aggregator doesn't flag it. Returns
    0.0 when disks exist but CORE_DISK_METRIC is missing."""
    if not disks or not expected:
        return 1.0
    counts = [
        len(metrics.get(CORE_DISK_METRIC) or [])
        for metrics in disks.values()
    ]
    if not counts:
        return 1.0
    return min(min(n / expected, 1.0) for n in counts)


def evaluate_node(
    data: NodeData,
    ctx: EvalContext,
    thresholds: Thresholds,
) -> EvalResult:
    """Apply thresholds to one node. See module-level TypedDicts for the
    shapes of `data`, `ctx` and the return value."""
    host, disks_raw = data.get("host", {}), data.get("disks", {})
    window = ctx["window"]
    # Disk-partition metrics are fetched with a wider window than host
    # metrics (see extraction.disk_days). Trim them to the host window
    # before any summarization so disk p95s reflect the same time slice as
    # compute signals.
    host_window_start = _earliest_host_timestamp(host)
    disks_trimmed = _trim_disks_to_window(disks_raw, start=host_window_start) if disks_raw else {}
    expected_compute = window.get("expected_compute_samples", window.get("expected_samples", 0))
    disk_coverage = _per_node_disk_coverage(disks_trimmed, expected_compute)
    # When a node's disk history is below the sparsity floor, drop it from
    # the per-node evaluation entirely: no disk triggers, no disk down-check
    # vote (set to None/unknown so scale_down can't claim "safe" without
    # evidence). The group aggregator will log the node by name.
    disk_sparse = bool(disks_raw) and disk_coverage < DISK_SPARSE_THRESHOLD
    disks = {} if disk_sparse else disks_trimmed
    triggers: list[Trigger] = []
    borderline: list[str] = []
    summary = {name: summarize(pts) for name, pts in host.items()}

    def check(tid, label, points, threshold, **kwargs) -> Summary:
        """Thin wrapper over the pure `check_high`: appends any emitted
        trigger / borderline string to the local lists and returns the
        summary, so call sites stay single-line."""
        trig, bord, s = check_high(
            tid=tid, label=label, points=points, threshold=threshold,
            thresholds=thresholds, window_days=window["days"],
            **kwargs,
        )
        if trig is not None:
            triggers.append(trig)
        if bord is not None:
            borderline.append(bord)
        return s

    # CPU (user + kernel), sustained
    # TODO: why IOWAIT is not added?
    cpu_pts = combine(
        a=host.get("SYSTEM_NORMALIZED_CPU_USER"),
        b=host.get("SYSTEM_NORMALIZED_CPU_KERNEL"),
        fn=operator.add,
    )
    cpu = check(
        tid="cpu",
        label="CPU (user+kernel)",
        points=cpu_pts,
        threshold=thresholds.cpu_up_pct,
        unit="%",
        sustained=True,
    )
    summary["CPU_USER_PLUS_KERNEL"] = cpu

    # Free memory (percentage of free+used) — judged on p5 (low end)
    mem_pts = [
        (ts, v) for ts, v in combine(
            a=host.get("SYSTEM_MEMORY_FREE"),
            b=host.get("SYSTEM_MEMORY_USED"),
            fn=lambda free, used: 100.0 * free / (free + used) if free + used > 0 else None,
        ) if v is not None
    ]
    mem = summarize(mem_pts)
    summary["MEMORY_FREE_PCT"] = mem
    if mem:
        if mem["p5"] < thresholds.mem_free_up_pct:
            triggers.append({
                "id": "memory",
                "text": (
                    f"Free memory p5 {mem['p5']}% < {thresholds.mem_free_up_pct}% "
                    f"(low for at least 5% of the window)"
                ),
            })
        elif mem["p5"] <= thresholds.mem_free_up_pct * (1 + thresholds.near_threshold):
            borderline.append(
                f"Free memory p5 {mem['p5']}% is within "
                f"{int(thresholds.near_threshold * 100)}% of the "
                f"{thresholds.mem_free_up_pct}% trigger"
            )

    # Connections vs tier limit
    conns = summarize(host.get("CONNECTIONS"))
    limit = ctx.get("max_connections")
    if conns and limit:
        low, high = limit
        limit_text = (
            str(low) if low == high
            else f"{low} (the docs list {low}-{high} for this tier by provider/class)"
        )
        check(
            tid="connections",
            label="Connections",
            points=host["CONNECTIONS"],
            threshold=thresholds.connections_up_fraction * low,
            threshold_text=(
                f"{int(thresholds.connections_up_fraction * 100)}% of the tier's "
                f"{limit_text} max per node"
            ),
        )

    # Queuing (concurrency)
    for label, name in (("read", "READERS"), ("write", "WRITERS")):
        q = summarize(host.get(f"GLOBAL_LOCK_CURRENT_QUEUE_{name}"))
        if q and q["p95"] > 0:
            exec_time = summarize(host.get(f"OP_EXECUTION_TIME_{label.upper()}S"))
            extra = (
                f"; OP_EXECUTION_TIME_{label.upper()}S p95 {exec_time['p95']}ms"
                if exec_time and exec_time["p95"] > 0 else ""
            )
            triggers.append({
                "id": f"queue_{label}",
                "text": (
                    f"{label.capitalize()} concurrency queue p95 {q['p95']} > 0: operations "
                    f"are waiting for a WiredTiger ticket{extra}"
                ),
            })

    # Page faults / cache pressure
    cache_read = summarize(host.get("CACHE_BYTES_READ_INTO"))
    page_faults = check(
        tid="page_faults",
        label="Page faults",
        points=host.get("EXTRA_INFO_PAGE_FAULTS"),
        threshold=thresholds.page_faults_up_per_sec,
        unit="/sec",
        suffix=(
            (f" (CACHE_BYTES_READ_INTO p95 {cache_read['p95']} B/s)"
             if cache_read and cache_read["p95"] > 0 else "")
            + ": WiredTiger cache may be undersized for the working set"
        ),
    )
    cache_fill = check(
        tid="cache_fill",
        label="Cache fill ratio",
        points=host.get("CACHE_FILL_RATIO"),
        threshold=thresholds.cache_fill_up_pct,
        unit="%",
        suffix=" (eviction_target): background eviction likely running continuously",
    )
    dirty_fill = check(
        tid="dirty_fill",
        label="Dirty fill ratio",
        points=host.get("DIRTY_FILL_RATIO"),
        threshold=thresholds.dirty_fill_up_pct,
        unit="%",
        suffix=" (eviction_dirty_target): dirty-page eviction likely running continuously",
    )
    queues = [summarize(host.get(f"GLOBAL_LOCK_CURRENT_QUEUE_{n}")) for n in ("READERS", "WRITERS")]

    # Disks (per partition)
    iowait = summarize(host.get("SYSTEM_NORMALIZED_CPU_IOWAIT"))
    prov = ctx.get("provisioned_iops")
    disk_down = []
    for part, m in sorted(disks.items()):
        for name, pts in m.items():
            summary[f"{name}[{part}]"] = summarize(pts)
        iops_pts = combine(
            a=m.get("DISK_PARTITION_IOPS_READ"),
            b=m.get("DISK_PARTITION_IOPS_WRITE"),
            fn=operator.add,
        )
        iops = summarize(iops_pts)
        summary[f"DISK_PARTITION_IOPS_TOTAL[{part}]"] = iops
        if prov:
            check(
                tid="iops",
                label=f"Disk IOPS read+write [{part}]",
                points=iops_pts,
                threshold=thresholds.iops_up_fraction * prov,
                sustained=True,
                threshold_text=(
                    f"{int(thresholds.iops_up_fraction * 100)}% of provisioned {prov}"
                ),
            )
        space = check(
            tid="disk_space",
            label=f"Disk space used [{part}]",
            points=m.get(CORE_DISK_METRIC),
            threshold=thresholds.disk_space_up_pct,
            unit="%",
            sustained=True,
        )
        latencies = []
        for lat_label in ("read", "write"):
            throughput = summarize(m.get(f"DISK_PARTITION_THROUGHPUT_{lat_label.upper()}"))
            context = []
            if throughput and throughput["p95"] > 0:
                context.append(f"throughput p95 {throughput['p95']} B/s")
            if iowait and iowait["p95"] > thresholds.iowait_context_pct:
                context.append(f"CPU iowait p95 {iowait['p95']}%")
            latencies.append(check(
                tid=f"disk_latency_{lat_label}",
                label=f"Disk {lat_label} latency [{part}]",
                points=m.get(f"DISK_PARTITION_LATENCY_{lat_label.upper()}"),
                threshold=thresholds.disk_latency_up_ms,
                unit="ms",
                threshold_text=f"{thresholds.disk_latency_up_ms}ms heuristic",
                suffix=f" ({', '.join(context)})" if context else "",
            ))
        disk_down.append(
            space is not None and space["p95"] < thresholds.disk_space_down_pct
            and (not prov or not iops
                 or iops["p95"] < thresholds.iops_down_fraction * prov)
            and all(lat is None or lat["p95"] < thresholds.disk_latency_down_ms
                    for lat in latencies)
        )

    # Missing core metrics
    missing = [m for m in CORE_HOST_METRICS if not host.get(m)]
    # CORE_DISK_METRIC is only considered "missing" when disks were reported
    # but the metric wasn't — not when disk data was dropped due to sparsity
    # (that's reported via disk_sparse instead).
    if disks_raw and not disk_sparse and not any(
        m.get(CORE_DISK_METRIC) for m in disks_raw.values()
    ):
        missing.append(CORE_DISK_METRIC)

    # Compute coverage per compute series (CPU/memory), checked against the
    # host window expected_samples. Disk coverage was computed above against
    # the same denominator (post-trim). Legacy `coverage` is min of both so
    # existing callers keep their worst-case view.
    compute_series = [host.get(m) or [] for m in CORE_HOST_METRICS]
    compute_coverage = (
        min(min(len(s) / expected_compute, 1.0) for s in compute_series)
        if expected_compute else 0.0
    )
    coverage = min(compute_coverage, disk_coverage) if disks_raw else compute_coverage

    down_checks = {
        "cpu":         bool(cpu and cpu["p95"] < thresholds.cpu_down_pct),
        "memory":      bool(mem and mem["p5"] > thresholds.mem_free_down_pct),
        # When disk data is dropped for sparsity, the disk down-check is
        # unknown (None), which blocks scale_down via Python's falsy-aware
        # `all()` without silently passing.
        "disk":        (None if disk_sparse
                        else (bool(disk_down) and all(disk_down))),
        "page_faults": page_faults is None or page_faults["p95"] < thresholds.page_faults_down_per_sec,
        "cache_fill":  cache_fill is None or cache_fill["p95"] < thresholds.cache_fill_down_pct,
        "dirty_fill":  dirty_fill is None or dirty_fill["p95"] < thresholds.dirty_fill_down_pct,
        "queues":      all(q is None or q["max"] == 0 for q in queues),
        "connections": (
            not conns or not limit
            or conns["p95"] < thresholds.connections_down_fraction * limit[0]
        ),
    }
    return {
        "triggers": triggers,
        "borderline": borderline,
        "down_checks": down_checks,
        "summary": summary,
        "coverage": round(coverage, 3),
        "compute_coverage": round(compute_coverage, 3),
        "disk_coverage": round(disk_coverage, 3),
        "disk_sparse": disk_sparse,
        "missing": missing,
    }
