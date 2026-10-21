from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from common.search_cpu_normalized_metrics import SearchCPUNormalizedMetrics
from stats import breach_days, sustained_days_required
from thresholds import Thresholds


@dataclass(frozen=True)
class SearchCPUEvalResult:
    """Per-Search-Node CPU verdict. Reads p95 of normalized user+kernel
    (per-core bounded) and compares against the mongot thresholds."""
    is_bottleneck: bool
    bottleneck_note: Optional[str]
    is_borderline: bool
    borderline_note: Optional[str]
    can_scale_down: Optional[bool]
    can_scale_down_note: str


class SearchCPURightsizing:
    """Evaluates whether CPU is a bottleneck for one Search Node (mongot).
    Mirror of CPURightsizing without the iowait field — Search Nodes don't
    emit per-process iowait and the signal would be misleading."""

    def __init__(self,
                 metrics: SearchCPUNormalizedMetrics,
                 thresholds: Thresholds,
                 window_days: float):
        self.metrics = metrics
        self.thresholds = thresholds
        self.window_days = window_days

    @staticmethod
    def no_data_result(down: float) -> SearchCPUEvalResult:
        """Verdict for a Search Node whose host_json lacks FTS_PROCESS_*.
        can_scale_down=None blocks the cluster AND."""
        return SearchCPUEvalResult(
            is_bottleneck=False,
            bottleneck_note=None,
            is_borderline=False,
            borderline_note=None,
            can_scale_down=None,
            can_scale_down_note=(
                f"no Search CPU samples on this node (need p95 < {down}%)"
            ),
        )

    def evaluate(self) -> SearchCPUEvalResult:
        up = self.thresholds.mongot_host.cpu_up_pct
        down = self.thresholds.mongot_host.cpu_down_pct
        near = self.thresholds.near_threshold

        cpu_series = self.metrics.user_plus_kernel()
        cpu_s = cpu_series.stats()
        if not cpu_s:
            raise ValueError(
                "Search CPU user+kernel series is empty — the cluster manager "
                "should detect missing data upstream and emit a no-data verdict "
                "instead of calling evaluate()."
            )

        is_bottleneck = False
        bottleneck_note: Optional[str] = None
        is_borderline = False
        borderline_note: Optional[str] = None
        if cpu_s.p95 > up:
            days = breach_days(points=list(cpu_series.points), threshold=up)
            need = sustained_days_required(
                window_days=self.window_days,
                default_days=self.thresholds.sustained_days,
            )
            if days >= need:
                is_bottleneck = True
                bottleneck_note = (
                    f"Search CPU (user+kernel) p95 {cpu_s.p95}% > {up}% "
                    f"on {days} day(s)"
                )
            else:
                is_borderline = True
                borderline_note = (
                    f"Search CPU (user+kernel) p95 {cpu_s.p95}% > {up}% "
                    f"on only {days} day(s) (need {need} to be sustained)"
                )
        elif cpu_s.p95 >= up * (1 - near):
            is_borderline = True
            borderline_note = (
                f"Search CPU (user+kernel) p95 {cpu_s.p95}% within "
                f"{int(near * 100)}% of the {up}% trigger"
            )

        if cpu_s.p95 < down:
            can_scale_down = True
            can_scale_down_note = f"Search CPU p95 {cpu_s.p95}% < {down}%"
        else:
            can_scale_down = False
            can_scale_down_note = f"Search CPU p95 {cpu_s.p95}% >= {down}%"

        return SearchCPUEvalResult(
            is_bottleneck=is_bottleneck,
            bottleneck_note=bottleneck_note,
            is_borderline=is_borderline,
            borderline_note=borderline_note,
            can_scale_down=can_scale_down,
            can_scale_down_note=can_scale_down_note,
        )
