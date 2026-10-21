from __future__ import annotations
from dataclasses import dataclass

from cpu_rightsizing import CPUEvalResult
from disk_iops_rightsizing import DiskIopsEvalResult
from disk_latency_rightsizing import DiskLatencyEvalResult
from disk_throughput_rightsizing import DiskThroughputEvalResult
from memory_rightsizing import MemoryEvalResult
from search_cpu_rightsizing import SearchCPUEvalResult
from search_memory_rightsizing import SearchMemoryEvalResult


@dataclass(frozen=True)
class NodeVerdict:
    hostname: str
    cpu: CPUEvalResult
    memory: MemoryEvalResult
    disk_iops: DiskIopsEvalResult
    disk_latency: DiskLatencyEvalResult
    disk_throughput: DiskThroughputEvalResult


@dataclass(frozen=True)
class SearchNodeVerdict:
    hostname: str                       # process_id
    cpu: SearchCPUEvalResult
    memory: SearchMemoryEvalResult


@dataclass(frozen=True)
class ClusterRightsizingResult:
    """Combined mongod + Search cluster verdict. The two fleets scale
    independently in Atlas (separate billing, separate tier catalogs), so
    their `can_scale_down` verdicts are reported side-by-side rather than
    AND'd into one bool. A caller that wants a single "everything OK"
    answer can do `result.can_scale_down and result.search_can_scale_down`
    at the call site."""
    # mongod fleet
    can_scale_down: bool
    reason: str
    nodes: tuple[NodeVerdict, ...]
    # Search fleet (empty tuple + True verdict when the cluster has no
    # Search Nodes — i.e. Search isn't a scale-down blocker when absent).
    search_can_scale_down: bool
    search_reason: str
    search_nodes: tuple[SearchNodeVerdict, ...]
