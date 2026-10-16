from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from common.series import Series


'''
Practical reading for rightsizing a mongod / mongos node:

Pressure signal: USER + KERNEL sustained near 100%
Investigation signal: IOWAIT elevated → disk-bound rather than CPU-bound
These values are already divided by vCPU count, so they're directly
comparable across tier sizes.
'''


@dataclass(frozen=True)
class CPUNormalizedMetrics:
    """Per-core normalized CPU breakdown for a mongod or mongos process.
    All eight values are PERCENT in [0, 100] approximately — their sum
    across all SYSTEM_NORMALIZED_CPU_* fields reflects total CPU usage
    averaged across cores. Same keys are present for both mongod and
    mongos hosts; Atlas emits the SYSTEM_NORMALIZED_CPU_* family
    regardless of role."""
    user: Series        # SYSTEM_NORMALIZED_CPU_USER
    kernel: Series      # SYSTEM_NORMALIZED_CPU_KERNEL
    iowait: Series      # SYSTEM_NORMALIZED_CPU_IOWAIT
    guest: Series       # SYSTEM_NORMALIZED_CPU_GUEST
    irq: Series         # SYSTEM_NORMALIZED_CPU_IRQ
    nice: Series        # SYSTEM_NORMALIZED_CPU_NICE
    softirq: Series     # SYSTEM_NORMALIZED_CPU_SOFTIRQ
    steal: Series       # SYSTEM_NORMALIZED_CPU_STEAL

    # ---- parsers ---------------------------------------------------------

    @classmethod
    def create_from_json(cls, host_json: dict) -> "CPUNormalizedMetrics":
        # Precondition: USER is the primary signal. Missing it means the
        # whole family is absent — raise rather than silently return empty.
        if not host_json.get("SYSTEM_NORMALIZED_CPU_USER"):
            raise ValueError(
                "SYSTEM_NORMALIZED_CPU_USER is missing from host_json — "
                "can't construct CPUNormalizedMetrics. Re-extract the "
                "cluster or use a fallback constructor if an empty-metrics "
                "case is actually expected."
            )

        def pull(name: str) -> Series:
            raw = Series.from_raw(name=name, raw=host_json.get(name))
            return raw if raw else Series.empty(name=name, unit="PERCENT")

        return cls(
            user=pull("SYSTEM_NORMALIZED_CPU_USER"),
            kernel=pull("SYSTEM_NORMALIZED_CPU_KERNEL"),
            iowait=pull("SYSTEM_NORMALIZED_CPU_IOWAIT"),
            guest=pull("SYSTEM_NORMALIZED_CPU_GUEST"),
            irq=pull("SYSTEM_NORMALIZED_CPU_IRQ"),
            nice=pull("SYSTEM_NORMALIZED_CPU_NICE"),
            softirq=pull("SYSTEM_NORMALIZED_CPU_SOFTIRQ"),
            steal=pull("SYSTEM_NORMALIZED_CPU_STEAL"),
        )

    # ---- introspection ---------------------------------------------------

    def __bool__(self) -> bool:
        """Truthy when USER has data — the minimum any derivation needs."""
        return bool(self.user)

    # ---- per-window summaries --------------------------------------------

    def peak_user_percentage(self) -> Optional[float]:
        """Max USER reading over the window. Primary saturation signal."""
        return max(self.user.values) if self.user.values else None

    def peak_kernel_percentage(self) -> Optional[float]:
        return max(self.kernel.values) if self.kernel.values else None

    def peak_iowait_percentage(self) -> Optional[float]:
        """Max IOWAIT reading. Elevated peaks here suggest disk-bound
        workload rather than CPU-bound — don't scale CPU to fix it."""
        return max(self.iowait.values) if self.iowait.values else None

    def trimmed(self, start_ts: Optional[str] = None,
                end_ts: Optional[str] = None) -> "CPUNormalizedMetrics":
        """Narrow every series to timestamps within [start_ts, end_ts].
        Either bound can be None. Mirrors `Series.trimmed` — returns a
        new CPUNormalizedMetrics."""
        return CPUNormalizedMetrics(
            user=self.user.trimmed(start_ts, end_ts),
            kernel=self.kernel.trimmed(start_ts, end_ts),
            iowait=self.iowait.trimmed(start_ts, end_ts),
            guest=self.guest.trimmed(start_ts, end_ts),
            irq=self.irq.trimmed(start_ts, end_ts),
            nice=self.nice.trimmed(start_ts, end_ts),
            softirq=self.softirq.trimmed(start_ts, end_ts),
            steal=self.steal.trimmed(start_ts, end_ts),
        )
