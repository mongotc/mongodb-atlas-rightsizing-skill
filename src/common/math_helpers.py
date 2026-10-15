'''
Line up your numbers from smallest to largest. The percentile tells you where 
a given point along that line lands.

[10, 20,  30,  40,  50]
 0%  25%  50%  75%  100%
  
pctl(values, 0.0) gives 10 (the smallest)
pctl(values, 0.5) gives 30 (the middle)
pctl(values, 1.0) gives 50 (the largest)
'''
def pctl(values, p):
    """Linear-interpolated percentile at fraction p (0..1)."""
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DescriptiveStats:
    """Descriptive statistics over a sample window — p5/p50/p95/min/max/n.

    Returned by `summarize_raw` and `Series.stats()`. Immutable so callers
    can pass instances around without worrying about mutation. Values are
    rounded to two decimals to match what the raw-dict era produced."""
    p5: float
    p50: float
    p95: float
    min: float
    max: float
    n: int


def summarize_raw(points) -> Optional[DescriptiveStats]:
    """Descriptive stats over the values in [(ts, value), ...]. Returns
    None when the input has no values."""
    values = [v for _, v in points or []]
    if not values:
        return None
    return DescriptiveStats(
        p5=round(pctl(values, 0.05), 2),
        p50=round(pctl(values, 0.5),  2),
        p95=round(pctl(values, 0.95), 2),
        min=round(min(values),         2),
        max=round(max(values),         2),
        n=len(values),
    )


def combine_raw(a, b, fn):
    """Timestamp-aligned pairwise op across two [(ts, value), ...] series."""
    b_by_ts = dict(b or [])
    return [(ts, fn(v, b_by_ts[ts])) for ts, v in a or [] if ts in b_by_ts]
