"""PricePoint: the normalized time-series shape every regime feature
function operates on, plus adapters from Phase 1's two source types
(`PriceBar`, `BenchmarkPoint`).

Both a single security (`PriceBar`) and a benchmark/index series
(`BenchmarkPoint`) reduce to the same (timestamp, price, volume,
data_version) shape, so the exact same feature math (features.py) runs
for either subject kind without duplicating it per type (Phase 5 spec
section 2 -- "Market Regime" is as much a benchmark-level concept as a
per-security one).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from data_infra.models import BenchmarkPoint, PriceBar


@dataclass(frozen=True)
class PricePoint:
    timestamp: datetime
    price: float
    volume: Optional[float]  # None for a benchmark (BenchmarkPoint has no volume)
    data_version: str


def bars_to_price_points(bars: Sequence[PriceBar]) -> list[PricePoint]:
    """Uses `adjusted_close` when present (falls back to raw `close`),
    the same choice Phase 2's SimpleMomentumStrategy already makes for
    signal calculation (Phase 2 spec section 8.4) -- a regime feature is
    a signal-quality input, not a cash/execution figure, so the same
    reasoning applies: a split should not look like a price crash."""
    return [
        PricePoint(
            timestamp=b.timestamp,
            price=b.adjusted_close if b.adjusted_close is not None else b.close,
            volume=b.volume,
            data_version=b.provenance.data_version,
        )
        for b in sorted(bars, key=lambda b: b.timestamp)
    ]


def benchmark_to_price_points(points: Sequence[BenchmarkPoint]) -> list[PricePoint]:
    return [
        PricePoint(
            timestamp=p.timestamp, price=p.level, volume=None, data_version=p.provenance.data_version,
        )
        for p in sorted(points, key=lambda p: p.timestamp)
    ]
