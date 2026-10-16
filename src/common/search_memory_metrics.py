from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from common.series import Series
from common.consts import _BYTES_PER_GB


'''
Practical reading for rightsizing a Search node:

Pressure signal: RESIDENT / instance_memory_gb
Cache-warming signal: SHARED trend over time
Ignore VIRTUAL
'''

@dataclass(frozen=True)
class SearchMemoryMetrics:
    resident: Series                # FTS_PROCESS_RESIDENT_MEMORY (RAM in use)
    shared: Series                  # FTS_PROCESS_SHARED_MEMORY
    virtual: Series                 # FTS_PROCESS_VIRTUAL_MEMORY (address space)
    resident_percentage: Series         # calculated percentage of ceiling
    total_memory_gb: float          # physical ceiling, from the tier catalog

    # ---- parsers ---------------------------------------------------------

    @classmethod
    def create_from_json(cls, host_json: dict, total_memory_gb: float) -> "SearchMemoryMetrics":
        # Preconditions. Both would silently produce an empty
        # used_percentage; raising here means callers never see one.
        if total_memory_gb <= 0:
            raise ValueError(
                f"total_memory_gb must be > 0, got {total_memory_gb!r}. "
                f"Check the tier-catalog lookup for the Search Node instance size."
            )

        if not host_json.get("FTS_PROCESS_RESIDENT_MEMORY"):
            raise ValueError(
                "FTS_PROCESS_RESIDENT_MEMORY is missing from host_json — can't compute "
                "used_percentage. Re-extract the cluster or use a fallback "
                "constructor if an empty-metrics case is actually expected."
            )

        def pull(name: str) -> Series:
            raw = Series.from_raw(name=name, raw=host_json.get(name))
            return raw.as_bytes() if raw else Series.empty(name=name, unit="BYTES")

        resident = pull("FTS_PROCESS_RESIDENT_MEMORY")

        # 100 * resident / instance_total — fraction of the physical ceiling
        # the mongot process is holding. This answers "how much of the box
        # is Search actually consuming?".
        ceiling_bytes = total_memory_gb * _BYTES_PER_GB
        used_percentage = resident.mapped(
            fn=lambda r: 100.0 * r / ceiling_bytes,
            name="MEMORY_USED_PERCENTAGE",
            unit="PERCENT",
        )

        return cls(
            resident=resident,
            shared=pull("FTS_PROCESS_SHARED_MEMORY"),
            virtual=pull("FTS_PROCESS_VIRTUAL_MEMORY"),
            resident_percentage=used_percentage,
            total_memory_gb=total_memory_gb,
        )

    # ---- introspection ---------------------------------------------------

    def __bool__(self) -> bool:
        """Truthy when resident has data — the minimum the derivations need."""
        return bool(self.resident)

    @property
    def total_memory_bytes(self) -> float:
        return self.total_memory_gb * _BYTES_PER_GB

    @property
    def used(self) -> Series:
        """Alias of `resident` for API symmetry with SystemMemoryMetrics.
        Lets polymorphic code (e.g. visualize/shared.py) read `mem.used`
        without caring whether the instance is a system or search variant."""
        return self.resident

    # ---- per-timestamp derivations (return Series) -----------------------

    def used_percentage_series(self) -> Series:
        """100 * resident / instance_total. Mirror of
        SystemMemoryMetrics.used_percentage_series — "100% used" reads
        more naturally on a chart than "0% free"."""
        ceiling = self.total_memory_bytes
        if ceiling <= 0:
            return Series.empty(name="MEMORY_USED_PERCENTAGE", unit="PERCENT")
        return self.resident.mapped(
            fn=lambda r: 100.0 * r / ceiling,
            name="MEMORY_USED_PERCENTAGE",
            unit="PERCENT",
        )

    def headroom_bytes(self) -> Series:
        """Per-sample bytes left between `resident` and the instance's physical
        memory ceiling. Negative values mean the kernel reports more
        in-use memory than the ceiling knows about — rare, but possible
        for bursty workloads or when the tier catalog disagrees with the
        actual provisioned size. Caller sees the sign; we don't clamp."""
        ceiling = self.total_memory_bytes
        return self.resident.mapped(
            fn=lambda r: ceiling - r,
            name="MEMORY_HEADROOM_BYTES",
            unit="BYTES",
        )

    def headroom_percentage(self) -> Series:
        """Headroom as a percentage of the instance's physical memory.
        Example: an S30 Search Node (8 GB) at 6 GB resident has
        headroom_percentage = 25%. A scale-down candidate wants this to
        stay comfortably above zero across the window; a scale-up
        candidate has it brushing zero."""
        ceiling = self.total_memory_bytes
        if ceiling <= 0:
            return Series.empty(name="MEMORY_HEADROOM_PERCENTAGE", unit="PERCENT")
        return self.resident.mapped(
            fn=lambda r: 100.0 * (ceiling - r) / ceiling,
            name="MEMORY_HEADROOM_PERCENTAGE",
            unit="PERCENT",
        )

    def peak_used_bytes(self) -> Optional[float]:
        """Largest `resident` reading over the window, bytes."""
        vals = self.resident.values
        return max(vals) if vals else None

    def peak_used_percentage(self) -> Optional[float]:
        """`peak_used_bytes` expressed as a fraction of the instance total.
        > 90% suggests the Search Node is sized close to its working set."""
        peak = self.peak_used_bytes()
        if peak is None or self.total_memory_bytes <= 0:
            return None
        return 100.0 * peak / self.total_memory_bytes

    def min_headroom_percentage(self) -> Optional[float]:
        """Worst-case headroom across the window. Scale-down judgments want
        this to be large even at the trough; averaging would hide spikes."""
        vals = self.headroom_percentage().values
        return min(vals) if vals else None

    def trimmed(self, start_ts: Optional[str] = None,
                end_ts: Optional[str] = None) -> "SearchMemoryMetrics":
        """Narrow every series to timestamps within [start_ts, end_ts].
        Either bound can be None. Mirrors `Series.trimmed` — returns a
        new SearchMemoryMetrics."""
        return SearchMemoryMetrics(
            resident=self.resident.trimmed(start_ts, end_ts),
            shared=self.shared.trimmed(start_ts, end_ts),
            virtual=self.virtual.trimmed(start_ts, end_ts),
            resident_percentage=self.resident_percentage.trimmed(start_ts, end_ts),
            total_memory_gb=self.total_memory_gb,
        )
