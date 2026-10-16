from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from common.series import Series


'''
Practical reading for rightsizing a disk partition:

Pressure signal: sustained IOPS near the tier's disk_iops_max → disk-bound
Investigation signal: read / write imbalance can point at workload shape
'''


@dataclass(frozen=True)
class DiskIopsMetrics:
    """Read / write IOPS for one disk partition. Both values are per-second
    rates (unit: SCALAR_PER_SECOND). The constructor takes the dict at
    `data.disks[partition_name]` because disks are a sibling scope to
    `data.host`, not nested under it."""
    read: Series   # DISK_PARTITION_IOPS_READ
    write: Series  # DISK_PARTITION_IOPS_WRITE

    # ---- parsers ---------------------------------------------------------

    @classmethod
    def create_from_json(cls, partition_json: dict) -> "DiskIopsMetrics":
        if not partition_json.get("DISK_PARTITION_IOPS_READ"):
            raise ValueError(
                "DISK_PARTITION_IOPS_READ is missing from partition_json — "
                "can't construct DiskIopsMetrics. Re-extract the cluster "
                "or use a fallback constructor if an empty-metrics case "
                "is actually expected."
            )

        def pull(name: str) -> Series:
            raw = Series.from_raw(name=name, raw=partition_json.get(name))
            return raw if raw else Series.empty(name=name, unit="SCALAR_PER_SECOND")

        return cls(
            read=pull("DISK_PARTITION_IOPS_READ"),
            write=pull("DISK_PARTITION_IOPS_WRITE"),
        )

    # ---- introspection ---------------------------------------------------

    def __bool__(self) -> bool:
        """Truthy when the READ series has data — the minimum any
        derivation needs."""
        return bool(self.read)

    # ---- per-window summaries --------------------------------------------

    def peak_read(self) -> Optional[float]:
        return max(self.read.values) if self.read.values else None

    def peak_write(self) -> Optional[float]:
        return max(self.write.values) if self.write.values else None

    def trimmed(self, start_ts: Optional[str] = None,
                end_ts: Optional[str] = None) -> "DiskIopsMetrics":
        """Narrow every series to timestamps within [start_ts, end_ts]."""
        return DiskIopsMetrics(
            read=self.read.trimmed(start_ts, end_ts),
            write=self.write.trimmed(start_ts, end_ts),
        )

    # ---- provisioned IOPS ceiling ---------------------------------------
    #
    # Atlas doesn't expose a single "provisionedIops" field across providers,
    # so we derive the ceiling from Atlas's documented per-provider formulas.
    # Keeping the derivation here — rather than in the visualizer or
    # evaluator — means every caller lands on the same number.
    #
    # AZURE: deferred — Atlas's Azure disk model differs again.

    @staticmethod
    def calc_provisioned_iops(provider: str,
                              generation: str,
                              disk_size_gb: float,
                              tier_iops_max: Optional[int],
                              instance_size: Optional[str] = None,
                              ebs_volume_type: Optional[str] = None,
                              configured_iops: Optional[int] = None) -> Optional[int]:
        '''
        Return the provisioned-IOPS ceiling for one partition, or None
        when the (provider, tier, volume type) combination isn't modelled.

        GCP formulas (from Atlas's "Storage classes" documentation):
          - Gen 1 / PD-SSD (M10/M20 and M30+ without _GEN_2):
              IOPS = min(6000 + 30 * disk_size_gb, tier_iops_max)
          - Gen 2 / Hyperdisk Balanced (M30+ _GEN_2):
              baseline = max(3000, 3 * disk_size_gb)
              maximum  = min(500 * disk_size_gb, tier_iops_max)
            Customers configure anywhere between baseline and maximum; we
            return the *maximum* because that's the upper envelope the
            per-node IOPS chart needs for its y-axis ceiling (using baseline
            would under-cap and let real traces clip through the top).

        AWS formulas (M30+ EBS-backed; M10/M20 and local-NVMe return None
        because the formula doesn't apply there):
          - Standard IOPS / gp3 (`ebs_volume_type == "STANDARD"`), both
            Gen 1 and Gen 2 share the baseline:
              baseline = max(3000, 3 * disk_size_gb)
              Gen 1 is additionally capped at 16,000 IOPS (network storage
              volume cap); Gen 2 at 80,000. Tier limits apply on top.
              return min(baseline, gen_cap, tier_iops_max)
          - Provisioned IOPS / High Performance IOPS (io2, `ebs_volume_type
            == "PROVISIONED"`): user-selected, not formula-derived. We
            return `configured_iops` (from `region.disk_iops`) when set,
            else None.
          - Local-NVMe or unrecognized `ebs_volume_type`: None (the gp3
            baseline would be misleading for an NVMe-backed tier).
        '''
        provider_u = (provider or "").upper()

        if disk_size_gb is None:
            return None

        if provider_u == "GCP":
            if (generation or "").lower() == "gen2":
                formula_value = 500 * disk_size_gb
            else:
                # gen1 / PD-SSD. Fallback for an unknown generation too —
                # most pre-Hyperdisk GCP tiers are gen1.
                formula_value = 6000 + 30 * disk_size_gb

            if tier_iops_max is not None:
                return int(min(formula_value, tier_iops_max))

            return int(formula_value)

        if provider_u == "AWS":
            # Formula is M30+ EBS only — bail on burstable M10/M20.
            if (instance_size or "").upper() in {"M10", "M20"}:
                return None

            volume_type = (ebs_volume_type or "").upper()

            if volume_type == "PROVISIONED":
                # io2 — user-selected IOPS, not formula-derived. Trust the
                # value the extraction captured; None when it isn't set.
                if configured_iops and configured_iops > 0:
                    return int(configured_iops)
                return None

            if volume_type == "STANDARD":
                baseline = max(3000, 3 * disk_size_gb)
                gen_cap = 80000 if (generation or "").lower() == "gen2" else 16000
                cap = gen_cap
                if tier_iops_max is not None:
                    cap = min(cap, tier_iops_max)
                return int(min(baseline, cap))

            # Local-NVMe or an ebs_volume_type we don't recognize — no
            # formula applies. Returning None lets the chart auto-range
            # rather than draw a misleading ceiling.
            return None

        return None
