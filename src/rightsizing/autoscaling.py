"""Turn cluster autoscaling settings into human-readable report notes.

Ported from scripts/rightsizing.py:392-419. Takes the autoscaling dict from
`config.autoscaling` (produced by src/extraction/common.summarize_config)
and the current verdict/trigger set; emits notes explaining how a manual
tier change might interact with Atlas autoscaling.
"""

import os
import sys

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from constants.verdicts import DISK_TRIGGERS  # noqa: E402


def autoscaling_notes(autoscaling, verdict, trigger_ids):
    """Return a list of note strings to append to the cluster's report.

    Args:
        autoscaling: {"compute": {...} or None, "disk": bool}
        verdict:     "scale_up" | "scale_down" | "no_change"
        trigger_ids: set of trigger IDs that fired for this cluster
    """
    notes = []
    compute = (autoscaling or {}).get("compute")
    if compute:
        span = f"{compute.get('minInstanceSize', '?')}-{compute.get('maxInstanceSize', '?')}"
        non_disk_triggers = set(trigger_ids) - set(DISK_TRIGGERS)
        if verdict == "scale_up" and non_disk_triggers:
            notes.append(
                f"Compute auto-scaling is ON ({span}). Atlas scales up by itself under "
                f"sustained load; if it hasn't, the cluster may already be at its max tier — "
                f"raising maxInstanceSize is likely the right change, not a manual tier bump."
            )
        elif verdict == "scale_down":
            if compute.get("scaleDownEnabled"):
                notes.append(
                    f"Compute auto-scaling with scale-down is ON ({span}). Atlas should "
                    f"downsize by itself and may override a manual change; lower "
                    f"minInstanceSize instead."
                )
            else:
                notes.append(
                    f"Compute auto-scaling is ON ({span}) but scale-down is disabled: "
                    f"enable scale-down or lower the tier manually."
                )
        else:
            notes.append(
                f"Compute auto-scaling is ON ({span}); a manual tier change may be overridden."
            )
    if (autoscaling or {}).get("disk") and "disk_space" in trigger_ids:
        notes.append(
            "Storage auto-scaling is ON: Atlas grows the disk automatically as it fills, "
            "so the disk-space trigger may resolve itself."
        )
    return notes
