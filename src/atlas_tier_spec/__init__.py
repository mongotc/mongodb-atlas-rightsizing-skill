"""Atlas tier catalog — hardware specs for every (provider, instance_size,
generation, class) tuple. Backing JSON lives alongside this module."""

from atlas_tier_spec.tier_spec import TierSpec, load_tier_spec

__all__ = ["TierSpec", "load_tier_spec"]
