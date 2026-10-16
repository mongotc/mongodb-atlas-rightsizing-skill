from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from common.series import Series


'''
Practical reading for rightsizing a disk partition:

Pressure signal: sustained throughput approaching the provisioned bandwidth
Investigation signal: imbalance between read and write throughput
Values are BYTES_PER_SECOND — the per-node renderer auto-scales
(bytes/sec → KB/sec → MB/sec → GB/sec) via `shared.scale_bytes_unit`.
'''


# -------- AWS throughput ceiling constants ---------------------------------
#
# Atlas doesn't expose a disk-throughput cap directly, so we compute it from
# the Atlas-documented formulas (see `calc_provisioned_throughput`). Numbers
# below are the per-tier EC2-instance bandwidth caps that bound the formula
# — these come from AWS's EBS-optimized documentation and the Atlas internal
# tier mapping. Values that aren't documented here fall back to the formula
# alone (which may overestimate on tiers whose underlying EC2 instance has a
# tighter bandwidth cap than the storage would allow).

_MIB_PER_SEC = 1024 * 1024          # bytes per MiB
_GIB_PER_SEC = 1024 * 1024 * 1024   # bytes per GiB

# Instance-store (NVMe) throughput is undocumented by AWS and effectively
# constant across tier. Atlas's own 100%-write benchmarks top out at
# ~1.5 GiB/s on i-series Gen 1 and i8g Gen 2 nodes alike.
_NVME_WRITE_THROUGHPUT_BYTES_PER_SEC = int(1.5 * _GIB_PER_SEC)

# EC2 instance bandwidth caps (bytes/sec, decimal MB base per AWS docs).
# Keyed by (atlas_tier, generation). Expand as additional tiers are
# documented; unlisted (tier, generation) tuples skip the EC2 cap step.
_EC2_THROUGHPUT_CAP_BYTES = {
    # Gen 1 — m6g family
    ("M40", "gen1"): int(593.75 * 1_000_000),   # m6g.xlarge
    # Gen 2 — m8g family (higher bandwidth per vCPU)
    ("M40", "gen2"): int(1250   * 1_000_000),   # m8g.xlarge
    ("M50", "gen2"): int(1000   * 1_000_000),   # m8g.2xlarge
    # TODO: add M50 gen1, M60 gen1, M60 gen2 once their EC2 caps are confirmed.
}


def _aws_standard_base_mib_per_sec(disk_size_gb):
    """AWS gp3 base throughput formula from Atlas's AWSNDSInstanceSize.java.
    Same base for Gen 1 and Gen 2; Gen 2 adds extraIOPS * 0.04 on top. The
    piecewise definition keeps a small disk at 125 MiB/s then grows with
    size through two different slopes."""
    if disk_size_gb < 170:
        return 125.0
    if disk_size_gb <= 260:
        return 210.0 + 5 * ((disk_size_gb - 170) / 10)
    return 255.0 + ((disk_size_gb - 260) / 10)


def _is_nvme_class(cls):
    """Atlas NVMe tiers carry 'nvme' in the `class` field (e.g.
    "high_cpu_nvme"). The throughput cap is a constant, not a formula."""
    return "nvme" in (cls or "").lower()


def _gcp_pdssd_instance_cap_mib_per_sec(vcpus):
    """GCP pd-ssd per-instance throughput cap by vCPU count. Values from
    GCP's N1 / N2 pd-ssd tables (same across E2 / N2D / most of GCP's
    general-purpose series; machine types with different caps are rare
    enough that this table is a safe approximation). Returns MiB/s.

    Falls back to the pd-ssd disk-type cap (1,200 MiB/s) when vCPU count
    isn't known — matches "if a specific size isn't listed, calculate
    performance using instance_limit" fallback behavior."""
    if vcpus is None:
        return 1200
    if vcpus < 2:
        return 204
    if vcpus < 8:
        return 240
    if vcpus < 16:
        return 800
    return 1200


@dataclass(frozen=True)
class DiskThroughputMetrics:
    """Read / write throughput (bytes per second) for one disk partition.
    Constructor takes the dict at `data.disks[partition_name]`."""
    read: Series   # DISK_PARTITION_THROUGHPUT_READ
    write: Series  # DISK_PARTITION_THROUGHPUT_WRITE

    # ---- parsers ---------------------------------------------------------

    @classmethod
    def create_from_json(cls, partition_json: dict) -> "DiskThroughputMetrics":
        if not partition_json.get("DISK_PARTITION_THROUGHPUT_READ"):
            raise ValueError(
                "DISK_PARTITION_THROUGHPUT_READ is missing from partition_json "
                "— can't construct DiskThroughputMetrics. Re-extract the "
                "cluster or use a fallback constructor if an empty-metrics "
                "case is actually expected."
            )

        def pull(name: str) -> Series:
            raw = Series.from_raw(name=name, raw=partition_json.get(name))
            return raw if raw else Series.empty(name=name, unit="BYTES_PER_SECOND")

        return cls(
            read=pull("DISK_PARTITION_THROUGHPUT_READ"),
            write=pull("DISK_PARTITION_THROUGHPUT_WRITE"),
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
                end_ts: Optional[str] = None) -> "DiskThroughputMetrics":
        return DiskThroughputMetrics(
            read=self.read.trimmed(start_ts, end_ts),
            write=self.write.trimmed(start_ts, end_ts),
        )

    # ---- provisioned-throughput ceiling ---------------------------------
    #
    # Atlas doesn't expose per-cluster disk throughput, so we derive it from
    # Atlas's documented per-provider formulas (same split-brain approach as
    # `DiskIopsMetrics.calc_provisioned_iops`). Keeping it on the dataclass
    # means every caller lands on the same number.
    #
    # Only AWS is implemented today. GCP and Azure return None — their
    # per-node Disk Throughput chart then auto-ranges with no ceiling line.
    # NVMe tiers return a constant ~1.5 GiB/s (undocumented by AWS; sourced
    # from Atlas's own 100%-write benchmarks).

    @staticmethod
    def calc_provisioned_throughput(provider: Optional[str],
                                    generation: Optional[str],
                                    instance_size: Optional[str],
                                    ebs_volume_type: Optional[str],
                                    disk_size_gb: Optional[float],
                                    provisioned_iops: Optional[int] = None,
                                    tier_class: Optional[str] = None,
                                    vcpus: Optional[int] = None) -> Optional[int]:
        '''
        Return the provisioned disk-throughput ceiling in BYTES_PER_SECOND,
        or None when the (provider, tier, volume type) combo isn't modelled.

        AWS formulas (per Atlas's AWSNDSInstanceSize.java + AWS EBS docs):

          - Instance-store NVMe (`tier_class` contains "nvme"):
              Constant ~1.5 GiB/s regardless of tier / disk size / IOPS.
              Instance-store throughput isn't documented by AWS; the
              number comes from Atlas's own 100%-write benchmarks.

          - gp3 Standard (`ebs_volume_type == "STANDARD"`):
              base_mib = piecewise fn of disk_size_gb (same for Gen 1 and Gen 2):
                   < 170 GB:  125
                170-260 GB:  210 + 5 * ((diskSizeGB-170) / 10)
                   > 260 GB:  255 + ((diskSizeGB-260) / 10)
              Gen 2 only: extra_mib = max(0, provisioned_iops - baseline_iops) * 0.04
                          where baseline_iops = max(3000, 3 * disk_size_gb).
              Final = min(base_mib + extra_mib, EC2 instance cap).

          - io2 PIOPS (`ebs_volume_type == "PROVISIONED"`):
              formula_mib = 0.256 * provisioned_iops
              Final = min(formula_mib, EC2 instance cap).
              Returns None when provisioned_iops isn't set (can't compute).

          - Unknown ebs_volume_type (and not NVMe): None.

        EC2 instance caps come from `_EC2_THROUGHPUT_CAP_BYTES`; tiers not
        in that table skip the cap step (formula value alone is returned).

        GCP formulas (per GCP's "Persistent Disk performance" doc):

          - Gen 1 / pd-ssd (M10/M20 and M30+ without _GEN_2):
              formula_mib  = 0.48 * disk_size_gb + 240
              instance_cap = per-vCPU bucket from the pd-ssd machine-type
                             table (2-7 vCPUs → 240, 8-15 → 800, 16+ → 1200)
              Final = min(formula_mib, instance_cap).

          - Gen 2 / Hyperdisk Balanced (M30+ _GEN_2): not implemented —
            Hyperdisk uses a different (configurable) model whose
            per-tier caps aren't captured here yet. Returns None.
        '''
        if disk_size_gb is None:
            return None

        provider_u = (provider or "").upper()

        if provider_u == "GCP":
            # Gen 2 is Hyperdisk Balanced — different formula family;
            # deferred until Atlas-side tier mapping is captured.
            if (generation or "").lower() == "gen2":
                return None
            # Gen 1 pd-ssd baseline + per-GiB rate, capped by the pd-ssd
            # per-instance limit (which varies by vCPU count).
            formula_mib = 0.48 * disk_size_gb + 240
            instance_cap_mib = _gcp_pdssd_instance_cap_mib_per_sec(vcpus=vcpus)
            return int(min(formula_mib, instance_cap_mib) * _MIB_PER_SEC)

        if provider_u != "AWS":
            return None

        # NVMe tiers short-circuit — constant cap, no formula.
        if _is_nvme_class(tier_class):
            return _NVME_WRITE_THROUGHPUT_BYTES_PER_SEC

        volume_type = (ebs_volume_type or "").upper()
        gen = (generation or "").lower()
        ec2_cap = _EC2_THROUGHPUT_CAP_BYTES.get((instance_size, gen))

        if volume_type == "STANDARD":
            base_mib = _aws_standard_base_mib_per_sec(disk_size_gb=disk_size_gb)
            extra_mib = 0.0
            if gen == "gen2" and provisioned_iops:
                baseline_iops = max(3000, 3 * disk_size_gb)
                extra_iops = max(0, provisioned_iops - baseline_iops)
                extra_mib = extra_iops * 0.04
            total_bytes = int((base_mib + extra_mib) * _MIB_PER_SEC)
            if ec2_cap is not None:
                return min(total_bytes, ec2_cap)
            return total_bytes

        if volume_type == "PROVISIONED":
            if not provisioned_iops or provisioned_iops <= 0:
                return None  # can't evaluate without the user-configured IOPS
            formula_bytes = int(0.256 * provisioned_iops * _MIB_PER_SEC)
            if ec2_cap is not None:
                return min(formula_bytes, ec2_cap)
            return formula_bytes

        return None
