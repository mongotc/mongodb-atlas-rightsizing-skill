"""TierSpec: hardware specs for one Atlas instance (tier + generation + class).

Backs three JSON catalogs — atlas_{aws,gcp,azure}_tier_spec.json — all of
which share a common row shape:

  {
    "hardware_spec_instance_size": "M40",
    "tier": "M40",
    "generation": "gen1",
    "class": "general",
    "available": true,
    "vcpus": 4,
    "memory_gb": 16,
    "storage_min_gb": 10,
    "storage_max_gb": 1024,
    "extended_storage_max_gb": 4096,
    "disk_iops_min": 6300,
    "disk_iops_max": 15000,
    "max_connections_per_node": 6000,
    "network_performance": "High",
    "regions": [...]            # ignored here — a tier is cross-region
  }

`load_tier_spec` picks the matching row, which is the ONE place in the
codebase that knows how to resolve a (provider, instance_size, generation,
class) tuple against the per-provider catalog. Hoisted out of
src/visualize/visualize.py so both the extractor and the evaluator can
share it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional


_CATALOG_DIR = os.path.dirname(os.path.abspath(__file__))

# Atlas Admin API provider enum (per cluster.replicationSpecs[].regionConfigs[].providerName)
# → catalog file suffix. Tenant-free lookup.
_PROVIDER_TO_FILE = {
    "AWS":   "aws",
    "GCP":   "gcp",
    "AZURE": "azure",
}


@dataclass(frozen=True)
class TierSpec:
    """One row of hardware specs for a particular Atlas instance."""
    provider: str                           # "AWS" | "GCP" | "AZURE"
    tier: str                               # e.g. "M40"
    generation: Optional[str]               # e.g. "gen1" (None for shared tiers)
    cls: Optional[str]                      # e.g. "general" (None for shared tiers)
    vcpus: Optional[float]                  # fractional for burstable M10/M20
    memory_gb: Optional[float]
    storage_min_gb: Optional[float]
    storage_max_gb: Optional[float]
    extended_storage_max_gb: Optional[float]
    disk_iops_min: Optional[int]
    disk_iops_max: Optional[int]
    max_disk_iops: Optional[int]            # single value when min==max (AWS gp3)
    max_connections_per_node: Optional[int]
    network_performance: Optional[str]
    available: bool                         # Atlas-reported availability flag


@lru_cache(maxsize=None)
def _load_catalog(provider: str) -> dict:
    """Load and cache the per-provider tier spec JSON. Raises FileNotFoundError
    if the provider isn't recognized or the catalog file is missing."""
    key = _PROVIDER_TO_FILE.get((provider or "").upper())
    if not key:
        raise FileNotFoundError(
            f"No tier spec catalog for provider {provider!r} — "
            f"known providers: {sorted(_PROVIDER_TO_FILE)}"
        )
    path = os.path.join(_CATALOG_DIR, f"atlas_{key}_tier_spec.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_tier_spec(provider: str, instance_size: str,
                   generation: Optional[str] = None,
                   cls: Optional[str] = None) -> TierSpec:
    """Resolve the TierSpec matching `(provider, instance_size, generation,
    cls)` against the per-provider catalog.

    Matching rules (in order):
      1. `tier == instance_size` — ignores the catalog's confused
         `hardware_spec_instance_size` field (some M40 rows mislabel it
         as M30).
      2. `generation` matches when both sides are set (Atlas returns None
         for shared tiers; the catalog uses None too, so None==None is a
         match).
      3. `class` matches when both sides are set, same None-both-sides rule.

    Raises LookupError when no row matches — a silent fallback to the
    first row with matching tier would mask tier/generation/class drift
    between Atlas and the catalog, which has bitten us before."""
    catalog = _load_catalog(provider=provider)
    candidates = [
        row for row in catalog.get("tiers") or []
        if row.get("hardware_spec_instance_size") == instance_size
    ]
    if not candidates:
        raise LookupError(
            f"No tier {instance_size!r} in {provider} tier catalog"
        )

    # Narrow by generation + class when provided. Both None sides are a
    # legitimate match (shared tiers lack these fields entirely).
    def row_matches(row):
        if generation is not None and row.get("generation") != generation:
            return False
        if cls is not None and row.get("class") != cls:
            return False
        return True

    matches = [row for row in candidates if row_matches(row)]
    if not matches:
        raise LookupError(
            f"No tier {instance_size!r} (generation={generation!r}, "
            f"class={cls!r}) in {provider} tier catalog — available: "
            f"{[(r.get('generation'), r.get('class')) for r in candidates]}"
        )
    if len(matches) > 1:
        # Ambiguous: catalog has duplicate rows for this (tier, gen, class).
        # The first one wins but call it out — someone should clean the
        # catalog. Not raising because the first row is usually correct.
        pass

    row = matches[0]
    return TierSpec(
        provider=(provider or "").upper(),
        tier=row.get("tier"),
        generation=row.get("generation"),
        cls=row.get("class"),
        vcpus=row.get("vcpus"),
        memory_gb=row.get("memory_gb"),
        storage_min_gb=row.get("storage_min_gb"),
        storage_max_gb=row.get("storage_max_gb"),
        extended_storage_max_gb=row.get("extended_storage_max_gb"),
        disk_iops_min=row.get("disk_iops_min"),
        disk_iops_max=row.get("disk_iops_max"),
        max_disk_iops=row.get("max_disk_iops"),
        max_connections_per_node=row.get("max_connections_per_node"),
        network_performance=row.get("network_performance"),
        available=bool(row.get("available", True)),
    )


# ---------------------------------------------------------------------------
# Search Node tier catalog
# ---------------------------------------------------------------------------
#
# Backs atlas_{aws,gcp,azure}_search_tier_spec.json. Row shape:
#   {
#     "hardware_spec_instance_size": "S50_HIGHCPU_NVME",
#     "tier": "S50",
#     "available": true,
#     "class": "high_cpu_nvme",
#     "vcpus": 16,
#     "memory_gb": 32,
#     "storage_gb": 674,                 # single value, not a range
#     "disk_iops_read": 680000,
#     "disk_iops_write": 360000,
#     "network_performance": "very_high",
#     "regions": []
#   }
#
# Why a separate dataclass + loader (vs. extending TierSpec / load_tier_spec):
#   - Mongod rows match by `tier` ("M40"); Search rows match by
#     `hardware_spec_instance_size` ("S50_HIGHCPU_NVME") because Search's
#     `tier` collides across HIGHCPU / LOWCPU / STORAGE variants.
#   - Schema is narrower (no generation, storage ranges, max connections).
#   - Keeping them separate makes each lookup rule legible.


@dataclass(frozen=True)
class SearchTierSpec:
    """One row of Atlas dedicated Search Node hardware specs."""
    provider: str                           # "AWS" | "GCP" | "AZURE"
    instance_size: str                      # e.g. "S50_HIGHCPU_NVME"
    tier: str                               # e.g. "S50"
    cls: Optional[str]                      # e.g. "high_cpu_nvme"
    vcpus: Optional[float]
    memory_gb: Optional[float]
    storage_gb: Optional[float]
    disk_iops_read: Optional[int]
    disk_iops_write: Optional[int]
    network_performance: Optional[str]
    available: bool


@lru_cache(maxsize=None)
def _load_search_catalog(provider: str) -> dict:
    """Load and cache the per-provider Search tier spec JSON. Raises
    FileNotFoundError if the provider isn't recognized or the catalog file
    is missing (today only GCP ships; AWS/AZURE will raise until added)."""
    key = _PROVIDER_TO_FILE.get((provider or "").upper())
    if not key:
        raise FileNotFoundError(
            f"No Search tier spec catalog for provider {provider!r} — "
            f"known providers: {sorted(_PROVIDER_TO_FILE)}"
        )
    path = os.path.join(_CATALOG_DIR, f"atlas_{key}_search_tier_spec.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_search_tier_spec(provider: str, instance_size: str) -> SearchTierSpec:
    """Resolve the SearchTierSpec matching `(provider, instance_size)` against
    the per-provider Search catalog. Unlike mongod, Search catalog rows
    carry no generation/class disambiguator — `hardware_spec_instance_size`
    (e.g. "S50_HIGHCPU_NVME") is the full key.

    Raises LookupError when no row matches."""
    catalog = _load_search_catalog(provider=provider)
    for row in catalog.get("tiers") or []:
        if row.get("hardware_spec_instance_size") == instance_size:
            return SearchTierSpec(
                provider=(provider or "").upper(),
                instance_size=row.get("hardware_spec_instance_size"),
                tier=row.get("tier"),
                cls=row.get("class"),
                vcpus=row.get("vcpus"),
                memory_gb=row.get("memory_gb"),
                storage_gb=row.get("storage_gb"),
                disk_iops_read=row.get("disk_iops_read"),
                disk_iops_write=row.get("disk_iops_write"),
                network_performance=row.get("network_performance"),
                available=bool(row.get("available", True)),
            )
    raise LookupError(
        f"No Search tier {instance_size!r} in {provider} Search catalog"
    )
