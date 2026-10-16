from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from common.series import Series


'''
Practical reading for rightsizing a disk partition:

Pressure signal: SPACE_PERCENT_USED creeping upward over the window;
                 >= 85% is a storage scale-up trigger on most Atlas tiers.
Values are PERCENT in [0, 100].
'''


@dataclass(frozen=True)
class DiskSizeMetrics:
    """DISK_PARTITION_SPACE_PERCENT_USED only. Kept as a dataclass for
    symmetry with the other three disk families — one entry point, same
    validation idiom — even though it holds a single Series."""
    space_percent_used: Series  # DISK_PARTITION_SPACE_PERCENT_USED

    # ---- parsers ---------------------------------------------------------

    @classmethod
    def create_from_json(cls, partition_json: dict) -> "DiskSizeMetrics":
        if not partition_json.get("DISK_PARTITION_SPACE_PERCENT_USED"):
            raise ValueError(
                "DISK_PARTITION_SPACE_PERCENT_USED is missing from "
                "partition_json — can't construct DiskSizeMetrics. "
                "Re-extract the cluster or use a fallback constructor if "
                "an empty-metrics case is actually expected."
            )
        raw = Series.from_raw(
            name="DISK_PARTITION_SPACE_PERCENT_USED",
            raw=partition_json.get("DISK_PARTITION_SPACE_PERCENT_USED"),
        )
        return cls(
            space_percent_used=raw if raw else Series.empty(
                name="DISK_PARTITION_SPACE_PERCENT_USED", unit="PERCENT",
            ),
        )

    # ---- introspection ---------------------------------------------------

    def __bool__(self) -> bool:
        return bool(self.space_percent_used)

    def peak_percent_used(self) -> Optional[float]:
        vs = self.space_percent_used.values
        return max(vs) if vs else None

    def trimmed(self, start_ts: Optional[str] = None,
                end_ts: Optional[str] = None) -> "DiskSizeMetrics":
        return DiskSizeMetrics(
            space_percent_used=self.space_percent_used.trimmed(start_ts, end_ts),
        )
