from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from common.series import Series
from common.consts import _BYTES_PER_GB


@dataclass(frozen=True)
class SystemMemoryMetrics:
    free: Series                    # SYSTEM_MEMORY_FREE
    used: Series                    # SYSTEM_MEMORY_USED
    available: Series               # SYSTEM_MEMORY_AVAILABLE (often empty)
    buffers: Series                 # SYSTEM_MEMORY_BUFFERS
    cached: Series                  # SYSTEM_MEMORY_CACHED
    shared: Series                  # SYSTEM_MEMORY_SHARED
    used_percentage: Series         # calculated percentage free
    total_memory_gb: float          # physical ceiling, from the tier catalog

    # ---- parsers ---------------------------------------------------------

    @classmethod
    def create_from_json(cls, host_json: dict, total_memory_gb: float) -> "SystemMemoryMetrics":
        # Preconditions. Both would silently produce an empty
        # used_percentage; raising here means callers never see one.
        if total_memory_gb <= 0:
            raise ValueError(
                f"total_memory_gb must be > 0, got {total_memory_gb!r}. "
                f"Check the tier-catalog lookup for the instance size."
            )
            
        if not host_json.get("SYSTEM_MEMORY_USED"):
            raise ValueError(
                "SYSTEM_MEMORY_USED is missing from host_json — can't compute "
                "used_percentage. Re-extract the cluster or use a fallback "
                "constructor if an empty-metrics case is actually expected."
            )

        def pull(name: str) -> Series:
            raw = Series.from_raw(name=name, raw=host_json.get(name))
            return raw.as_bytes() if raw else Series.empty(name=name, unit="BYTES")

        free = pull("SYSTEM_MEMORY_FREE")
        used = pull("SYSTEM_MEMORY_USED")

        # 100 * used / instance_total — fraction of the physical ceiling in
        # use. This answers "how much of the box are we actually consuming?".
        ceiling_bytes = total_memory_gb * _BYTES_PER_GB
        used_percentage = used.mapped(
            fn=lambda u: 100.0 * u / ceiling_bytes,
            name="MEMORY_USED_PERCENTAGE",
            unit="PERCENT",
        )

        return cls(
            free=free,
            used=used,
            available=pull("SYSTEM_MEMORY_AVAILABLE"),
            buffers=pull("SYSTEM_MEMORY_BUFFERS"),
            cached=pull("SYSTEM_MEMORY_CACHED"),
            shared=pull("SYSTEM_MEMORY_SHARED"),
            used_percentage=used_percentage,
            total_memory_gb=total_memory_gb,
        )

    # ---- introspection ---------------------------------------------------

    def __bool__(self) -> bool:
        """Truthy when at least one of free/used has data — the minimum
        the derivations need."""
        return bool(self.free) and bool(self.used)

    @property
    def total_memory_bytes(self) -> float:
        return self.total_memory_gb * _BYTES_PER_GB

    # ---- per-timestamp derivations (return Series) -----------------------

    def free_percentage(self) -> Series:
        """100 * free / instance_total. Fraction of the physical ceiling
        that the kernel considers unused. Scale-up trigger evaluates
        against this series."""
        ceiling = self.total_memory_bytes
        if ceiling <= 0:
            return Series.empty(name="MEMORY_FREE_PERCENTAGE", unit="PERCENT")
        
        return self.free.mapped(
            fn=lambda f: 100.0 * f / ceiling,
            name="MEMORY_FREE_PERCENTAGE",
            unit="PERCENT",
        )

    def used_percentage_series(self) -> Series:
        """100 * used / instance_total. Visual mirror of free_percentage —
        "100% used" reads more naturally on a chart than "0% free"."""
        ceiling = self.total_memory_bytes
        if ceiling <= 0:
            return Series.empty(name="MEMORY_USED_PERCENTAGE", unit="PERCENT")
        return self.used.mapped(
            fn=lambda u: 100.0 * u / ceiling,
            name="MEMORY_USED_PERCENTAGE",
            unit="PERCENT",
        )

    def headroom_bytes(self) -> Series:
        """Per-sample bytes left between `used` and the instance's physical
        memory ceiling. Negative values mean the kernel reports more
        in-use memory than the ceiling knows about — rare, but possible
        for bursty workloads or when the tier catalog disagrees with the
        actual provisioned size. Caller sees the sign; we don't clamp."""
        ceiling = self.total_memory_bytes
        return self.used.mapped(
            fn=lambda u: ceiling - u,
            name="MEMORY_HEADROOM_BYTES",
            unit="BYTES",
        )

    def headroom_percentage(self) -> Series:
        """Headroom as a percentage of the instance's physical memory.
        Example: on an M40 (16 GB) running at 12 GB used,
        headroom_percentage = 25%. A scale-down candidate wants this to
        stay comfortably above zero across the window; a scale-up
        candidate has it brushing zero."""
        ceiling = self.total_memory_bytes
        if ceiling <= 0:
            return Series.empty(name="MEMORY_HEADROOM_PERCENTAGE", unit="PERCENT")
        return self.used.mapped(
            fn=lambda u: 100.0 * (ceiling - u) / ceiling,
            name="MEMORY_HEADROOM_PERCENTAGE",
            unit="PERCENT",
        )

    def peak_used_bytes(self) -> Optional[float]:
        """Largest `used` reading over the window, bytes."""
        vals = self.used.values
        return max(vals) if vals else None

    def peak_used_percentage(self) -> Optional[float]:
        """`peak_used_bytes` expressed as a fraction of the instance total.
        > 90% suggests the box is sized close to its working set."""
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
                end_ts: Optional[str] = None) -> "SystemMemoryMetrics":
        """Narrow every series to timestamps within [start_ts, end_ts].
        Either bound can be None. Mirrors `Series.trimmed` — returns a
        new SystemMemoryMetrics."""
        return SystemMemoryMetrics(
            free=self.free.trimmed(start_ts, end_ts),
            used=self.used.trimmed(start_ts, end_ts),
            available=self.available.trimmed(start_ts, end_ts),
            buffers=self.buffers.trimmed(start_ts, end_ts),
            cached=self.cached.trimmed(start_ts, end_ts),
            shared=self.shared.trimmed(start_ts, end_ts),
            used_percentage=self.used_percentage.trimmed(start_ts, end_ts),
            total_memory_gb=self.total_memory_gb,
        )
