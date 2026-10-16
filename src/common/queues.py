from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from common.series import Series


'''
Practical reading for rightsizing global-lock queueing:

Pressure signal: queued readers OR writers consistently > 0 → requests
                 are waiting on the global lock, which usually means the
                 workload is contending for intent locks faster than the
                 server can grant them. Scale-up CPU or re-shape the
                 workload (shorter transactions, fewer wide reads).

Both values are instantaneous counts (SCALAR), sampled on the
measurement cadence.
'''


@dataclass(frozen=True)
class Queues:
    """Global-lock queue depth (readers + writers waiting) for one mongod
    host. Both values are SCALAR counts of requests currently queued.
    mongos routers and Search Nodes do not emit either metric; constructing
    from one of those host dicts raises ValueError so the per-node
    renderer can silently skip them."""
    queue_readers: Series   # GLOBAL_LOCK_CURRENT_QUEUE_READERS
    queue_writers: Series   # GLOBAL_LOCK_CURRENT_QUEUE_WRITERS

    # ---- parsers ---------------------------------------------------------

    @classmethod
    def create_from_json(cls, host_json: dict) -> "Queues":
        if not host_json.get("GLOBAL_LOCK_CURRENT_QUEUE_READERS"):
            raise ValueError(
                "GLOBAL_LOCK_CURRENT_QUEUE_READERS is missing from "
                "host_json — can't construct Queues. Re-extract the "
                "cluster or use a fallback constructor if an empty-"
                "metrics case is actually expected."
            )

        def pull(name: str) -> Series:
            raw = Series.from_raw(name=name, raw=host_json.get(name))
            return raw if raw else Series.empty(name=name, unit="SCALAR")

        return cls(
            queue_readers=pull("GLOBAL_LOCK_CURRENT_QUEUE_READERS"),
            queue_writers=pull("GLOBAL_LOCK_CURRENT_QUEUE_WRITERS"),
        )

    # ---- introspection ---------------------------------------------------

    def __bool__(self) -> bool:
        return bool(self.queue_readers)

    # ---- per-window summaries --------------------------------------------

    def peak_queue_readers(self) -> Optional[float]:
        return max(self.queue_readers.values) if self.queue_readers.values else None

    def peak_queue_writers(self) -> Optional[float]:
        return max(self.queue_writers.values) if self.queue_writers.values else None

    def trimmed(self, start_ts: Optional[str] = None,
                end_ts: Optional[str] = None) -> "Queues":
        return Queues(
            queue_readers=self.queue_readers.trimmed(start_ts, end_ts),
            queue_writers=self.queue_writers.trimmed(start_ts, end_ts),
        )
