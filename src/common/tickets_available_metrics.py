from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from common.series import Series


'''
Practical reading for rightsizing WT concurrency tickets:

Pressure signal: AVAILABLE dropping toward zero → the storage engine has
                 run out of concurrency slots and new requests are waiting.
                 Historically the ceiling is 128 (reads) and 128 (writes),
                 but MongoDB 7.0+ makes the ceiling dynamic via execution
                 control, so a hard cap can't be assumed here.

Fields hold the raw AVAILABLE counts Atlas emits — low = bad. An
inversion to utilization% (cap - available) / cap × 100 would read
"high = bad" like the CPU / memory grids but needs a cap source.
'''


@dataclass(frozen=True)
class TicketsAvailableMetrics:
    """WiredTiger concurrency tickets remaining for one mongod host. Both
    values are SCALAR counts of free (unused) tickets. mongos routers and
    Search Nodes do not emit either metric; constructing from one of those
    host dicts raises ValueError so the per-node renderer can silently
    skip them."""
    reads_available: Series   # TICKETS_AVAILABLE_READS
    writes_available: Series  # TICKETS_AVAILABLE_WRITE

    # ---- parsers ---------------------------------------------------------

    @classmethod
    def create_from_json(cls, host_json: dict) -> "TicketsAvailableMetrics":
        if not host_json.get("TICKETS_AVAILABLE_READS"):
            raise ValueError(
                "TICKETS_AVAILABLE_READS is missing from host_json — "
                "can't construct TicketsAvailableMetrics. Re-extract the "
                "cluster or use a fallback constructor if an empty-metrics "
                "case is actually expected."
            )

        def pull(name: str) -> Series:
            raw = Series.from_raw(name=name, raw=host_json.get(name))
            return raw if raw else Series.empty(name=name, unit="SCALAR")

        return cls(
            reads_available=pull("TICKETS_AVAILABLE_READS"),
            writes_available=pull("TICKETS_AVAILABLE_WRITE"),
        )

    # ---- introspection ---------------------------------------------------

    def __bool__(self) -> bool:
        return bool(self.reads_available)

    # ---- per-window summaries --------------------------------------------

    def min_reads_available(self) -> Optional[float]:
        """Lowest READS_AVAILABLE sample over the window — the "worst
        moment" for read concurrency. Zero means the storage engine ran
        out of read tickets at least once."""
        return min(self.reads_available.values) if self.reads_available.values else None

    def min_writes_available(self) -> Optional[float]:
        """Lowest WRITES_AVAILABLE sample over the window — the "worst
        moment" for write concurrency."""
        return min(self.writes_available.values) if self.writes_available.values else None

    def trimmed(self, start_ts: Optional[str] = None,
                end_ts: Optional[str] = None) -> "TicketsAvailableMetrics":
        return TicketsAvailableMetrics(
            reads_available=self.reads_available.trimmed(start_ts, end_ts),
            writes_available=self.writes_available.trimmed(start_ts, end_ts),
        )
