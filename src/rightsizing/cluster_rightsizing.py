#!/usr/bin/env python3
"""
Single-cluster rightsizing CLI.

Loads one extraction.json, runs ClusterRightsizingManager over both the
mongod fleet (replica-set `nodes` + sharded `shards`) and the Search
fleet (`search.search_nodes`), and prints two side-by-side scale-down
verdicts with per-node breakdowns.

Mongod domains : CPU, memory, disk IOPS, disk latency, disk throughput.
Search domains : search CPU, search memory.

Example:

  python src/rightsizing/cluster_rightsizing.py \\
    --extraction output/persona/persona-data-products-staging/data-products/extraction.json
"""

import argparse
import json
import os
import sys

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from cluster_manager import ClusterRightsizingManager  # noqa: E402
from report_generator import write_report  # noqa: E402
from results import ClusterRightsizingResult  # noqa: E402
from thresholds import DEFAULT_YAML_PATH, Thresholds, load_thresholds  # noqa: E402
from visualize.shared import (  # noqa: E402
    primary_region_memory_gb,
    primary_region_provisioned_iops,
    primary_region_provisioned_throughput,
    search_memory_gb,
)


def collect_nodes(extraction: dict) -> list[tuple[str, dict]]:
    """Flatten the extraction's replica-set `nodes` + sharded `shards` into
    [(label, node_data), ...]. node_data is the raw `n['data']` dict and
    carries both the host-metrics `host` sub-dict and the per-partition
    `disks` sub-dict."""
    out: list[tuple[str, dict]] = []
    for n in extraction.get("nodes") or []:
        out.append((n["label"], n.get("data") or {}))
    for shard_nodes in (extraction.get("shards") or {}).values():
        for n in shard_nodes:
            out.append((n["label"], n.get("data") or {}))
    return out


def collect_search_nodes(extraction: dict) -> list[tuple[str, dict]]:
    """Flatten `extraction['search']['search_nodes']` into
    [(process_id, host_json), ...]. Search Nodes expose `process_id`
    instead of `label` / `role` and don't carry a `disks` sub-dict."""
    search = extraction.get("search") or {}
    out: list[tuple[str, dict]] = []
    for n in search.get("search_nodes") or []:
        out.append((n["process_id"], (n.get("data") or {}).get("host") or {}))
    return out


def run_cluster(extraction: dict, thresholds: Thresholds) -> ClusterRightsizingResult:
    """Compose the ceiling lookups + node flattening + manager call for one
    extraction. Returns the ClusterRightsizingResult. Raises ValueError
    when the mongod tier memory can't be resolved (hard requirement; the
    Search tier can be absent — the manager produces no-data verdicts per
    Search Node if `search_memory_gb` returns None). Shared by the single-
    cluster CLI and the bulk runner so the orchestration logic has one
    source of truth."""
    total_memory_gb = primary_region_memory_gb(extraction=extraction)
    if not total_memory_gb or total_memory_gb <= 0:
        raise ValueError(
            "mongod tier memory GB unresolvable from extraction's config.regions[0]"
        )
    return ClusterRightsizingManager(
        nodes=collect_nodes(extraction=extraction),
        search_nodes=collect_search_nodes(extraction=extraction),
        thresholds=thresholds,
        window_days=thresholds.window_days,
        total_memory_gb=total_memory_gb,
        search_memory_gb=search_memory_gb(extraction=extraction),
        provisioned_iops=primary_region_provisioned_iops(extraction=extraction),
        provisioned_throughput=primary_region_provisioned_throughput(extraction=extraction),
    ).evaluate()


def print_result(result: ClusterRightsizingResult) -> None:
    print("=== mongod ===")
    print(f"cluster can_scale_down: {result.can_scale_down}")
    print(f"reason: {result.reason}")
    print()
    for v in result.nodes:
        print(f"  {v.hostname}")
        print(f"    CPU")
        print(f"      is_bottleneck   : {v.cpu.is_bottleneck} | {v.cpu.bottleneck_note}")
        print(f"      is_borderline   : {v.cpu.is_borderline} | {v.cpu.borderline_note}")
        print(f"      can_scale_down  : {v.cpu.can_scale_down} | {v.cpu.can_scale_down_note}")
        print(f"      iowait_elevated : {v.cpu.iowait_elevated}")
        print(f"    Memory")
        print(f"      is_bottleneck   : {v.memory.is_bottleneck} | {v.memory.bottleneck_note}")
        print(f"      is_borderline   : {v.memory.is_borderline} | {v.memory.borderline_note}")
        print(f"      can_scale_down  : {v.memory.can_scale_down} | {v.memory.can_scale_down_note}")
        print(f"    Disk IOPS")
        print(f"      is_bottleneck   : {v.disk_iops.is_bottleneck} | {v.disk_iops.bottleneck_note}")
        print(f"      is_borderline   : {v.disk_iops.is_borderline} | {v.disk_iops.borderline_note}")
        print(f"      can_scale_down  : {v.disk_iops.can_scale_down} | {v.disk_iops.can_scale_down_note}")
        print(f"    Disk Latency")
        print(f"      is_bottleneck   : {v.disk_latency.is_bottleneck} | {v.disk_latency.bottleneck_note}")
        print(f"      is_borderline   : {v.disk_latency.is_borderline} | {v.disk_latency.borderline_note}")
        print(f"      can_scale_down  : {v.disk_latency.can_scale_down} | {v.disk_latency.can_scale_down_note}")
        print(f"    Disk Throughput")
        print(f"      is_bottleneck   : {v.disk_throughput.is_bottleneck} | {v.disk_throughput.bottleneck_note}")
        print(f"      is_borderline   : {v.disk_throughput.is_borderline} | {v.disk_throughput.borderline_note}")
        print(f"      can_scale_down  : {v.disk_throughput.can_scale_down} | {v.disk_throughput.can_scale_down_note}")

    print()
    print("=== Search ===")
    print(f"search can_scale_down: {result.search_can_scale_down}")
    print(f"reason: {result.search_reason}")
    print()
    for v in result.search_nodes:
        print(f"  {v.hostname}")
        print(f"    Search CPU")
        print(f"      is_bottleneck   : {v.cpu.is_bottleneck} | {v.cpu.bottleneck_note}")
        print(f"      is_borderline   : {v.cpu.is_borderline} | {v.cpu.borderline_note}")
        print(f"      can_scale_down  : {v.cpu.can_scale_down} | {v.cpu.can_scale_down_note}")
        print(f"    Search Memory")
        print(f"      is_bottleneck   : {v.memory.is_bottleneck} | {v.memory.bottleneck_note}")
        print(f"      is_borderline   : {v.memory.is_borderline} | {v.memory.borderline_note}")
        print(f"      can_scale_down  : {v.memory.can_scale_down} | {v.memory.can_scale_down_note}")


def console_main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--extraction", required=True,
                    help="Path to extraction.json (from src/extraction/).")
    ap.add_argument("--thresholds", default=None,
                    help=f"Path to config.yaml (default: {DEFAULT_YAML_PATH}).")
    ap.add_argument("--report", default=None,
                    help="Path to write the markdown report (default: "
                         "rightsizing_report.md next to --extraction).")
    args = ap.parse_args(argv)

    try:
        with open(args.extraction, encoding="utf-8") as f:
            extraction = json.load(f)
    except OSError as e:
        sys.exit(f"Could not read extraction: {e}")
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in extraction: {e}")

    try:
        thresholds = load_thresholds(path=args.thresholds)
    except (OSError, KeyError, ValueError) as e:
        sys.exit(f"Could not load thresholds: {e}")

    try:
        result = run_cluster(extraction=extraction, thresholds=thresholds)
    except ValueError as e:
        sys.exit(str(e))

    print_result(result=result)

    report_path = args.report or os.path.join(
        os.path.dirname(os.path.abspath(args.extraction)) or ".",
        "rightsizing_report.md",
    )
    write_report(
        result=result, path=report_path,
        cluster_name=extraction.get("cluster"),
    )
    print(f"\n[report written to {report_path}]", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(console_main())
