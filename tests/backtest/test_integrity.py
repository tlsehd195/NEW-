"""Category: Duplicate order test.
Category: Integrity failure test.

See docs/specifications/PHASE-2-backtesting.md section 12: any ERROR or
CRITICAL integrity issue must gate is_valid_performance to False, and
the failure must be inspectable, not silently discarded or crashed on.
"""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, checkpoint, make_bars, make_security, trading_days, utc

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.enums import IntegritySeverity, IntegrityStatus, OrderSide
from backtest.fills import Fill
from backtest.integrity import BacktestIntegrityChecker
from backtest.portfolio import PortfolioAccounting
from backtest.strategy import OrderIntent


class TestDuplicateOrder:
    def test_checker_flags_duplicate_intents_same_step(self) -> None:
        checker = BacktestIntegrityChecker()
        intents = [
            OrderIntent("AAA", OrderSide.BUY, 10.0),
            OrderIntent("AAA", OrderSide.BUY, 5.0),  # duplicate: same security+side, same step
        ]
        checker.check_duplicate_intents(intents, utc(2024, 1, 2, 20))
        report = checker.finalize()
        assert report.status in (IntegrityStatus.FAILED, IntegrityStatus.CRITICAL_FAILURE)
        assert any(i.check == "duplicate_trades" for i in report.issues)
        assert report.is_valid_performance is False

    def test_checker_flags_duplicate_fills_for_same_order_id(self) -> None:
        checker = BacktestIntegrityChecker()
        fill = Fill(
            order_id="ORD-000001", security_id="AAA", side=OrderSide.BUY, quantity=10.0,
            reference_price=100.0, price=100.0, commission=1.0, spread_cost=0.0, slippage_cost=0.0,
            decision_time=utc(2024, 1, 2, 20), execution_time=utc(2024, 1, 3, 20), data_version="v1",
        )
        checker.check_fill(fill)
        checker.check_fill(fill)  # same order_id applied twice
        report = checker.finalize()
        assert any(i.check == "duplicate_trades" for i in report.issues)
        assert not report.is_valid_performance

    def test_different_security_or_side_is_not_a_duplicate(self) -> None:
        checker = BacktestIntegrityChecker()
        intents = [
            OrderIntent("AAA", OrderSide.BUY, 10.0),
            OrderIntent("AAA", OrderSide.SELL, 5.0),
            OrderIntent("BBB", OrderSide.BUY, 5.0),
        ]
        checker.check_duplicate_intents(intents, utc(2024, 1, 2, 20))
        report = checker.finalize()
        assert report.status == IntegrityStatus.PASSED

    def test_engine_level_duplicate_intents_invalidate_the_result(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 8))
        bars = make_bars("AAA", days, [100.0] * len(days))
        repo = build_repository(bars=bars, securities=[make_security("AAA", "AAA")])

        class _DuplicateIntentStrategy:
            version = "duplicate_intent_v1"

            def generate_orders(self, as_of_time, data, portfolio):
                return [OrderIntent("AAA", OrderSide.BUY, 1.0), OrderIntent("AAA", OrderSide.BUY, 1.0)]

        config = BacktestConfig(
            market="US_EQUITY", start_date=days[0], end_date=days[-1],
            initial_capital=10_000.0, security_ids=("AAA",),
        )
        result = BacktestEngine(repo, config, _DuplicateIntentStrategy()).run()
        assert any(i.check == "duplicate_trades" for i in result.integrity.issues)
        assert result.is_valid_performance is False


class TestIntegrityFailureGating:
    def test_negative_cash_triggers_critical_failure_and_invalid_result(self) -> None:
        portfolio = PortfolioAccounting(1_000.0)
        # Deliberately bypass OrderSimulator/FillSimulator (which would
        # normally prevent this) to construct the impossible state this
        # check exists to catch.
        oversized_fill = Fill(
            order_id="ORD-BAD", security_id="AAA", side=OrderSide.BUY, quantity=1000.0,
            reference_price=100.0, price=100.0, commission=0.0, spread_cost=0.0, slippage_cost=0.0,
            decision_time=utc(2024, 1, 2, 20), execution_time=utc(2024, 1, 3, 20), data_version="v1",
        )
        portfolio.apply_fill(oversized_fill)
        assert portfolio.cash < 0

        checker = BacktestIntegrityChecker()
        checker.check_portfolio_state(portfolio.snapshot_view(utc(2024, 1, 3, 20)))
        report = checker.finalize()

        assert report.status == IntegrityStatus.CRITICAL_FAILURE
        assert report.is_valid_performance is False
        assert any(i.severity == IntegritySeverity.CRITICAL and i.check == "impossible_portfolio_state"
                   for i in report.issues)
        # The failure is still inspectable, not discarded:
        assert len(report.critical_issues) >= 1

    def test_negative_position_triggers_critical_failure(self) -> None:
        from backtest.portfolio import Position

        portfolio = PortfolioAccounting(10_000.0)
        portfolio.positions["AAA"] = Position("AAA", quantity=-5.0, average_cost=100.0)
        view = portfolio.snapshot_view(utc(2024, 1, 3, 20))

        checker = BacktestIntegrityChecker()
        checker.check_portfolio_state(view)
        report = checker.finalize()

        assert report.status == IntegrityStatus.CRITICAL_FAILURE
        assert not report.is_valid_performance

    def test_clean_run_has_no_issues_and_is_valid(self) -> None:
        checker = BacktestIntegrityChecker()
        report = checker.finalize()
        assert report.status == IntegrityStatus.PASSED
        assert report.is_valid_performance is True
        assert report.issues == ()

    def test_warning_only_run_is_still_valid_performance(self) -> None:
        checker = BacktestIntegrityChecker()
        checker.check_missing_data(["AAA"], utc(2024, 1, 2, 20))
        report = checker.finalize()
        assert report.status == IntegrityStatus.PASSED_WITH_WARNINGS
        assert report.is_valid_performance is True
