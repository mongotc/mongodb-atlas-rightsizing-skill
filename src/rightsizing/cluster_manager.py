from __future__ import annotations
from typing import Optional

from common.cpu_normalized_metrics import CPUNormalizedMetrics
from common.disk_iops_metrics import DiskIopsMetrics
from common.disk_latency_metrics import DiskLatencyMetrics
from common.disk_throughput_metrics import DiskThroughputMetrics
from common.search_cpu_normalized_metrics import SearchCPUNormalizedMetrics
from common.search_memory_metrics import SearchMemoryMetrics
from common.system_memory_metrics import SystemMemoryMetrics
from cpu_rightsizing import CPUEvalResult, CPURightsizing
from disk_iops_rightsizing import DiskIopsEvalResult, DiskIopsRightsizing
from disk_latency_rightsizing import DiskLatencyEvalResult, DiskLatencyRightsizing
from disk_throughput_rightsizing import DiskThroughputEvalResult, DiskThroughputRightsizing
from memory_rightsizing import MemoryEvalResult, MemoryRightsizing
from results import (
    ClusterRightsizingResult,
    NodeVerdict,
    SearchNodeVerdict,
)
from search_cpu_rightsizing import SearchCPUEvalResult, SearchCPURightsizing
from search_memory_rightsizing import SearchMemoryEvalResult, SearchMemoryRightsizing
from thresholds import Thresholds


class ClusterRightsizingManager:
    """Aggregates per-node verdicts into one cluster-level result that
    carries two independent sub-verdicts: one for the mongod fleet (CPU +
    memory + disk IOPS / latency / throughput) and one for the Search
    fleet (search CPU + search memory). Atlas scales the two fleets
    independently so the two verdicts are reported side-by-side rather
    than AND'd into a single bool."""

    def __init__(self,
                 nodes: list[tuple[str, dict]],
                 search_nodes: list[tuple[str, dict]],
                 thresholds: Thresholds,
                 window_days: float,
                 total_memory_gb: float,
                 search_memory_gb: Optional[float],
                 provisioned_iops: Optional[int],
                 provisioned_throughput: Optional[int]):
        """`nodes` is [(label, node_data), ...] for mongod — node_data is
        `n['data']` carrying both `host` and `disks`. `search_nodes` is
        [(process_id, host_json), ...] for Search Nodes (no disks). Pass
        an empty list for either to skip that fleet's evaluation."""
        self.nodes = nodes
        self.search_nodes = search_nodes
        self.thresholds = thresholds
        self.window_days = window_days
        self.total_memory_gb = total_memory_gb
        self.search_memory_gb = search_memory_gb
        self.provisioned_iops = provisioned_iops
        self.provisioned_throughput = provisioned_throughput

    # ---- mongod per-domain evaluation -----------------------------------

    def _eval_cpu(self, host_json: dict) -> CPUEvalResult:
        try:
            metrics = CPUNormalizedMetrics.create_from_json(host_json=host_json)
        except ValueError:
            return CPURightsizing.no_data_result(down=self.thresholds.cpu_down_pct)
        return CPURightsizing(
            metrics=metrics, thresholds=self.thresholds, window_days=self.window_days,
        ).evaluate()

    def _eval_memory(self, host_json: dict) -> MemoryEvalResult:
        try:
            metrics = SystemMemoryMetrics.create_from_json(
                host_json=host_json, total_memory_gb=self.total_memory_gb,
            )
        except ValueError:
            return MemoryRightsizing.no_data_result(down=self.thresholds.mem_used_down_pct)
        return MemoryRightsizing(
            metrics=metrics, thresholds=self.thresholds, window_days=self.window_days,
        ).evaluate()

    def _build_partitions(self, disks_json: dict, metric_cls, **extra):
        """Walk `disks_json` and build `{partition_name: metric_cls}` for
        every partition that has the gate metric. `extra` is forwarded to
        the metric's `create_from_json` (used for IOPS / throughput which
        need the tier-level `provisioned_*` cap to pre-compute the
        used_percentage series). Partitions that raise on construction
        are silently skipped."""
        out = {}
        for name, partition_json in (disks_json or {}).items():
            try:
                out[name] = metric_cls.create_from_json(
                    partition_json=partition_json, **extra,
                )
            except ValueError:
                continue
        return out

    def _eval_disk_iops(self, disks_json: dict) -> DiskIopsEvalResult:
        if self.provisioned_iops is None:
            return DiskIopsRightsizing.no_data_result(
                reason="provisioned IOPS ceiling not resolvable for this cluster"
            )
        partitions = self._build_partitions(
            disks_json=disks_json, metric_cls=DiskIopsMetrics,
            provisioned_iops=self.provisioned_iops,
        )
        if not partitions:
            return DiskIopsRightsizing.no_data_result(
                reason="no disk IOPS samples on this node"
            )
        return DiskIopsRightsizing(
            partitions=partitions,
            thresholds=self.thresholds,
            window_days=self.window_days,
        ).evaluate()

    def _eval_disk_latency(self, disks_json: dict) -> DiskLatencyEvalResult:
        partitions = self._build_partitions(
            disks_json=disks_json, metric_cls=DiskLatencyMetrics,
        )
        if not partitions:
            return DiskLatencyRightsizing.no_data_result(
                reason="no disk latency samples on this node"
            )
        return DiskLatencyRightsizing(
            partitions=partitions,
            thresholds=self.thresholds,
            window_days=self.window_days,
        ).evaluate()

    def _eval_disk_throughput(self, disks_json: dict) -> DiskThroughputEvalResult:
        if self.provisioned_throughput is None:
            return DiskThroughputRightsizing.no_data_result(
                reason="provisioned throughput ceiling not resolvable for this cluster"
            )
        partitions = self._build_partitions(
            disks_json=disks_json, metric_cls=DiskThroughputMetrics,
            provisioned_throughput=self.provisioned_throughput,
        )
        if not partitions:
            return DiskThroughputRightsizing.no_data_result(
                reason="no disk throughput samples on this node"
            )
        return DiskThroughputRightsizing(
            partitions=partitions,
            thresholds=self.thresholds,
            window_days=self.window_days,
        ).evaluate()

    # ---- Search per-domain evaluation -----------------------------------

    def _eval_search_cpu(self, host_json: dict) -> SearchCPUEvalResult:
        try:
            metrics = SearchCPUNormalizedMetrics.create_from_json(host_json=host_json)
        except ValueError:
            return SearchCPURightsizing.no_data_result(
                down=self.thresholds.mongot_host.cpu_down_pct,
            )
        return SearchCPURightsizing(
            metrics=metrics, thresholds=self.thresholds, window_days=self.window_days,
        ).evaluate()

    def _eval_search_memory(self, host_json: dict) -> SearchMemoryEvalResult:
        if not self.search_memory_gb or self.search_memory_gb <= 0:
            return SearchMemoryRightsizing.no_data_result(
                down=self.thresholds.mongot_host.mem_used_down_pct,
            )
        try:
            metrics = SearchMemoryMetrics.create_from_json(
                host_json=host_json, total_memory_gb=self.search_memory_gb,
            )
        except ValueError:
            return SearchMemoryRightsizing.no_data_result(
                down=self.thresholds.mongot_host.mem_used_down_pct,
            )
        return SearchMemoryRightsizing(
            metrics=metrics, thresholds=self.thresholds, window_days=self.window_days,
        ).evaluate()

    # ---- aggregation -----------------------------------------------------

    def _aggregate_mongod(self, verdicts: list[NodeVerdict]) -> tuple[bool, str]:
        if not verdicts:
            return False, "cluster has no mongod nodes to evaluate"
        blockers_by_domain = {
            "CPU":             [v for v in verdicts if v.cpu.can_scale_down is not True],
            "memory":          [v for v in verdicts if v.memory.can_scale_down is not True],
            "disk IOPS":       [v for v in verdicts if v.disk_iops.can_scale_down is not True],
            "disk latency":    [v for v in verdicts if v.disk_latency.can_scale_down is not True],
            "disk throughput": [v for v in verdicts if v.disk_throughput.can_scale_down is not True],
        }
        all_safe = not any(blockers_by_domain.values())
        if all_safe:
            domain_list = ", ".join(blockers_by_domain)
            return True, f"all {len(verdicts)} node(s) safe to scale down on {domain_list}"
        reason = "; ".join(
            f"{name} blocks on: {', '.join(v.hostname for v in blockers)}"
            for name, blockers in blockers_by_domain.items() if blockers
        )
        return False, reason

    def _aggregate_search(self, verdicts: list[SearchNodeVerdict]) -> tuple[bool, str]:
        # Empty Search fleet → not a blocker (True + explanatory reason).
        # Lets a caller doing `can_scale_down AND search_can_scale_down`
        # treat "no Search Nodes" as "no Search objection."
        if not verdicts:
            return True, "cluster has no Search Nodes"
        blockers_by_domain = {
            "search CPU":    [v for v in verdicts if v.cpu.can_scale_down is not True],
            "search memory": [v for v in verdicts if v.memory.can_scale_down is not True],
        }
        all_safe = not any(blockers_by_domain.values())
        if all_safe:
            domain_list = ", ".join(blockers_by_domain)
            return True, f"all {len(verdicts)} Search Node(s) safe to scale down on {domain_list}"
        reason = "; ".join(
            f"{name} blocks on: {', '.join(v.hostname for v in blockers)}"
            for name, blockers in blockers_by_domain.items() if blockers
        )
        return False, reason

    def evaluate(self) -> ClusterRightsizingResult:
        mongod_verdicts: list[NodeVerdict] = []
        for hostname, node_data in self.nodes:
            host_json = (node_data or {}).get("host") or {}
            disks_json = (node_data or {}).get("disks") or {}
            mongod_verdicts.append(NodeVerdict(
                hostname=hostname,
                cpu=self._eval_cpu(host_json=host_json),
                memory=self._eval_memory(host_json=host_json),
                disk_iops=self._eval_disk_iops(disks_json=disks_json),
                disk_latency=self._eval_disk_latency(disks_json=disks_json),
                disk_throughput=self._eval_disk_throughput(disks_json=disks_json),
            ))

        search_verdicts: list[SearchNodeVerdict] = []
        for hostname, host_json in self.search_nodes:
            search_verdicts.append(SearchNodeVerdict(
                hostname=hostname,
                cpu=self._eval_search_cpu(host_json=host_json),
                memory=self._eval_search_memory(host_json=host_json),
            ))

        can_scale_down, reason = self._aggregate_mongod(verdicts=mongod_verdicts)
        search_can_scale_down, search_reason = self._aggregate_search(verdicts=search_verdicts)

        return ClusterRightsizingResult(
            can_scale_down=can_scale_down,
            reason=reason,
            nodes=tuple(mongod_verdicts),
            search_can_scale_down=search_can_scale_down,
            search_reason=search_reason,
            search_nodes=tuple(search_verdicts),
        )
