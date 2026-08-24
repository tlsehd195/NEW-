"""BacktestClock: drives the simulation forward one trading day at a time.

See docs/specifications/PHASE-2-backtesting.md section 3, section 6.2
(execution timing), and ADR-0006.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from data_infra.calendar import TradingCalendar


def build_daily_checkpoints(
    calendar: TradingCalendar,
    start_date: date,
    end_date: date,
    *,
    checkpoint_time: time = time(20, 0),
    tz: timezone = timezone.utc,
) -> tuple[datetime, ...]:
    """One checkpoint per trading day in [start_date, end_date], at
    `checkpoint_time` in `tz`. This mirrors the convention Phase 1's mock
    data used for `available_time` (end-of-session, ~20:00 UTC for US
    equities) — see Phase 2 spec section 6.2 for why the checkpoint
    represents "this day's bar has become available," not an earlier
    intraday moment."""
    checkpoints: list[datetime] = []
    current = start_date
    one_day = timedelta(days=1)
    while current <= end_date:
        if calendar.is_trading_day(current):
            checkpoints.append(
                datetime(current.year, current.month, current.day, tzinfo=tz).replace(
                    hour=checkpoint_time.hour, minute=checkpoint_time.minute
                )
            )
        current += one_day
    return tuple(checkpoints)


@dataclass
class BacktestClock:
    """Simulation clock. `current_time` is the only notion of "now" any
    Phase 2 component is allowed to use — see AsOfDataView (asof.py),
    which binds every DataRepository query to this value."""

    checkpoints: tuple[datetime, ...]
    index: int = field(default=0)

    def __post_init__(self) -> None:
        if not self.checkpoints:
            raise ValueError("BacktestClock requires at least one checkpoint")
        for a, b in zip(self.checkpoints, self.checkpoints[1:]):
            if b <= a:
                raise ValueError("BacktestClock checkpoints must be strictly increasing")

    @property
    def current_time(self) -> datetime:
        return self.checkpoints[self.index]

    @property
    def current_date(self) -> date:
        return self.current_time.date()

    @property
    def is_finished(self) -> bool:
        return self.index >= len(self.checkpoints)

    @property
    def has_next(self) -> bool:
        return self.index + 1 < len(self.checkpoints)

    def peek_next(self) -> Optional[datetime]:
        if not self.has_next:
            return None
        return self.checkpoints[self.index + 1]

    def advance(self) -> None:
        if self.is_finished:
            raise StopIteration("BacktestClock has no more checkpoints")
        self.index += 1
