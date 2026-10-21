from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from common.disk_iops_metrics import DiskIopsMetrics
from stats import breach_days, sustained_days_required
from thresholds import Thresholds


@dataclass(frozen=True)
class DiskIopsEvalResult:
    """Per-node disk IOPS verdict. Reads p95 of the pre-computed
    `used_percentage` series on each partition (100 × (read + write) /
    provisioned) and compares against `iops_up_pct` / `iops_down_pct`.
    Multi-partition nodes aggregate to the worst partition and surface
    its name in the notes."""
    is_bottleneck: bool
    bottleneck_note: Optional[str]
    is_borderline: bool
    borderline_note: Optional[str]
    can_scale_down: Optional[bool]
    can_scale_down_note: str


class DiskIopsRightsizing:
    """Evaluates disk IOPS saturation for one mongod/mongos node. Walks
    every partition on the node; the worst partition drives the verdict."""

    def __init__(self,
                 partitions: dict[str, DiskIopsMetrics],
                 thresholds: Thresholds,
                 window_days: float):
        self.partitions = partitions
        self.thresholds = thresholds
        self.window_days = window_days

    @staticmethod
    def no_data_result(reason: str) -> DiskIopsEvalResult:
        """Verdict when disk partitions are missing or the provisioned IOPS
        ceiling can't be resolved. can_scale_down=None blocks the cluster
        AND."""
        return DiskIopsEvalResult(
            is_bottleneck=False,
            bottleneck_note=None,
            is_borderline=False,
            borderline_note=None,
            can_scale_down=None,
            can_scale_down_note=reason,
        )

    def evaluate(self) -> DiskIopsEvalResult:
        up = self.thresholds.iops_up_pct
        down = self.thresholds.iops_down_pct
        near = self.thresholds.near_threshold

        # (name, stats, points) per partition. Empty used_percentage
        # (no samples OR unresolvable provisioned_iops) → partition skipped.
        per_part: list[tuple[str, object, list]] = []
        for name, metrics in self.partitions.items():
            pct = metrics.used_percentage
            s = pct.stats()
            if s:
                per_part.append((name, s, list(pct.points)))

        if not per_part:
            raise ValueError(
                "No disk IOPS percentage samples on any partition — manager "
                "should detect this and emit a no-data verdict upstream."
            )

        # Worst partition drives the verdict (highest p95 %).
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
                    f"IOPS read+write p95 {worst_s.p95:.1f}% > {up}% "
                    f"on partition [{worst_name}], {days} day(s)"
                )
            else:
                is_borderline = True
                borderline_note = (
                    f"IOPS read+write p95 {worst_s.p95:.1f}% > {up}% "
                    f"on partition [{worst_name}] on only {days} day(s) "
                    f"(need {need} to be sustained)"
                )
        elif worst_s.p95 >= up * (1 - near):
            is_borderline = True
            borderline_note = (
                f"IOPS read+write p95 {worst_s.p95:.1f}% on partition "
                f"[{worst_name}] within {int(near * 100)}% of the {up}% trigger"
            )

        # Scale-down: ALL partitions must be below `down`.
        over_down = [(n, s) for n, s, _ in per_part if s.p95 >= down]
        if not over_down:
            can_scale_down = True
            can_scale_down_note = f"all partitions IOPS p95 < {down}%"
        else:
            can_scale_down = False
            names = ", ".join(f"[{n}] p95 {s.p95:.1f}%" for n, s in over_down)
            can_scale_down_note = f"IOPS >= {down}% on: {names}"

        return DiskIopsEvalResult(
            is_bottleneck=is_bottleneck,
            bottleneck_note=bottleneck_note,
            is_borderline=is_borderline,
            borderline_note=borderline_note,
            can_scale_down=can_scale_down,
            can_scale_down_note=can_scale_down_note,
        )
