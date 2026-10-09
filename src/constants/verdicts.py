"""Verdict identifiers used across the rightsizing module.

The verdict space is intentionally a tiny set: scale_up, scale_down, no_change.
Nuance (disk-only triggers, shared tier skips, mongos informational rows,
insufficient-data cases) lives in the `reasons` text, not in verdict identifiers.
Downstream consumers switch on these three strings.

Not tunable — changing these strings breaks every consumer of the report JSON
(dashboards, merge_verdict.py, downstream diff tools).
"""


# Trigger IDs that are disk-only. When ALL fired triggers are in this set the
# evaluator still emits `scale_up`, but adds a reason noting the fix is a
# bigger disk / more provisioned IOPS, not a compute-tier bump.
DISK_TRIGGERS = frozenset({
    "iops",
    "disk_space",
    "disk_latency_read",
    "disk_latency_write",
})

EVALUATED_VERDICTS = frozenset({
    "scale_up",
    "scale_down",
    "no_change",
})

VERDICT_LABELS = {
    "scale_up":   "SCALE UP",
    "scale_down": "SCALE DOWN",
    "no_change":  "NO CHANGE",
    "error":      "ERROR",
}
