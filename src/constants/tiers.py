"""Atlas tier reference data.

Not a risk-tolerance knob — these are facts from MongoDB documentation.
Adjust only when Atlas changes them.

Source: "Connection Limits and Cluster Tier"
https://www.mongodb.com/docs/atlas/reference/atlas-limits/ (checked 2026-09-22)
"""

import re


# Max concurrent connections per node, (low, high) across cloud-provider /
# cluster-class variants. The Atlas docs list several tables that disagree for
# some tiers (M40: 4000 vs 6000, M80: 64000 vs 96000). The rightsizing
# connections check uses the low end so it errs toward flagging; the report
# quotes the range.
# R-series (low-CPU) and _NVME variants map to their M-number.
TIER_MAX_CONNECTIONS = {
    "M10": (1500, 1500), "M20": (3000, 3000), "M30": (3000, 3000), "M40": (4000, 6000),
    "M50": (16000, 16000), "M60": (32000, 32000), "M80": (64000, 96000),
    "M140": (96000, 96000), "M200": (128000, 128000), "M300": (128000, 128000),
    "M400": (128000, 128000), "M600": (128000, 128000), "M700": (128000, 128000),
}

# Tiers without full hardware measurements — no rightsizing verdict possible.
SHARED_TIERS = {"M0", "M2", "M5", "FLEX", "SERVERLESS"}



def normalize_tier(tier):
    """'M30_NVME' or 'R40' -> 'M30' / 'M40', so R-series and _NVME variants
    look up the same connection limit as their base M-number."""
    m = re.match(r"^[MR](\d+)", tier or "")
    return f"M{m.group(1)}" if m else None


# Mapping rules verified against the Atlas Admin API v2 OpenAPI spec on
# 2026-10-06 (HardwareSpec enums for AWS/GCP/Azure). Keep in sync with
# https://www.mongodb.com/docs/api/doc/atlas-admin-api-v2.json when Atlas
# adds new generations or suffixes.
_INSTANCE_SIZE_RE = re.compile(r"^(?P<prefix>[MR])(?P<num>\d+)$")


def parse_instance_size(size):
    """Decompose an Atlas instanceSize string into its four axes.

    Returns (base_tier, class, storage, generation). Any failure to parse
    returns (None, None, None, None).

    Examples:
      'M40'            -> ('M40', 'general', 'standard', 'gen1')
      'R30'            -> ('M30', 'low_cpu', 'standard', 'gen1')
      'M40_NVME'       -> ('M40', 'general', 'nvme',     'gen1')  # AWS only
      'M40_GEN_2'      -> ('M40', 'general', 'standard', 'gen2')
      'R40_GEN_2'      -> ('M40', 'low_cpu', 'standard', 'gen2')
      'M40_NVME_GEN_2' -> ('M40', 'general', 'nvme',     'gen2')  # AWS only
    """
    if not size:
        return (None, None, None, None)
    s = str(size).upper()
    generation = "gen1"
    if s.endswith("_GEN_2"):
        generation = "gen2"
        s = s[:-6]
    storage = "standard"
    if s.endswith("_NVME"):
        storage = "nvme"
        s = s[:-5]
    m = _INSTANCE_SIZE_RE.match(s)
    if not m:
        return (None, None, None, None)
    tier_class = "general" if m.group("prefix") == "M" else "low_cpu"
    base_tier = f"M{m.group('num')}"
    return (base_tier, tier_class, storage, generation)
