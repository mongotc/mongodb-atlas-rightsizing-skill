"""Load and expose the tunable thresholds from thresholds.yaml.

Nothing in this module contains policy — every default value lives in the
YAML file next to it, so tuning is a text edit rather than a code change.
`load_thresholds()` returns a frozen dataclass so downstream evaluators get
IDE completion and can't accidentally mutate values across nodes.
"""

import os
from dataclasses import dataclass

import yaml


DEFAULT_YAML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thresholds.yaml")


@dataclass(frozen=True)
class Range:
    up: float
    down: float


@dataclass(frozen=True)
class SearchThresholds:
    cpu_up_pct: float
    cpu_down_pct: float
    mem_free_up_pct: float
    mem_free_down_pct: float


@dataclass(frozen=True)
class Thresholds:
    # mongod
    cpu_up_pct: float
    cpu_down_pct: float
    mem_free_up_pct: float
    mem_free_down_pct: float
    iops_up_fraction: float
    iops_down_fraction: float
    disk_space_up_pct: float
    disk_space_down_pct: float
    disk_latency_up_ms: float
    disk_latency_down_ms: float
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
    # search
    search: SearchThresholds
    # provenance
    source_path: str


def load_thresholds(path=None):
    """Load thresholds from a YAML file. Falls back to the bundled defaults."""
    path = path or DEFAULT_YAML_PATH
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    s = raw.get("search") or {}
    s_cpu = s.get("cpu") or {}
    s_mem = s.get("memory") or {}
    return Thresholds(
        cpu_up_pct=raw["cpu"]["up_pct"],
        cpu_down_pct=raw["cpu"]["down_pct"],
        mem_free_up_pct=raw["memory"]["free_up_pct"],
        mem_free_down_pct=raw["memory"]["free_down_pct"],
        iops_up_fraction=raw["iops"]["up_fraction"],
        iops_down_fraction=raw["iops"]["down_fraction"],
        disk_space_up_pct=raw["disk_space"]["up_pct"],
        disk_space_down_pct=raw["disk_space"]["down_pct"],
        disk_latency_up_ms=raw["disk_latency"]["up_ms"],
        disk_latency_down_ms=raw["disk_latency"]["down_ms"],
        connections_up_fraction=raw["connections"]["up_fraction"],
        connections_down_fraction=raw["connections"]["down_fraction"],
        page_faults_up_per_sec=raw["page_faults"]["up_per_sec"],
        page_faults_down_per_sec=raw["page_faults"]["down_per_sec"],
        cache_fill_up_pct=raw["cache_fill"]["up_pct"],
        cache_fill_down_pct=raw["cache_fill"]["down_pct"],
        dirty_fill_up_pct=raw["dirty_fill"]["up_pct"],
        dirty_fill_down_pct=raw["dirty_fill"]["down_pct"],
        sustained_days=int(raw.get("sustained_days", 3)),
        near_threshold=float(raw.get("near_threshold", 0.10)),
        min_coverage=float(raw.get("min_coverage", 0.90)),
        iowait_context_pct=float(raw.get("iowait_context_pct", 5)),
        search=SearchThresholds(
            cpu_up_pct=s_cpu.get("up_pct", 80),
            cpu_down_pct=s_cpu.get("down_pct", 20),
            mem_free_up_pct=s_mem.get("free_up_pct", 10),
            mem_free_down_pct=s_mem.get("free_down_pct", 40),
        ),
        source_path=os.path.abspath(path),
    )
