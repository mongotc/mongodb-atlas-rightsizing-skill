from __future__ import annotations
from dataclasses import dataclass, field, replace
from typing import Callable, Optional, Sequence

from common.math_helpers import DescriptiveStats
from common.math_helpers import combine_raw as _combine_raw
from common.math_helpers import summarize_raw as _summarize_raw


# Multipliers to normalize Atlas raw values to bytes. Covers the units the
# measurements API has returned to us so far. PERCENT and SCALAR_* are not
# convertible to bytes — callers that ask for `.as_bytes()` on those get a
# ValueError, which is the right failure mode (silent coercion would hide
# the mistake).
_BYTES_MULTIPLIER = {
    "":           1,          # unknown unit — assume already bytes
    "BYTES":      1,
    "KILOBYTES":  1024,
    "MEGABYTES":  1024 ** 2,
    "GIGABYTES":  1024 ** 3,
    "TERABYTES":  1024 ** 4,
    # Rate variants map the same way; "/sec" is a dimension on top of bytes
    # and doesn't change the multiplier.
    "BYTES_PER_SECOND":     1,
    "KILOBYTES_PER_SECOND": 1024,
    "MEGABYTES_PER_SECOND": 1024 ** 2,
}

# Fallback when the extraction didn't preserve `unit` (older extractions +
# the current extractor as of 2026-10-14). Only metrics we've confirmed come
# through at non-byte scale. SYSTEM_MEMORY_USED+FREE sums to ~13.4M on an M40
# node, which only makes sense if KB (= ~13 GB). Other "bytes" metrics
# (CACHE_BYTES_*, SYSTEM_NETWORK_*, DISK_PARTITION_SPACE_*) empirically land
# at raw-byte magnitudes.
_RAW_UNIT_FALLBACK = {
    "SYSTEM_MEMORY_USED": "KILOBYTES",
    "SYSTEM_MEMORY_FREE": "KILOBYTES",
    "SYSTEM_MEMORY_AVAILABLE": "KILOBYTES",
}


Point = tuple[str, Optional[float]]


@dataclass(frozen=True)
class Series:
    """A named, unit-tagged sequence of (timestamp, value) points.

    `points` holds the raw samples the extraction produced; `None` values
    are preserved so callers can tell "metric reported, no value at that
    timestamp" apart from "sample missing from the window entirely" (the
    latter is just a shorter list)."""
    name: str
    points: tuple[Point, ...] = field(default_factory=tuple)
    unit: str = ""

    # ---- introspection ----------------------------------------------------

    def __bool__(self) -> bool:
        """Truthy only when at least one non-None value exists. Lets
        `if series.cpu_user:` read naturally for the common "do I have data"
        check without catching both the empty-list and all-nulls cases
        separately at every site."""
        return any(v is not None for _, v in self.points)

    def __len__(self) -> int:
        return len(self.points)

    @property
    def values(self) -> list[float]:
        """Non-None values only — the shape `summarize`/`pctl` want."""
        return [v for _, v in self.points if v is not None]

    @property
    def first_ts(self) -> Optional[str]:
        return self.points[0][0] if self.points else None

    @property
    def last_ts(self) -> Optional[str]:
        return self.points[-1][0] if self.points else None

    # ---- transformations (return new Series) ------------------------------

    def trimmed(self, start_ts: Optional[str] = None,
                end_ts: Optional[str] = None) -> "Series":
        """Keep only points within [start_ts, end_ts] (inclusive). Either
        bound can be None to leave that side open. No-op when both are
        None. Timestamps are ISO-8601 Zulu strings — they sort lexically,
        no parsing needed."""
        if not start_ts and not end_ts:
            return self
        return replace(self, points=tuple(
            p for p in self.points
            if (not start_ts or p[0] >= start_ts)
            and (not end_ts or p[0] <= end_ts)
        ))

    def combined(self, other: "Series", fn: Callable[[float, float], Optional[float]],
                 name: Optional[str] = None, unit: Optional[str] = None) -> "Series":
        """Join on timestamp and apply `fn(self_v, other_v)` sample by sample.
        Timestamps present in only one series are dropped (mirrors
        src/rightsizing/stats.combine)."""
        return Series(
            name=name if name is not None else f"{self.name}+{other.name}",
            points=tuple(_combine_raw(list(self.points), list(other.points), fn)),
            unit=unit if unit is not None else "",
        )

    def mapped(self, fn: Callable[[float], Optional[float]],
               name: Optional[str] = None, unit: Optional[str] = None) -> "Series":
        """Apply `fn(value)` to every non-None value; None values pass through
        unchanged. Returns a new Series — useful for scalar scaling (e.g. KB→B)
        without touching timestamps."""
        new_pts = tuple((ts, (fn(v) if v is not None else None)) for ts, v in self.points)
        return Series(
            name=name if name is not None else self.name,
            points=new_pts,
            unit=unit if unit is not None else self.unit,
        )

    def as_bytes(self) -> "Series":
        """Return a Series whose values are in bytes, converting from
        self.unit (or `_RAW_UNIT_FALLBACK[name]` when unit is unknown).

        Raises ValueError when the series isn't convertible to bytes
        (e.g. PERCENT) — silent coercion of a percent to bytes would be
        a bug waiting to happen."""
        unit = self.unit or _RAW_UNIT_FALLBACK.get(self.name, "")
        mult = _BYTES_MULTIPLIER.get(unit)
        if mult is None:
            raise ValueError(
                f"Series {self.name!r} unit {unit!r} is not convertible to bytes"
            )
        if mult == 1 and unit in ("BYTES", "BYTES_PER_SECOND", ""):
            return replace(self, unit=unit or "BYTES")
        new_unit = "BYTES_PER_SECOND" if unit.endswith("_PER_SECOND") else "BYTES"
        return self.mapped(fn=lambda v: v * mult, unit=new_unit)

    # ---- reductions -------------------------------------------------------

    def stats(self) -> Optional[DescriptiveStats]:
        """DescriptiveStats (p5/p50/p95/min/max/n) over the series' values,
        or None when the series is empty."""
        return _summarize_raw(list(self.points))

    # ---- constructors -----------------------------------------------------

    @classmethod
    def from_raw(cls, name: str, raw: Optional[Sequence[Point]], unit: str = "") -> "Series":
        """Build from the raw extraction shape ([(ts, value), ...]).
        `raw=None` and `raw=[]` both become an empty Series — downstream
        code checks `bool(series)` or `len(series)`."""
        return cls(name=name, points=tuple(raw or ()), unit=unit)

    @classmethod
    def empty(cls, name: str = "", unit: str = "") -> "Series":
        return cls(name=name, points=(), unit=unit)


def series_from_host(host: dict, name: str, unit: str = "") -> Series:
    """Pull a single metric out of an extraction's `host` dict as a Series.
    Keeps the "look up name, wrap in Series" pattern one-line at call sites."""
    return Series.from_raw(name=name, raw=host.get(name), unit=unit)
