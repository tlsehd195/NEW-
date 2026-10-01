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
from data_infra.universe import BENCHMARK_SYMBOL

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


class MembershipFilteredDataView(AsOfDataView):
    """An AsOfDataView that shows a Strategy price bars only for the
    securities in `members`, which the engine resets to the as-of
    universe at every checkpoint (ADR-0224). A strategy built over every
    name that was ever in the index then ranks only the names that were
    members on that date, without knowing about membership itself.

    The benchmark (SPY) is never a member but stays visible: beta-style
    factor scores read it next to each member's bars, and hiding it left
    them all without a score. It is a reference series, not a tradable
    name, since strategies only rank the security_ids they were built
    over."""

    _ALWAYS_VISIBLE = frozenset({BENCHMARK_SYMBOL})

    def __init__(self, repository: DataRepository, clock: BacktestClock) -> None:
        super().__init__(repository, clock)
        self.members: frozenset[str] = frozenset()

    def get_bars(self, security_id: str, start: datetime, end: datetime) -> list[PriceBar]:
        if security_id not in self.members and security_id not in self._ALWAYS_VISIBLE:
            return []
        return super().get_bars(security_id, start, end)
