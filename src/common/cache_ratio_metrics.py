from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from common.series import Series


'''
Practical reading for rightsizing WT cache fill:

Pressure signal: FILL_RATIO sustained near eviction_target (default 80%)
                 → eviction is active; working set approaches cache size.
Secondary signal: DIRTY_FILL_RATIO near eviction_dirty_target (default 5%)
                  → write amplification; checkpoint can't keep up with
                  modifications and app threads will start evicting.

Both values arrive from Atlas as 0-100 percentages (not 0-1 fractions).
'''


@dataclass(frozen=True)
class CacheRatioMetrics:
    """WiredTiger cache occupancy for one mongod host. Both ratios are
    PERCENT in [0, 100]. mongos routers and Search Nodes do not emit
    either metric; constructing from one of those host dicts raises
    ValueError so the per-node renderer can silently skip them."""
    fill_ratio: Series        # CACHE_FILL_RATIO
    dirty_fill_ratio: Series  # DIRTY_FILL_RATIO

    # ---- parsers ---------------------------------------------------------

    @classmethod
    def create_from_json(cls, host_json: dict) -> "CacheRatioMetrics":
        if not host_json.get("CACHE_FILL_RATIO"):
            raise ValueError(
                "CACHE_FILL_RATIO is missing from host_json — can't "
                "construct CacheRatioMetrics. Re-extract the cluster "
                "or use a fallback constructor if an empty-metrics case "
                "is actually expected."
            )

        def pull(name: str) -> Series:
            raw = Series.from_raw(name=name, raw=host_json.get(name))
            return raw if raw else Series.empty(name=name, unit="PERCENT")

        return cls(
            fill_ratio=pull("CACHE_FILL_RATIO"),
            dirty_fill_ratio=pull("DIRTY_FILL_RATIO"),
        )

    # ---- introspection ---------------------------------------------------

    def __bool__(self) -> bool:
        return bool(self.fill_ratio)

    # ---- per-window summaries --------------------------------------------

    def peak_fill_ratio(self) -> Optional[float]:
        return max(self.fill_ratio.values) if self.fill_ratio.values else None

    def peak_dirty_fill_ratio(self) -> Optional[float]:
        return max(self.dirty_fill_ratio.values) if self.dirty_fill_ratio.values else None

    def trimmed(self, start_ts: Optional[str] = None,
                end_ts: Optional[str] = None) -> "CacheRatioMetrics":
        return CacheRatioMetrics(
            fill_ratio=self.fill_ratio.trimmed(start_ts, end_ts),
            dirty_fill_ratio=self.dirty_fill_ratio.trimmed(start_ts, end_ts),
        )
