"""Cross-package constants (Atlas facts, verdict identifiers).

Not tunable knobs — these are either MongoDB documentation facts (tier tables)
or wire-format identifiers (verdict names in report JSON). Adjust only when
Atlas changes them or you're consciously reshaping the report schema.

Modules:
  tiers     — TIER_MAX_CONNECTIONS, SHARED_TIERS, normalize_tier
  verdicts  — DISK_TRIGGERS, EVALUATED_VERDICTS, VERDICT_LABELS
"""
