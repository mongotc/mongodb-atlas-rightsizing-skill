from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from common.series import Series


'''
Practical reading for rightsizing WT cache:

Pressure signal: BYTES_READ_INTO sustained high → working set > cache
                 (misses dominate; eviction churn is replacing hot pages)
Investigation signal: BYTES_WRITTEN_FROM elevated → write-heavy workload
                      flushing dirty pages faster than eviction target.
'''


@dataclass(frozen=True)
class CacheActivity:
    """WiredTiger cache I/O for one mongod host. Both values are per-second
    byte rates (unit: BYTES_PER_SECOND). mongos routers and Search Nodes
    do not emit either metric; constructing from one of those host dicts
    raises ValueError so the per-node renderer can silently skip them."""
    bytes_read_into: Series       # CACHE_BYTES_READ_INTO
    bytes_written_from: Series    # CACHE_BYTES_WRITTEN_FROM

    # ---- parsers ---------------------------------------------------------

    @classmethod
    def create_from_json(cls, host_json: dict) -> "CacheActivity":
        if not host_json.get("CACHE_BYTES_READ_INTO"):
            raise ValueError(
                "CACHE_BYTES_READ_INTO is missing from host_json — "
                "can't construct CacheActivity. Re-extract the cluster "
                "or use a fallback constructor if an empty-metrics case "
                "is actually expected."
            )

        def pull(name: str) -> Series:
            raw = Series.from_raw(name=name, raw=host_json.get(name))
            return raw if raw else Series.empty(name=name, unit="BYTES_PER_SECOND")

        return cls(
            bytes_read_into=pull("CACHE_BYTES_READ_INTO"),
            bytes_written_from=pull("CACHE_BYTES_WRITTEN_FROM"),
        )

    # ---- introspection ---------------------------------------------------

    def __bool__(self) -> bool:
        return bool(self.bytes_read_into)

    # ---- per-window summaries --------------------------------------------

    def peak_read_into(self) -> Optional[float]:
        """Max BYTES_READ_INTO over the window — proxy for peak cache miss
        pressure during the measurement period."""
        return max(self.bytes_read_into.values) if self.bytes_read_into.values else None

    def peak_written_from(self) -> Optional[float]:
        """Max BYTES_WRITTEN_FROM over the window — proxy for peak dirty-
        page flush rate."""
        return max(self.bytes_written_from.values) if self.bytes_written_from.values else None

    def trimmed(self, start_ts: Optional[str] = None,
                end_ts: Optional[str] = None) -> "CacheActivity":
        return CacheActivity(
            bytes_read_into=self.bytes_read_into.trimmed(start_ts, end_ts),
            bytes_written_from=self.bytes_written_from.trimmed(start_ts, end_ts),
        )
