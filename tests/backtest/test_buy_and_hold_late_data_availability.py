"""Category: Regression test -- BuyAndHoldStrategy must not permanently
give up after a single checkpoint where no data was available yet.

Found via a real ingestion run (Phase 24 follow-up): `US_EQUITY`
(`src/data_infra/calendar.py`) is explicitly documented as "NOT a
production-accurate, multi-year holiday calendar" -- it has zero
holidays registered for 2023 and only three for 2024. Against a real
2023-2024 backtest window, `BacktestConfig.start_date` can therefore
land on a calendar-valid-but-actually-a-real-market-holiday date (e.g.
2023-01-02, the observed New Year's Day holiday since 2023-01-01 fell
on a Sunday) for which no real provider ever has a bar. Before this
fix, `BuyAndHoldStrategy.generate_orders` unconditionally set
`self._invested = True` on its very first call regardless of whether it
actually found anything to buy -- so a single "no data yet" first
checkpoint permanently disabled the strategy for the rest of the
backtest, even though real data existed on every subsequent day. This
produced a real, observed result of zero trades over a real 2-year
window."""

from __future__ import annotations

from datetime import date, timedelta

from backtest_helpers import build_repository, make_bars, make_security, trading_days

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.strategy import BuyAndHoldStrategy


class TestBuyAndHoldSurvivesDataMissingOnFirstCheckpoint:
    def test_invests_on_the_first_checkpoint_that_actually_has_data(self) -> None:
        all_days = trading_days(date(2023, 1, 2), date(2023, 1, 20))
        # The backtest window includes 2023-01-02 as its first checkpoint
        # (a calendar-valid trading day per the simplistic US_EQUITY
        # calendar), but the security's own price history does not
        # start until several days later -- exactly the "calendar says
        # trading day, no provider ever has a bar for it" gap this
        # regression targets. No bar exists at all for the first two
        # calendar days.
        bars_start_index = 3
        available_days = all_days[bars_start_index:]
        bars = make_bars("AAA", available_days, [100.0 + i for i in range(len(available_days))])
        repo = build_repository(bars=bars, securities=[make_security("AAA", "AAA")])

        config = BacktestConfig(
            market="US_EQUITY", start_date=all_days[0], end_date=all_days[-1],
            initial_capital=10_000.0, security_ids=("AAA",),
        )
        result = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"])).run()

        assert len(result.fills) >= 1, (
            "BuyAndHoldStrategy must still invest once real data becomes "
            "available, not give up permanently after an empty first checkpoint"
        )
        # The first fill must not be priced before data actually existed.
        assert result.fills[0].execution_time.date() >= available_days[0]

    def test_still_invests_exactly_once_not_repeatedly(self) -> None:
        """The fix must not turn this into a repeated-rebalance strategy
        -- once it successfully invests, it must never trade again."""
        all_days = trading_days(date(2023, 1, 2), date(2023, 2, 1))
        bars_start_index = 2
        available_days = all_days[bars_start_index:]
        bars = make_bars("AAA", available_days, [100.0] * len(available_days))
        repo = build_repository(bars=bars, securities=[make_security("AAA", "AAA")])

        config = BacktestConfig(
            market="US_EQUITY", start_date=all_days[0], end_date=all_days[-1],
            initial_capital=10_000.0, security_ids=("AAA",),
        )
        result = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"])).run()

        buy_fills = [f for f in result.fills if f.side.value == "BUY"]
        assert len(buy_fills) == 1

    def test_data_available_from_day_one_still_invests_immediately(self) -> None:
        """No regression for the ordinary case: data available on the
        very first checkpoint still results in an immediate buy, same
        as before this fix."""
        days = trading_days(date(2024, 1, 2), date(2024, 1, 12))
        bars = make_bars("AAA", days, [100.0 + i for i in range(len(days))])
        repo = build_repository(bars=bars, securities=[make_security("AAA", "AAA")])

        config = BacktestConfig(
            market="US_EQUITY", start_date=days[0], end_date=days[-1],
            initial_capital=10_000.0, security_ids=("AAA",),
        )
        result = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"])).run()

        assert len(result.fills) >= 1
        assert result.fills[0].decision_time.date() == days[0]
