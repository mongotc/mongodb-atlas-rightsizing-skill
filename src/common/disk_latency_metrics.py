from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from common.series import Series


'''
Practical reading for rightsizing a disk partition:

Pressure signal: sustained read / write latency rising → disk is the bottleneck
Investigation signal: write latency alone spiking → fsync / journal churn
Values are in MILLISECONDS.
'''


@dataclass(frozen=True)
class DiskLatencyMetrics:
    """Read / write latency (milliseconds) for one disk partition. The
    constructor takes the dict at `data.disks[partition_name]`."""
    read: Series   # DISK_PARTITION_LATENCY_READ
    write: Series  # DISK_PARTITION_LATENCY_WRITE

    # ---- parsers ---------------------------------------------------------

    @classmethod
    def create_from_json(cls, partition_json: dict) -> "DiskLatencyMetrics":
        if not partition_json.get("DISK_PARTITION_LATENCY_READ"):
            raise ValueError(
                "DISK_PARTITION_LATENCY_READ is missing from partition_json "
                "— can't construct DiskLatencyMetrics. Re-extract the cluster "
                "or use a fallback constructor if an empty-metrics case is "
                "actually expected."
            )

        def pull(name: str) -> Series:
            raw = Series.from_raw(name=name, raw=partition_json.get(name))
            return raw if raw else Series.empty(name=name, unit="MILLISECONDS")

        return cls(
            read=pull("DISK_PARTITION_LATENCY_READ"),
            write=pull("DISK_PARTITION_LATENCY_WRITE"),
        )

    # ---- introspection ---------------------------------------------------

    def __bool__(self) -> bool:
        return bool(self.read)

    # ---- per-window summaries --------------------------------------------

    def peak_read(self) -> Optional[float]:
        return max(self.read.values) if self.read.values else None

    def peak_write(self) -> Optional[float]:
        return max(self.write.values) if self.write.values else None

    def trimmed(self, start_ts: Optional[str] = None,
                end_ts: Optional[str] = None) -> "DiskLatencyMetrics":
        return DiskLatencyMetrics(
            read=self.read.trimmed(start_ts, end_ts),
            write=self.write.trimmed(start_ts, end_ts),
        )
