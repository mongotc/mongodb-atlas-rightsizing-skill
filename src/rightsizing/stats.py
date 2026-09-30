"""Percentile and time-series helpers.

Port of the statistics primitives from scripts/rightsizing.py:426-468 —
kept identical so verdicts from this module match the legacy script for the
same input data.
"""


def pctl(values, p):
    """Linear-interpolated percentile of `values` at fraction `p` (0..1)."""
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def summarize(points):
    """{p5, p50, p95, max, n} over the values in a [(ts, value), ...] series."""
    values = [v for _, v in points or []]
    if not values:
        return None
    return {
        "p5": round(pctl(values, 0.05), 2),
        "p50": round(pctl(values, 0.5), 2),
        "p95": round(pctl(values, 0.95), 2),
        "max": round(max(values), 2),
        "n": len(values),
    }


def combine(a, b, fn):
    """Join two [(ts, value), ...] series on timestamp; apply fn(a_v, b_v)."""
    b_by_ts = dict(b or [])
    return [(ts, fn(v, b_by_ts[ts])) for ts, v in a or [] if ts in b_by_ts]


def breach_days(points, threshold, last_n_days=7):
    """How many of the last `last_n_days` UTC days have their own p95 above
    `threshold`. Used for the sustained-breach check on CPU / IOPS /
    disk-space triggers."""
    by_day = {}
    for ts, v in points:
        by_day.setdefault(ts[:10], []).append(v)
    recent = sorted(by_day)[-last_n_days:]
    return sum(1 for day in recent if pctl(by_day[day], 0.95) > threshold)


def sustained_days_required(window_days, default_days=3):
    """Days a threshold must breach to count as sustained.

    Full 7-day window: `default_days`. Shorter windows scale proportionally
    (with a minimum of 1) so a 3-day window doesn't demand 3 days of breach."""
    if window_days >= 7:
        return default_days
    return max(1, -(-default_days * int(window_days) // 7))
