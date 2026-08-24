"""AsOfDataView: the only data access surface a Strategy ever receives.

See docs/specifications/PHASE-2-backtesting.md section 3.2. Every method
here has the exact same name as the corresponding data_infra.DataRepository
method, minus the `as_of_time` parameter — that value is read from the
BacktestClock on every call. There is no method, override, or parameter
through which a well-behaved Strategy implementation could request data
beyond the clock's current checkpoint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from data_infra.calendar import TradingCalendar
from data_infra.models import BenchmarkPoint, CorporateAction, PriceBar, SecurityMaster
from data_infra.repository import DataRepository

from backtest.clock import BacktestClock


class AsOfDataView:
    def __init__(self, repository: DataRepository, clock: BacktestClock) -> None:
        self._repository = repository
        self._clock = clock

    @property
    def current_time(self) -> datetime:
        """Read-only. A Strategy can observe "now" but has no way to pass
        a different value into any query method below."""
        return self._clock.current_time

    def get_bars(self, security_id: str, start: datetime, end: datetime) -> list[PriceBar]:
        return self._repository.get_bars(security_id, start, end, as_of_time=self._clock.current_time)

    def get_security(self, security_id: str) -> Optional[SecurityMaster]:
        return self._repository.get_security(security_id, as_of_time=self._clock.current_time)

    def get_corporate_actions(
        self, security_id: str, start: datetime, end: datetime
    ) -> list[CorporateAction]:
        return self._repository.get_corporate_actions(
            security_id, start, end, as_of_time=self._clock.current_time
        )

    def get_benchmark(self, benchmark_id: str, start: datetime, end: datetime) -> list[BenchmarkPoint]:
        return self._repository.get_benchmark(
            benchmark_id, start, end, as_of_time=self._clock.current_time
        )

    def get_universe(self, market: str, universe: str) -> list[str]:
        return self._repository.get_universe(market, universe, as_of_time=self._clock.current_time)

    def get_trading_calendar(self, market: str) -> TradingCalendar:
        # Not point-in-time sensitive (Phase 1 spec section 12) — passed
        # through unchanged.
        return self._repository.get_trading_calendar(market)
