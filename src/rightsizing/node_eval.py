"""Per-mongod-node evaluation.

Applies the tunable thresholds to one node's metric bundle
(`data = {"host": {metric: series}, "disks": {partition: {metric: series}}}`,
straight out of extraction.json) and returns per-metric triggers, borderline
signals, down-check flags, a summary table, coverage and any missing core
metrics.

Ported from scripts/rightsizing.py:475-611; behavior is identical when the
same threshold values are supplied.
"""

import operator

from stats import breach_days, combine, pctl, summarize, sustained_days_required


CORE_HOST_METRICS = (
    "SYSTEM_NORMALIZED_CPU_USER",
    "SYSTEM_NORMALIZED_CPU_KERNEL",
    "SYSTEM_MEMORY_USED",
    "SYSTEM_MEMORY_FREE",
)
CORE_DISK_METRIC = "DISK_PARTITION_SPACE_PERCENT_USED"


def evaluate_node(data, ctx, thresholds):
    """Apply thresholds to one node.

    Args:
        data: {"host": {metric_name: [(ts, value), ...]},
               "disks": {partition: {metric_name: series}}}
        ctx: {"window": window_dict,
              "provisioned_iops": int or None,
              "max_connections": (low, high) or None}
        thresholds: Thresholds dataclass (from thresholds.load_thresholds).

    Returns:
        {"triggers": [{"id", "text"}],
         "borderline": [str],
         "down_checks": {name: bool},
         "summary": {metric_name: {p5, p50, p95, max, n}},
         "coverage": float 0..1,
         "missing": [core metric names not returned]}
    """
    host, disks = data.get("host", {}), data.get("disks", {})
    window = ctx["window"]
    triggers, borderline = [], []
    summary = {name: summarize(pts) for name, pts in host.items()}

    def check_high(tid, label, points, threshold, unit="", sustained=False,
                   threshold_text=None, suffix=""):
        s = summarize(points)
        if not s:
            return None
        limit = threshold_text or f"{round(threshold, 2)}{unit}"
        if s["p95"] > threshold:
            if sustained:
                days = breach_days(points, threshold)
                need = sustained_days_required(window["days"], thresholds.sustained_days)
                if days < need:
                    borderline.append(
                        f"{label} p95 {s['p95']}{unit} > {limit}, but only on {days} day(s) "
                        f"(needs {need} to count as sustained)"
                    )
                    return s
                triggers.append({
                    "id": tid,
                    "text": f"{label} p95 {s['p95']}{unit} > {limit}, on {days} day(s){suffix}",
                })
            else:
                triggers.append({
                    "id": tid,
                    "text": f"{label} p95 {s['p95']}{unit} > {limit}{suffix}",
                })
        elif s["p95"] >= threshold * (1 - thresholds.near_threshold):
            borderline.append(
                f"{label} p95 {s['p95']}{unit} is within "
                f"{int(thresholds.near_threshold * 100)}% of the {limit} trigger"
            )
        return s

    # CPU (user + kernel), sustained
    cpu_pts = combine(
        host.get("SYSTEM_NORMALIZED_CPU_USER"),
        host.get("SYSTEM_NORMALIZED_CPU_KERNEL"),
        operator.add,
    )
    cpu = check_high("cpu", "CPU (user+kernel)", cpu_pts, thresholds.cpu_up_pct, "%",
                     sustained=True)
    summary["CPU_USER_PLUS_KERNEL"] = cpu

    # Free memory (percentage of free+used) — judged on p5 (low end)
    mem_pts = [
        (ts, v) for ts, v in combine(
            host.get("SYSTEM_MEMORY_FREE"), host.get("SYSTEM_MEMORY_USED"),
            lambda free, used: 100.0 * free / (free + used) if free + used > 0 else None,
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
        check_high(
            "connections", "Connections", host["CONNECTIONS"],
            thresholds.connections_up_fraction * low,
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
    page_faults = check_high(
        "page_faults", "Page faults", host.get("EXTRA_INFO_PAGE_FAULTS"),
        thresholds.page_faults_up_per_sec, "/sec",
        suffix=(
            (f" (CACHE_BYTES_READ_INTO p95 {cache_read['p95']} B/s)"
             if cache_read and cache_read["p95"] > 0 else "")
            + ": WiredTiger cache may be undersized for the working set"
        ),
    )
    cache_fill = check_high(
        "cache_fill", "Cache fill ratio", host.get("CACHE_FILL_RATIO"),
        thresholds.cache_fill_up_pct, "%",
        suffix=" (eviction_target): background eviction likely running continuously",
    )
    dirty_fill = check_high(
        "dirty_fill", "Dirty fill ratio", host.get("DIRTY_FILL_RATIO"),
        thresholds.dirty_fill_up_pct, "%",
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
            m.get("DISK_PARTITION_IOPS_READ"), m.get("DISK_PARTITION_IOPS_WRITE"),
            operator.add,
        )
        iops = summarize(iops_pts)
        summary[f"DISK_PARTITION_IOPS_TOTAL[{part}]"] = iops
        if prov:
            check_high(
                "iops", f"Disk IOPS read+write [{part}]", iops_pts,
                thresholds.iops_up_fraction * prov, sustained=True,
                threshold_text=(
                    f"{int(thresholds.iops_up_fraction * 100)}% of provisioned {prov}"
                ),
            )
        space = check_high(
            "disk_space", f"Disk space used [{part}]",
            m.get(CORE_DISK_METRIC), thresholds.disk_space_up_pct, "%", sustained=True,
        )
        latencies = []
        for lat_label in ("read", "write"):
            throughput = summarize(m.get(f"DISK_PARTITION_THROUGHPUT_{lat_label.upper()}"))
            context = []
            if throughput and throughput["p95"] > 0:
                context.append(f"throughput p95 {throughput['p95']} B/s")
            if iowait and iowait["p95"] > thresholds.iowait_context_pct:
                context.append(f"CPU iowait p95 {iowait['p95']}%")
            latencies.append(check_high(
                f"disk_latency_{lat_label}",
                f"Disk {lat_label} latency [{part}]",
                m.get(f"DISK_PARTITION_LATENCY_{lat_label.upper()}"),
                thresholds.disk_latency_up_ms, "ms",
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

    # Missing core metrics + coverage
    missing = [m for m in CORE_HOST_METRICS if not host.get(m)]
    if disks and not any(m.get(CORE_DISK_METRIC) for m in disks.values()):
        missing.append(CORE_DISK_METRIC)
    core_series = [host.get(m) or [] for m in CORE_HOST_METRICS]
    core_series += [m.get(CORE_DISK_METRIC) or [] for m in (disks.values() or [{}])]
    expected = window["expected_samples"]
    coverage = min(min(len(s) / expected, 1.0) for s in core_series) if expected else 0.0

    down_checks = {
        "cpu":         bool(cpu and cpu["p95"] < thresholds.cpu_down_pct),
        "memory":      bool(mem and mem["p5"] > thresholds.mem_free_down_pct),
        "disk":        bool(disk_down) and all(disk_down),
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
        "missing": missing,
    }
