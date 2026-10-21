"""Simplified markdown report for a ClusterRightsizingResult.

Layout:
  1. Summary table (mongod + Search can-scale-down flags).
  2. Mongod section — one row per node with a ✅/❌ per domain, plus a
     blockers list for nodes that failed any domain.
  3. Search section — same table shape, with 2 domain columns.

Rendered via `generate_markdown(result, cluster_name)` as a string. The
CLI wraps this with `write_report(result, path, cluster_name)` to drop a
file next to the extraction.
"""

from __future__ import annotations
from typing import Optional

from results import (
    ClusterRightsizingResult,
    NodeVerdict,
    SearchNodeVerdict,
)


_YES = "✅"
_NO = "❌"


def _flag(can_scale_down: Optional[bool]) -> str:
    """Tri-state → emoji. None (no evidence) is treated as a blocker so it
    renders as ❌; the paired note explains it was data-missing, not a
    policy violation."""
    return _YES if can_scale_down is True else _NO


def _yes_no(b: bool) -> str:
    return f"{_YES} Yes" if b else f"{_NO} No"


# ---- mongod section -------------------------------------------------------

def _mongod_row(v: NodeVerdict) -> str:
    cells = [
        v.hostname,
        _flag(v.cpu.can_scale_down),
        _flag(v.memory.can_scale_down),
        _flag(v.disk_iops.can_scale_down),
        _flag(v.disk_latency.can_scale_down),
        _flag(v.disk_throughput.can_scale_down),
    ]
    return "| " + " | ".join(cells) + " |"


def _mongod_blockers(v: NodeVerdict) -> list[str]:
    """One blocker note per domain where can_scale_down is not True."""
    out = []
    for label, dom in (
        ("CPU", v.cpu),
        ("Memory", v.memory),
        ("Disk IOPS", v.disk_iops),
        ("Disk Latency", v.disk_latency),
        ("Disk Throughput", v.disk_throughput),
    ):
        if dom.can_scale_down is not True:
            out.append(f"{label}: {dom.can_scale_down_note}")
    return out


def _mongod_section(result: ClusterRightsizingResult) -> str:
    lines = [f"## Mongod — {_yes_no(result.can_scale_down)}", "",
             f"**Reason**: {result.reason}", ""]

    if not result.nodes:
        lines.append("_No mongod nodes evaluated._")
        return "\n".join(lines)

    # Per-node table.
    lines.append("| Node | CPU | Memory | Disk IOPS | Disk Latency | Disk Throughput |")
    lines.append("|---|---|---|---|---|---|")
    for v in result.nodes:
        lines.append(_mongod_row(v=v))
    lines.append("")

    # Blockers per node (only nodes with at least one blocker).
    blockers_by_node = [(v, _mongod_blockers(v=v)) for v in result.nodes]
    blockers_by_node = [(v, b) for v, b in blockers_by_node if b]
    if blockers_by_node:
        lines.append("### Blockers")
        lines.append("")
        for v, bs in blockers_by_node:
            lines.append(f"- **{v.hostname}**")
            for b in bs:
                lines.append(f"  - {b}")
        lines.append("")

    return "\n".join(lines)


# ---- Search section -------------------------------------------------------

def _search_row(v: SearchNodeVerdict) -> str:
    cells = [
        v.hostname,
        _flag(v.cpu.can_scale_down),
        _flag(v.memory.can_scale_down),
    ]
    return "| " + " | ".join(cells) + " |"


def _search_blockers(v: SearchNodeVerdict) -> list[str]:
    out = []
    for label, dom in (
        ("Search CPU", v.cpu),
        ("Search Memory", v.memory),
    ):
        if dom.can_scale_down is not True:
            out.append(f"{label}: {dom.can_scale_down_note}")
    return out


def _search_section(result: ClusterRightsizingResult) -> str:
    lines = [f"## Search — {_yes_no(result.search_can_scale_down)}", "",
             f"**Reason**: {result.search_reason}", ""]

    if not result.search_nodes:
        lines.append("_No Search Nodes in this cluster._")
        return "\n".join(lines)

    lines.append("| Node | Search CPU | Search Memory |")
    lines.append("|---|---|---|")
    for v in result.search_nodes:
        lines.append(_search_row(v=v))
    lines.append("")

    blockers_by_node = [(v, _search_blockers(v=v)) for v in result.search_nodes]
    blockers_by_node = [(v, b) for v, b in blockers_by_node if b]
    if blockers_by_node:
        lines.append("### Blockers")
        lines.append("")
        for v, bs in blockers_by_node:
            lines.append(f"- **{v.hostname}**")
            for b in bs:
                lines.append(f"  - {b}")
        lines.append("")

    return "\n".join(lines)


# ---- top-level entrypoints ------------------------------------------------

def generate_markdown(result: ClusterRightsizingResult,
                      cluster_name: Optional[str] = None) -> str:
    """Build the full markdown report. `cluster_name` is purely cosmetic
    (used in the top-level heading); the verdict itself comes from
    `result`."""
    title = (
        f"# Rightsizing Report — {cluster_name}" if cluster_name
        else "# Rightsizing Report"
    )
    summary = [
        "## Summary",
        "",
        "| Fleet | Can scale down? |",
        "|---|---|",
        f"| Mongod | {_yes_no(result.can_scale_down)} |",
        f"| Search | {_yes_no(result.search_can_scale_down)} |",
        "",
    ]
    return "\n".join([
        title,
        "",
        *summary,
        _mongod_section(result=result),
        "",
        _search_section(result=result),
        "",
    ])


def write_report(result: ClusterRightsizingResult, path: str,
                 cluster_name: Optional[str] = None) -> None:
    """Render the markdown and write it to `path` (UTF-8). Overwrites."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(generate_markdown(result=result, cluster_name=cluster_name))


# ---- bulk (multi-cluster) summary ----------------------------------------

def _cell(flag: Optional[bool]) -> str:
    """True → 'down' (can scale down). Everything else → 'n/a' (cannot
    scale down OR fleet absent). Collapses the tri-state into the two
    labels the top-level summary uses."""
    return "down" if flag is True else "n/a"


def generate_bulk_summary_markdown(rows: list[dict]) -> str:
    """Top-level bulk markdown. One row per cluster in `rows`; each row
    carries {cluster, status, mongod, search, ?error} where mongod and
    search are bool|None (True → 'down', False/None → 'n/a'). Rows with
    status=='err' render both columns as 'err'. Prepends a totals block
    with the count of 'down' verdicts per fleet (err rows excluded from
    the denominator)."""
    ok_rows = [r for r in rows if r.get("status") != "err"]
    mongod_down = sum(1 for r in ok_rows if r.get("mongod") is True)
    search_down = sum(1 for r in ok_rows if r.get("search") is True)
    lines = [
        "# Rightsizing Bulk Summary",
        "",
        f"**Mongod can scale down**: {mongod_down} / {len(ok_rows)}  ",
        f"**Search can scale down**: {search_down} / {len(ok_rows)}",
        "",
        "| Cluster | Mongod | Search |",
        "|---|---|---|",
    ]
    for r in rows:
        cname = r["cluster"]
        if r.get("status") == "err":
            lines.append(f"| {cname} | err | err |")
            continue
        lines.append(f"| {cname} | {_cell(r['mongod'])} | {_cell(r['search'])} |")
    return "\n".join(lines) + "\n"


def write_bulk_summary_report(rows: list[dict], path: str) -> None:
    """Render the bulk summary markdown and write to `path` (UTF-8)."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(generate_bulk_summary_markdown(rows=rows))
