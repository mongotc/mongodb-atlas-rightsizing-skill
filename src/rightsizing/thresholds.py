"""Load and expose the tunable thresholds from config.yaml.

Nothing in this module contains policy — every default value lives in the
YAML file at src/config.yaml, so tuning is a text edit rather than a code
change. `load_thresholds()` returns a frozen dataclass so downstream
evaluators get IDE completion and can't accidentally mutate values across
nodes.
"""

import os
from dataclasses import dataclass

import yaml


# src/config.yaml — one level up from this module (src/rightsizing/).
DEFAULT_YAML_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml")
)


@dataclass(frozen=True)
class Range:
    up: float
    down: float


@dataclass(frozen=True)
class MongotHostThresholds:
    cpu_up_pct: float
    cpu_down_pct: float
    mem_used_up_pct: float
    mem_used_down_pct: float
    # Legacy free-% view; evaluate_search.py still reads these.
    mem_free_up_pct: float
    mem_free_down_pct: float


@dataclass(frozen=True)
class Thresholds:
    # mongod
    cpu_up_pct: float
    cpu_down_pct: float
    mem_used_up_pct: float
    mem_used_down_pct: float
    # Legacy free-percentage view (100 − used_*). Still read by the
    # scripts in node_eval.py / evaluate_search.py, which judge memory
    # against p5 of SYSTEM_MEMORY_FREE. New per-domain evaluators read
    # the used-% fields above directly.
    mem_free_up_pct: float
    mem_free_down_pct: float
    iops_up_pct: float
    iops_down_pct: float
    # Legacy fraction view (pct / 100). Still read by the per-domain
    # evaluators and node_eval.py in `fraction * provisioned` form.
    iops_up_fraction: float
    iops_down_fraction: float
    disk_space_up_pct: float
    disk_space_down_pct: float
    disk_latency_up_ms: float
    disk_latency_down_ms: float
    throughput_up_pct: float
    throughput_down_pct: float
    # Legacy fraction view (pct / 100).
    throughput_up_fraction: float
    throughput_down_fraction: float
    connections_up_fraction: float
    connections_down_fraction: float
    page_faults_up_per_sec: float
    page_faults_down_per_sec: float
    cache_fill_up_pct: float
    cache_fill_down_pct: float
    dirty_fill_up_pct: float
    dirty_fill_down_pct: float
    sustained_days: int
    near_threshold: float
    min_coverage: float
    iowait_context_pct: float
    # extraction / evaluation window — mirrors extraction.default_days so
    # evaluators and CLIs don't hardcode 7.
    window_days: float
    # mongot (dedicated Search Nodes)
    mongot_host: MongotHostThresholds
    # provenance
    source_path: str


def load_thresholds(path=None):
    """Load thresholds from a YAML file. Falls back to the bundled defaults."""
    path = path or DEFAULT_YAML_PATH
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    m = raw.get("mongod_host") or {}
    e = raw.get("evaluation") or {}
    x = raw.get("extraction") or {}
    mt = raw.get("mongot_host") or {}
    mt_cpu = mt.get("cpu") or {}
    mt_mem = mt.get("memory") or {}
    return Thresholds(
        cpu_up_pct=m["cpu"]["up_pct"],
        cpu_down_pct=m["cpu"]["down_pct"],
        mem_used_up_pct=m["memory"]["used_up_pct"],
        mem_used_down_pct=m["memory"]["used_down_pct"],
        mem_free_up_pct=100.0 - m["memory"]["used_up_pct"],
        mem_free_down_pct=100.0 - m["memory"]["used_down_pct"],
        iops_up_pct=m["iops"]["up_pct"],
        iops_down_pct=m["iops"]["down_pct"],
        iops_up_fraction=m["iops"]["up_pct"] / 100.0,
        iops_down_fraction=m["iops"]["down_pct"] / 100.0,
        disk_space_up_pct=m["disk_space"]["up_pct"],
        disk_space_down_pct=m["disk_space"]["down_pct"],
        disk_latency_up_ms=m["disk_latency"]["up_ms"],
        disk_latency_down_ms=m["disk_latency"]["down_ms"],
        throughput_up_pct=m["disk_throughput"]["up_pct"],
        throughput_down_pct=m["disk_throughput"]["down_pct"],
        throughput_up_fraction=m["disk_throughput"]["up_pct"] / 100.0,
        throughput_down_fraction=m["disk_throughput"]["down_pct"] / 100.0,
        connections_up_fraction=m["connections"]["up_fraction"],
        connections_down_fraction=m["connections"]["down_fraction"],
        page_faults_up_per_sec=m["page_faults"]["up_per_sec"],
        page_faults_down_per_sec=m["page_faults"]["down_per_sec"],
        cache_fill_up_pct=m["cache_fill"]["up_pct"],
        cache_fill_down_pct=m["cache_fill"]["down_pct"],
        dirty_fill_up_pct=m["dirty_fill"]["up_pct"],
        dirty_fill_down_pct=m["dirty_fill"]["down_pct"],
        sustained_days=int(e.get("sustained_days", 3)),
        near_threshold=float(e.get("near_threshold", 0.10)),
        min_coverage=float(e.get("min_coverage", 0.90)),
        iowait_context_pct=float(e.get("iowait_context_pct", 5)),
        window_days=float(x.get("default_days", 7)),
        mongot_host=MongotHostThresholds(
            cpu_up_pct=mt_cpu.get("up_pct", 80),
            cpu_down_pct=mt_cpu.get("down_pct", 20),
            mem_used_up_pct=mt_mem.get("used_up_pct", 90),
            mem_used_down_pct=mt_mem.get("used_down_pct", 60),
            mem_free_up_pct=100.0 - mt_mem.get("used_up_pct", 90),
            mem_free_down_pct=100.0 - mt_mem.get("used_down_pct", 60),
        ),
        source_path=os.path.abspath(path),
    )
