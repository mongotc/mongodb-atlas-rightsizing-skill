from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from common.cpu_normalized_metrics import CPUNormalizedMetrics
from stats import breach_days, sustained_days_required
from thresholds import Thresholds


@dataclass(frozen=True)
class CPUEvalResult:
    """Per-node CPU verdict. Every verdict is a bool / tri-state; the
    paired *_note carries the explanation for display.

    - can_scale_down is tri-state: True / False / None. None means "no
      evidence" (empty CPU series) — the cluster-level AND must treat it
      as a blocker, not as a yes."""
    is_bottleneck: bool
    bottleneck_note: Optional[str]
    is_borderline: bool
    borderline_note: Optional[str]
    can_scale_down: Optional[bool]
    can_scale_down_note: str
    iowait_elevated: bool


class CPURightsizing:
    """Evaluates whether CPU is a bottleneck for one mongod/mongos node.
    USER + KERNEL combined on timestamp, p95 compared against the up/down
    thresholds in the config; iowait reported alongside so the cluster
    manager can discount CPU verdicts on disk-bound nodes."""

    def __init__(self,
                 metrics: CPUNormalizedMetrics,
                 thresholds: Thresholds,
                 window_days: float):
        self.metrics = metrics
        self.thresholds = thresholds
        self.window_days = window_days

    @staticmethod
    def no_data_result(down: float) -> CPUEvalResult:
        """Verdict for a node whose host_json lacks the CPU USER series.
        Produces can_scale_down=None so missing CPU evidence blocks the
        cluster-level scale-down vote instead of being read as a yes."""
        return CPUEvalResult(
            is_bottleneck=False,
            bottleneck_note=None,
            is_borderline=False,
            borderline_note=None,
            can_scale_down=None,
            can_scale_down_note=(
                f"no CPU samples on this node (need p95 < {down}%)"
            ),
            iowait_elevated=False,
        )

    def evaluate(self) -> CPUEvalResult:
        up = self.thresholds.cpu_up_pct
        down = self.thresholds.cpu_down_pct
        near = self.thresholds.near_threshold

        cpu_series = self.metrics.user_plus_kernel()
        cpu_s = cpu_series.stats()
        if not cpu_s:
            raise ValueError(
                "CPU user+kernel series is empty — the cluster manager should "
                "detect missing CPU data upstream and emit a no-data verdict "
                "instead of calling evaluate()."
            )
        iowait_s = self.metrics.iowait.stats()

        # Bottleneck / borderline — defaults are "neither."
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
                    f"CPU (user+kernel) p95 {cpu_s.p95}% > {up}% "
                    f"on {days} day(s)"
                )
            else:
                is_borderline = True
                borderline_note = (
                    f"CPU (user+kernel) p95 {cpu_s.p95}% > {up}% "
                    f"on only {days} day(s) (need {need} to be sustained)"
                )
        elif cpu_s.p95 >= up * (1 - near):
            is_borderline = True
            borderline_note = (
                f"CPU (user+kernel) p95 {cpu_s.p95}% within "
                f"{int(near * 100)}% of the {up}% trigger"
            )

        # Scale-down — plain bool here since cpu_s is guaranteed non-None.
        # CPUEvalResult.can_scale_down stays Optional for the manager's
        # no-data path, which bypasses evaluate() entirely.
        if cpu_s.p95 < down:
            can_scale_down = True
            can_scale_down_note = f"CPU p95 {cpu_s.p95}% < {down}%"
        else:
            can_scale_down = False
            can_scale_down_note = f"CPU p95 {cpu_s.p95}% >= {down}%"

        iowait_elevated = bool(
            iowait_s and iowait_s.p95 > self.thresholds.iowait_context_pct
        )

        return CPUEvalResult(
            is_bottleneck=is_bottleneck,
            bottleneck_note=bottleneck_note,
            is_borderline=is_borderline,
            borderline_note=borderline_note,
            can_scale_down=can_scale_down,
            can_scale_down_note=can_scale_down_note,
            iowait_elevated=iowait_elevated,
        )
