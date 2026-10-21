from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from common.search_memory_metrics import SearchMemoryMetrics
from stats import breach_days, sustained_days_required
from thresholds import Thresholds


@dataclass(frozen=True)
class SearchMemoryEvalResult:
    """Per-Search-Node memory verdict. Reads p95 of RESIDENT_PERCENTAGE
    (mongot RSS / tier memory GB) and compares against the mongot
    thresholds."""
    is_bottleneck: bool
    bottleneck_note: Optional[str]
    is_borderline: bool
    borderline_note: Optional[str]
    can_scale_down: Optional[bool]
    can_scale_down_note: str


class SearchMemoryRightsizing:
    """Evaluates whether memory is a bottleneck for one Search Node.
    Reads the pre-computed resident_percentage Series on
    SearchMemoryMetrics (100 × RSS / tier memory bytes)."""

    def __init__(self,
                 metrics: SearchMemoryMetrics,
                 thresholds: Thresholds,
                 window_days: float):
        self.metrics = metrics
        self.thresholds = thresholds
        self.window_days = window_days

    @staticmethod
    def no_data_result(down: float) -> SearchMemoryEvalResult:
        return SearchMemoryEvalResult(
            is_bottleneck=False,
            bottleneck_note=None,
            is_borderline=False,
            borderline_note=None,
            can_scale_down=None,
            can_scale_down_note=(
                f"no Search memory samples on this node (need p95 < {down}%)"
            ),
        )

    def evaluate(self) -> SearchMemoryEvalResult:
        up = self.thresholds.mongot_host.mem_used_up_pct
        down = self.thresholds.mongot_host.mem_used_down_pct
        near = self.thresholds.near_threshold

        resident_pct = self.metrics.resident_percentage
        mem_s = resident_pct.stats()
        if not mem_s:
            raise ValueError(
                "Search resident_percentage series is empty — the cluster "
                "manager should detect missing memory data upstream and emit "
                "a no-data verdict instead of calling evaluate()."
            )

        is_bottleneck = False
        bottleneck_note: Optional[str] = None
        is_borderline = False
        borderline_note: Optional[str] = None
        if mem_s.p95 > up:
            days = breach_days(points=list(resident_pct.points), threshold=up)
            need = sustained_days_required(
                window_days=self.window_days,
                default_days=self.thresholds.sustained_days,
            )
            if days >= need:
                is_bottleneck = True
                bottleneck_note = (
                    f"Search memory p95 {mem_s.p95}% > {up}% on {days} day(s)"
                )
            else:
                is_borderline = True
                borderline_note = (
                    f"Search memory p95 {mem_s.p95}% > {up}% on only "
                    f"{days} day(s) (need {need} to be sustained)"
                )
        elif mem_s.p95 >= up * (1 - near):
            is_borderline = True
            borderline_note = (
                f"Search memory p95 {mem_s.p95}% within "
                f"{int(near * 100)}% of the {up}% trigger"
            )

        if mem_s.p95 < down:
            can_scale_down = True
            can_scale_down_note = f"Search memory p95 {mem_s.p95}% < {down}%"
        else:
            can_scale_down = False
            can_scale_down_note = f"Search memory p95 {mem_s.p95}% >= {down}%"

        return SearchMemoryEvalResult(
            is_bottleneck=is_bottleneck,
            bottleneck_note=bottleneck_note,
            is_borderline=is_borderline,
            borderline_note=borderline_note,
            can_scale_down=can_scale_down,
            can_scale_down_note=can_scale_down_note,
        )
