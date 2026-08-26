"""PaperMarketDataSource: the only way `PaperBrokerAdapter` ever learns
a reference price. Deliberately a caller-supplied dependency, not
something `broker.paper.*` fetches itself -- mirrors `broker.validation.
build_validated_order`'s existing "current_quantity must be supplied by
the caller" boundary (Phase 13): no module in `broker.*` imports
`data_infra.repository`/`backtest.asof` (point-in-time boundary test),
so `PaperBrokerAdapter` cannot reach for a bar itself. A caller builds a
`PaperMarketDataSource` from whatever point-in-time-safe accessor it
already has (`backtest.asof.AsOfDataView`, a fixture, or a test double)
and hands the finished object to the adapter.

`InMemoryPaperMarketDataSource` enforces point-in-time safety
structurally: `get_reference_bar` only ever considers bars whose
`PriceBar.available_time <= as_of` (the same field Phase 14's
`monitoring.metrics.compute_data_quality_metrics` already treats as the
point-in-time cutoff) -- a bar that would not yet have been available
at `as_of` can never be returned, no matter what is registered.

See docs/specifications/PHASE-15-paper-trading.md section 7.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol

from data_infra.models import PriceBar


class PaperMarketDataSource(Protocol):
    def get_reference_bar(self, security_id: str, *, as_of: datetime) -> Optional[PriceBar]: ...


class InMemoryPaperMarketDataSource:
    """Register bars up front (e.g. from a backtest fixture or a
    deterministic test scenario); `get_reference_bar` returns the latest
    *available* one -- `None` if nothing has become available yet, never
    a guessed/extrapolated price."""

    def __init__(self, bars: Optional[list[PriceBar]] = None) -> None:
        self._bars: dict[str, list[PriceBar]] = {}
        for bar in bars or []:
            self.register(bar)

    def register(self, bar: PriceBar) -> None:
        self._bars.setdefault(bar.security_id, []).append(bar)

    def get_reference_bar(self, security_id: str, *, as_of: datetime) -> Optional[PriceBar]:
        candidates = [b for b in self._bars.get(security_id, ()) if b.available_time <= as_of]
        if not candidates:
            return None
        return max(candidates, key=lambda b: (b.available_time, b.timestamp))
