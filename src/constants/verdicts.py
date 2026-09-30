"""Verdict identifiers used across the rightsizing module.

Not tunable — changing these strings breaks every consumer of the report JSON
(dashboards, merge_verdict.py, downstream diff tools).
"""


# Trigger IDs that are disk-only. When ALL fired triggers are in this set, the
# verdict becomes 'disk_iops_only' instead of 'scale_up' — the fix is a bigger
# disk / more provisioned IOPS, not a compute-tier bump.
DISK_TRIGGERS = frozenset({
    "iops",
    "disk_space",
    "disk_latency_read",
    "disk_latency_write",
})

# Verdicts produced by an actual metric evaluation (as opposed to
# informational rows like 'not_supported' for shared tiers or
# 'not_applicable' for mongos routers).
EVALUATED_VERDICTS = frozenset({
    "scale_up",
    "disk_iops_only",
    "scale_down_candidate",
    "no_change",
})

VERDICT_LABELS = {
    "scale_up":             "SCALE UP",
    "disk_iops_only":       "CHANGE DISK / IOPS ONLY",
    "scale_down_candidate": "SCALE DOWN CANDIDATE",
    "no_change":            "NO CHANGE",
    "insufficient_data":    "INSUFFICIENT DATA",
    "not_supported":        "NOT SUPPORTED",
    "not_applicable":       "NOT APPLICABLE",
    "error":                "ERROR",
}
