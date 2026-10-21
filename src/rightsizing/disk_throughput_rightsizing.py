from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from common.disk_throughput_metrics import DiskThroughputMetrics
from stats import breach_days, sustained_days_required
from thresholds import Thresholds


@dataclass(frozen=True)
class DiskThroughputEvalResult:
    """Per-node disk throughput verdict. Reads p95 of the pre-computed
    `used_percentage` series on each partition (100 × (read + write) /
    provisioned bytes/sec) and compares against `throughput_up_pct` /
    `throughput_down_pct`. Multi-partition nodes aggregate to the worst
    partition."""
    is_bottleneck: bool
    bottleneck_note: Optional[str]
    is_borderline: bool
    borderline_note: Optional[str]
    can_scale_down: Optional[bool]
    can_scale_down_note: str


class DiskThroughputRightsizing:
    """Evaluates disk throughput saturation for one mongod/mongos node."""

    def __init__(self,
                 partitions: dict[str, DiskThroughputMetrics],
                 thresholds: Thresholds,
                 window_days: float):
        self.partitions = partitions
        self.thresholds = thresholds
        self.window_days = window_days

    @staticmethod
    def no_data_result(reason: str) -> DiskThroughputEvalResult:
        return DiskThroughputEvalResult(
            is_bottleneck=False,
            bottleneck_note=None,
            is_borderline=False,
            borderline_note=None,
            can_scale_down=None,
            can_scale_down_note=reason,
        )

    def evaluate(self) -> DiskThroughputEvalResult:
        up = self.thresholds.throughput_up_pct
        down = self.thresholds.throughput_down_pct
        near = self.thresholds.near_threshold

        per_part: list[tuple[str, object, list]] = []
        for name, metrics in self.partitions.items():
            pct = metrics.used_percentage
            s = pct.stats()
            if s:
                per_part.append((name, s, list(pct.points)))

        if not per_part:
            raise ValueError(
                "No disk throughput percentage samples on any partition — "
                "manager should detect this and emit a no-data verdict upstream."
            )

        worst_name, worst_s, worst_points = max(per_part, key=lambda t: t[1].p95)

        is_bottleneck = False
        bottleneck_note: Optional[str] = None
        is_borderline = False
        borderline_note: Optional[str] = None
        if worst_s.p95 > up:
            days = breach_days(points=worst_points, threshold=up)
            need = sustained_days_required(
                window_days=self.window_days,
                default_days=self.thresholds.sustained_days,
            )
            if days >= need:
                is_bottleneck = True
                bottleneck_note = (
                    f"throughput read+write p95 {worst_s.p95:.1f}% > {up}% "
                    f"on partition [{worst_name}], {days} day(s)"
                )
            else:
                is_borderline = True
                borderline_note = (
                    f"throughput read+write p95 {worst_s.p95:.1f}% > {up}% "
                    f"on partition [{worst_name}] on only {days} day(s) "
                    f"(need {need} to be sustained)"
                )
        elif worst_s.p95 >= up * (1 - near):
            is_borderline = True
            borderline_note = (
                f"throughput read+write p95 {worst_s.p95:.1f}% on partition "
                f"[{worst_name}] within {int(near * 100)}% of the {up}% trigger"
            )

        over_down = [(n, s) for n, s, _ in per_part if s.p95 >= down]
        if not over_down:
            can_scale_down = True
            can_scale_down_note = f"all partitions throughput p95 < {down}%"
        else:
            can_scale_down = False
            names = ", ".join(f"[{n}] p95 {s.p95:.1f}%" for n, s in over_down)
            can_scale_down_note = f"throughput >= {down}% on: {names}"

        return DiskThroughputEvalResult(
            is_bottleneck=is_bottleneck,
            bottleneck_note=bottleneck_note,
            is_borderline=is_borderline,
            borderline_note=borderline_note,
            can_scale_down=can_scale_down,
            can_scale_down_note=can_scale_down_note,
        )
