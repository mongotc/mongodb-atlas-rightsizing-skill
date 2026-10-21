from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from common.system_memory_metrics import SystemMemoryMetrics
from stats import breach_days, sustained_days_required
from thresholds import Thresholds

'''
free_up_pct: 10 → scale UP when p5 of free-memory-% is below 10%. "Even at the 
near-worst (p5) moment in the window, less than 10% of RAM is free" → under 
memory pressure.

free_down_pct: 40 → scale DOWN when p5 of free-memory-% is above 40%. "Even at 
the near-worst moment, we still have more than 40% RAM free" → oversized.
'''

@dataclass(frozen=True)
class MemoryEvalResult:
    """Per-node memory verdict. Mirrors CPUEvalResult shape. The paired
    *_note strings carry the human-readable explanation; the manager's
    no-data path produces can_scale_down=None so missing memory evidence
    cannot vote 'yes' at the cluster level."""
    is_bottleneck: bool
    bottleneck_note: Optional[str]
    is_borderline: bool
    borderline_note: Optional[str]
    can_scale_down: Optional[bool]
    can_scale_down_note: str


class MemoryRightsizing:
    """Evaluates whether memory is a bottleneck for one mongod/mongos node.
    Reads p95 of MEMORY_USED_PERCENTAGE (precomputed on SystemMemoryMetrics
    as `used_percentage`) and compares against the up/down thresholds."""

    def __init__(self,
                 metrics: SystemMemoryMetrics,
                 thresholds: Thresholds,
                 window_days: float):
        self.metrics = metrics
        self.thresholds = thresholds
        self.window_days = window_days

    @staticmethod
    def no_data_result(down: float) -> MemoryEvalResult:
        """Verdict for a node whose host_json lacks SYSTEM_MEMORY_USED.
        Produces can_scale_down=None so missing memory evidence blocks the
        cluster-level scale-down vote instead of being read as a yes."""
        return MemoryEvalResult(
            is_bottleneck=False,
            bottleneck_note=None,
            is_borderline=False,
            borderline_note=None,
            can_scale_down=None,
            can_scale_down_note=(
                f"no memory samples on this node (need p95 < {down}%)"
            ),
        )

    def evaluate(self) -> MemoryEvalResult:
        up = self.thresholds.mem_used_up_pct
        down = self.thresholds.mem_used_down_pct
        near = self.thresholds.near_threshold

        used_pct = self.metrics.used_percentage
        mem_s = used_pct.stats()
        if not mem_s:
            raise ValueError(
                "MEMORY_USED_PERCENTAGE series is empty — the cluster manager "
                "should detect missing memory data upstream and emit a no-data "
                "verdict instead of calling evaluate()."
            )

        # Bottleneck / borderline — defaults are "neither."
        is_bottleneck = False
        bottleneck_note: Optional[str] = None
        is_borderline = False
        borderline_note: Optional[str] = None
        if mem_s.p95 > up:
            days = breach_days(points=list(used_pct.points), threshold=up)
            need = sustained_days_required(
                window_days=self.window_days,
                default_days=self.thresholds.sustained_days,
            )
            if days >= need:
                is_bottleneck = True
                bottleneck_note = (
                    f"Memory used p95 {mem_s.p95}% > {up}% "
                    f"on {days} day(s)"
                )
            else:
                is_borderline = True
                borderline_note = (
                    f"Memory used p95 {mem_s.p95}% > {up}% "
                    f"on only {days} day(s) (need {need} to be sustained)"
                )
        elif mem_s.p95 >= up * (1 - near):
            is_borderline = True
            borderline_note = (
                f"Memory used p95 {mem_s.p95}% within "
                f"{int(near * 100)}% of the {up}% trigger"
            )

        if mem_s.p95 < down:
            can_scale_down = True
            can_scale_down_note = f"Memory used p95 {mem_s.p95}% < {down}%"
        else:
            can_scale_down = False
            can_scale_down_note = f"Memory used p95 {mem_s.p95}% >= {down}%"

        return MemoryEvalResult(
            is_bottleneck=is_bottleneck,
            bottleneck_note=bottleneck_note,
            is_borderline=is_borderline,
            borderline_note=borderline_note,
            can_scale_down=can_scale_down,
            can_scale_down_note=can_scale_down_note,
        )
