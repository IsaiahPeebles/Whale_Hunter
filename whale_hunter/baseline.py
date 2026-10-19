"""Per-market behavioral baseline, computed on demand from stored trades (CONTEXT §6)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median

BUCKETS = (60, 300, 900, 3600)  # seconds


def percentile(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    i = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (i - lo)


@dataclass
class Baseline:
    n_trades: int = 0
    span_s: float = 0.0              # seconds of observed history
    median_trade: float = 0.0
    p95_trade: float = 0.0
    p99_trade: float = 0.0
    sizes: list = field(default_factory=list)          # sorted trade notionals
    avg_volume: dict = field(default_factory=dict)     # bucket seconds -> mean volume per bucket
    bucket_volumes: dict = field(default_factory=dict)  # bucket seconds -> sorted bucket volumes
    last_price: float | None = None  # last YES price before the evaluation window

    def size_percentile(self, x):
        return _rank(self.sizes, x)

    def volume_percentile(self, bucket_s, x):
        return _rank(self.bucket_volumes.get(bucket_s, []), x)

    def max_volume(self, bucket_s):
        vols = self.bucket_volumes.get(bucket_s)
        return vols[-1] if vols else 0.0


def _rank(sorted_vals, x):
    if not sorted_vals:
        return None
    lo, hi = 0, len(sorted_vals)
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_vals[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo / len(sorted_vals)


def build_baseline(history: list[dict], window_start: float) -> Baseline:
    """history: trades strictly before window_start, sorted by ts."""
    if not history:
        return Baseline()
    sizes = sorted(t["notional"] for t in history)
    first = history[0]["ts"]
    span = max(window_start - first, 60.0)
    b = Baseline(
        n_trades=len(history),
        span_s=span,
        median_trade=median(sizes),
        p95_trade=percentile(sizes, 0.95),
        p99_trade=percentile(sizes, 0.99),
        sizes=sizes,
        last_price=history[-1]["price"],
    )
    total = sum(sizes)
    for bs in BUCKETS:
        n_buckets = max(int(math.ceil(span / bs)), 1)
        vols = [0.0] * n_buckets  # empty periods count as zero volume
        for t in history:
            i = min(int((window_start - t["ts"]) // bs), n_buckets - 1)
            vols[i] += t["notional"]
        b.avg_volume[bs] = total / (span / bs) if span >= bs else total
        b.bucket_volumes[bs] = sorted(vols)
    return b
