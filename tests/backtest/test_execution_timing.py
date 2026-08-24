"""Category: Execution timing test.

See docs/specifications/PHASE-2-backtesting.md section 6.2 and ADR-0006:
a fill decided using checkpoint T's data must always execute at
checkpoint T+1's close, never T's own close and never an arbitrary later
checkpoint.
"""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, checkpoint, make_bars, make_security, trading_days

from backtest.enums import OrderStatus
from backtest.engine import BacktestConfig, BacktestEngine
from backtest.strategy import BuyAndHoldStrategy


class TestExecutionTiming:
    def test_every_fill_executes_strictly_after_its_decision(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 12))
        bars = make_bars("AAA", days, [100.0 + i for i in range(len(days))])
        repo = build_repository(bars=bars, securities=[make_security("AAA", "AAA")])

        config = BacktestConfig(
            market="US_EQUITY", start_date=days[0], end_date=days[-1],
            initial_capital=10_000.0, security_ids=("AAA",),
        )
        result = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"])).run()

        assert len(result.fills) >= 1
        for fill in result.fills:
            assert fill.execution_time > fill.decision_time

    def test_fill_reference_price_is_the_next_checkpoints_close_not_the_decision_days(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 12))
        # Day 1 close = 100, day 2 close = 101 — a modest but unambiguous
        # jump (small enough that BuyAndHoldStrategy's cost safety margin
        # still comfortably affords the fill) so we can tell which bar
        # actually priced the fill without the order being rejected for
        # insufficient cash at the higher price.
        closes = [100.0] + [101.0] * (len(days) - 1)
        bars = make_bars("AAA", days, closes)
        repo = build_repository(bars=bars, securities=[make_security("AAA", "AAA")])

        config = BacktestConfig(
            market="US_EQUITY", start_date=days[0], end_date=days[-1],
            initial_capital=10_000.0, security_ids=("AAA",),
        )
        result = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"])).run()

        assert len(result.fills) == 1
        fill = result.fills[0]
        # Decision happened on day[0] (close=100); execution must price
        # off day[1]'s close (101), not day[0]'s.
        assert fill.reference_price == 101.0
        assert fill.execution_time.date() == days[1]
        assert fill.decision_time.date() == days[0]

    def test_no_fill_ever_shares_the_decision_checkpoints_own_bar(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 12))
        bars = make_bars("AAA", days, [100.0 + i * 2 for i in range(len(days))])
        repo = build_repository(bars=bars, securities=[make_security("AAA", "AAA")])

        config = BacktestConfig(
            market="US_EQUITY", start_date=days[0], end_date=days[-1],
            initial_capital=10_000.0, security_ids=("AAA",),
        )
        result = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"])).run()

        for fill in result.fills:
            assert fill.execution_time.date() != fill.decision_time.date()

    def test_order_generated_on_final_checkpoint_is_not_executed(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 3))  # only 2 checkpoints
        bars = make_bars("AAA", days, [100.0, 101.0])
        repo = build_repository(bars=bars, securities=[make_security("AAA", "AAA")])

        from backtest.enums import OrderSide
        from backtest.strategy import OrderIntent

        class _BuyEveryStep:
            version = "buy_every_step_v1"

            def generate_orders(self, as_of_time, data, portfolio):
                return [OrderIntent("AAA", OrderSide.BUY, 1.0)]

        config = BacktestConfig(
            market="US_EQUITY", start_date=days[0], end_date=days[-1],
            initial_capital=10_000.0, security_ids=("AAA",),
        )
        result = BacktestEngine(repo, config, _BuyEveryStep()).run()

        # One order on day[0] should fill using day[1]'s close; the order
        # generated on day[1] (the final checkpoint) has no future bar to
        # execute against and must be marked NOT_EXECUTED, not fabricated
        # a price.
        not_executed = [o for o in result.orders if o.status == OrderStatus.NOT_EXECUTED]
        assert len(not_executed) == 1
        assert any(i.check == "end_of_backtest" for i in result.integrity.issues)
