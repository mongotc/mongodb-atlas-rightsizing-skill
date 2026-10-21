from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from common.disk_latency_metrics import DiskLatencyMetrics
from thresholds import Thresholds


@dataclass(frozen=True)
class DiskLatencyEvalResult:
    """Per-node disk latency verdict. For each partition we take the
    higher of read-p95 and write-p95 as the signal; the worst partition
    drives the verdict. No sustained-breach check — latency is treated as
    a point-in-time saturation signal, matching the existing heuristic."""
    is_bottleneck: bool
    bottleneck_note: Optional[str]
    is_borderline: bool
    borderline_note: Optional[str]
    can_scale_down: Optional[bool]
    can_scale_down_note: str


class DiskLatencyRightsizing:
    """Evaluates disk latency saturation for one mongod/mongos node. Each
    partition reports a worst-of-read/write p95; the worst partition
    across the node drives the verdict."""

    def __init__(self,
                 partitions: dict[str, DiskLatencyMetrics],
                 thresholds: Thresholds,
                 window_days: float):
        self.partitions = partitions
        self.thresholds = thresholds
        self.window_days = window_days

    @staticmethod
    def no_data_result(reason: str) -> DiskLatencyEvalResult:
        return DiskLatencyEvalResult(
            is_bottleneck=False,
            bottleneck_note=None,
            is_borderline=False,
            borderline_note=None,
            can_scale_down=None,
            can_scale_down_note=reason,
        )

    def evaluate(self) -> DiskLatencyEvalResult:
        up = self.thresholds.disk_latency_up_ms
        down = self.thresholds.disk_latency_down_ms
        near = self.thresholds.near_threshold

        # Per partition, pick the max of read-p95 and write-p95 as the
        # saturation signal.
        per_part: list[tuple[str, float, str]] = []  # (name, worst_p95, which)
        for name, metrics in self.partitions.items():
            r = metrics.read.stats()
            w = metrics.write.stats()
            if r is None and w is None:
                continue
            r_p95 = r.p95 if r else float("-inf")
            w_p95 = w.p95 if w else float("-inf")
            if r_p95 >= w_p95:
                per_part.append((name, r_p95, "read"))
            else:
                per_part.append((name, w_p95, "write"))

        if not per_part:
            raise ValueError(
                "No disk latency samples on any partition — manager should "
                "detect this and emit a no-data verdict upstream."
            )

        worst_name, worst_p95, worst_side = max(per_part, key=lambda t: t[1])

        is_bottleneck = False
        bottleneck_note: Optional[str] = None
        is_borderline = False
        borderline_note: Optional[str] = None
        if worst_p95 > up:
            is_bottleneck = True
            bottleneck_note = (
                f"{worst_side} latency p95 {worst_p95:.1f}ms > {up}ms "
                f"on partition [{worst_name}]"
            )
        elif worst_p95 >= up * (1 - near):
            is_borderline = True
            borderline_note = (
                f"{worst_side} latency p95 {worst_p95:.1f}ms on partition "
                f"[{worst_name}] within {int(near * 100)}% of the {up}ms trigger"
            )

        over_down = [(n, p, s) for n, p, s in per_part if p >= down]
        if not over_down:
            can_scale_down = True
            can_scale_down_note = (
                f"all partitions read/write latency p95 < {down}ms"
            )
        else:
            can_scale_down = False
            names = ", ".join(f"[{n}] {s} p95 {p:.1f}ms" for n, p, s in over_down)
            can_scale_down_note = (
                f"latency >= {down}ms on: {names}"
            )

        return DiskLatencyEvalResult(
            is_bottleneck=is_bottleneck,
            bottleneck_note=bottleneck_note,
            is_borderline=is_borderline,
            borderline_note=borderline_note,
            can_scale_down=can_scale_down,
            can_scale_down_note=can_scale_down_note,
        )
