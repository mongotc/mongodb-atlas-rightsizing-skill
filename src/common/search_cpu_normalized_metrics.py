from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from common.series import Series


'''
Practical reading for rightsizing a Search Node:

Pressure signal: NORMALIZED_CPU_USER + NORMALIZED_CPU_KERNEL sustained
                 near 100% means the mongot process is CPU-bound per core.
Capacity signal: raw CPU_USER + CPU_KERNEL hitting ~ (vCPU_count * 100)
                 means mongot is using every core.
Search Nodes don't emit the SYSTEM_* family — only FTS_PROCESS_* exists.
'''


@dataclass(frozen=True)
class SearchCPUNormalizedMetrics:
    """CPU usage for an Atlas Search (mongot) process. Two semantic pairs:

      - cpu_user / cpu_kernel: raw process-level CPU%, summed across cores;
        can exceed 100% on multi-core instances.
      - normalized_cpu_user / normalized_cpu_kernel: per-core normalized,
        divided by vCPU count; stays in roughly [0, 100].

    Both pairs matter: raw shows absolute consumption, normalized is
    comparable across tiers."""
    cpu_user: Series                # FTS_PROCESS_CPU_USER
    cpu_kernel: Series              # FTS_PROCESS_CPU_KERNEL
    normalized_cpu_user: Series     # FTS_PROCESS_NORMALIZED_CPU_USER
    normalized_cpu_kernel: Series   # FTS_PROCESS_NORMALIZED_CPU_KERNEL

    # ---- parsers ---------------------------------------------------------

    @classmethod
    def create_from_json(cls, host_json: dict) -> "SearchCPUNormalizedMetrics":
        if not host_json.get("FTS_PROCESS_CPU_USER"):
            raise ValueError(
                "FTS_PROCESS_CPU_USER is missing from host_json — "
                "can't construct SearchCPUNormalizedMetrics. Re-extract "
                "the cluster or use a fallback constructor if an "
                "empty-metrics case is actually expected."
            )

        def pull(name: str) -> Series:
            raw = Series.from_raw(name=name, raw=host_json.get(name))
            return raw if raw else Series.empty(name=name, unit="PERCENT")

        return cls(
            cpu_user=pull("FTS_PROCESS_CPU_USER"),
            cpu_kernel=pull("FTS_PROCESS_CPU_KERNEL"),
            normalized_cpu_user=pull("FTS_PROCESS_NORMALIZED_CPU_USER"),
            normalized_cpu_kernel=pull("FTS_PROCESS_NORMALIZED_CPU_KERNEL"),
        )

    # ---- introspection ---------------------------------------------------

    def __bool__(self) -> bool:
        """Truthy when the raw USER series has data — the minimum any
        derivation needs."""
        return bool(self.cpu_user)

    # ---- per-window summaries --------------------------------------------

    def peak_cpu_user(self) -> Optional[float]:
        """Max raw USER reading (can exceed 100% on multi-core)."""
        return max(self.cpu_user.values) if self.cpu_user.values else None

    def peak_cpu_kernel(self) -> Optional[float]:
        return max(self.cpu_kernel.values) if self.cpu_kernel.values else None

    def peak_normalized_cpu_user(self) -> Optional[float]:
        """Max per-core-normalized USER reading. Scale-up trigger if this
        stays near 100 across the window."""
        vs = self.normalized_cpu_user.values
        return max(vs) if vs else None

    def peak_normalized_cpu_kernel(self) -> Optional[float]:
        vs = self.normalized_cpu_kernel.values
        return max(vs) if vs else None

    def trimmed(self, start_ts: Optional[str] = None,
                end_ts: Optional[str] = None) -> "SearchCPUNormalizedMetrics":
        """Narrow every series to timestamps within [start_ts, end_ts].
        Either bound can be None. Mirrors `Series.trimmed` — returns a
        new SearchCPUNormalizedMetrics."""
        return SearchCPUNormalizedMetrics(
            cpu_user=self.cpu_user.trimmed(start_ts, end_ts),
            cpu_kernel=self.cpu_kernel.trimmed(start_ts, end_ts),
            normalized_cpu_user=self.normalized_cpu_user.trimmed(start_ts, end_ts),
            normalized_cpu_kernel=self.normalized_cpu_kernel.trimmed(start_ts, end_ts),
        )
