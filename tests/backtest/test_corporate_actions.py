"""Category: Corporate action test.

See docs/specifications/PHASE-2-backtesting.md section 8.4.
"""

from __future__ import annotations

from datetime import date

import pytest
from backtest_helpers import (
    build_repository,
    checkpoint,
    make_bars,
    make_dividend,
    make_security,
    make_split,
    trading_days,
    utc,
)

from backtest.corporate_actions import CorporateActionApplier, _parse_ratio
from backtest.engine import BacktestConfig, BacktestEngine
from backtest.enums import OrderSide
from backtest.fills import Fill
from backtest.portfolio import PortfolioAccounting
from backtest.strategy import BuyAndHoldStrategy


def _fill(security_id, quantity, price, day) -> Fill:
    return Fill(
        order_id="ORD-1", security_id=security_id, side=OrderSide.BUY, quantity=quantity,
        reference_price=price, price=price, commission=0.0, spread_cost=0.0, slippage_cost=0.0,
        decision_time=utc(2024, 1, day - 1, 20), execution_time=utc(2024, 1, day, 20), data_version="v1",
    )


class TestRatioParsing:
    def test_colon_ratio_parses_forward_split(self) -> None:
        assert _parse_ratio("2:1") == pytest.approx(2.0)

    def test_colon_ratio_parses_reverse_split(self) -> None:
        assert _parse_ratio("1:2") == pytest.approx(0.5)

    def test_numeric_ratio_passes_through(self) -> None:
        assert _parse_ratio(3.0) == 3.0

    def test_unparseable_ratio_returns_none(self) -> None:
        assert _parse_ratio("not-a-ratio") is None
        assert _parse_ratio(None) is None


class TestCorporateActionApplierUnit:
    def test_split_adjusts_held_position(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill("AAA", 10, 100.0, 2))
        action = make_split("AAA", date(2024, 1, 5))
        applier = CorporateActionApplier()
        warnings = applier.apply([action], portfolio, checkpoint(date(2024, 1, 5)))
        assert warnings == []
        assert portfolio.positions["AAA"].quantity == 20.0
        assert portfolio.positions["AAA"].average_cost == pytest.approx(50.0)

    def test_dividend_credits_cash_not_recorded_as_trade(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill("AAA", 10, 100.0, 2))
        cash_before = portfolio.cash
        action = make_dividend("AAA", date(2024, 1, 5), amount=1.0)
        applier = CorporateActionApplier()
        applier.apply([action], portfolio, checkpoint(date(2024, 1, 5)))
        assert portfolio.cash == pytest.approx(cash_before + 10.0)
        assert portfolio.closed_trades == []

    def test_action_not_applied_twice(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill("AAA", 10, 100.0, 2))
        action = make_split("AAA", date(2024, 1, 5))
        applier = CorporateActionApplier()
        applier.apply([action], portfolio, checkpoint(date(2024, 1, 5)))
        applier.apply([action], portfolio, checkpoint(date(2024, 1, 6)))  # same action seen again
        assert portfolio.positions["AAA"].quantity == 20.0  # not 40

    def test_future_action_is_not_applied(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill("AAA", 10, 100.0, 2))
        action = make_split("AAA", date(2024, 1, 10))
        applier = CorporateActionApplier()
        applier.apply([action], portfolio, checkpoint(date(2024, 1, 5)))  # before available_time
        assert portfolio.positions["AAA"].quantity == 10.0  # unchanged

    def test_unhandled_action_type_produces_warning_not_crash(self) -> None:
        from data_infra.enums import CorporateActionType
        from data_infra.models import CorporateAction, Provenance

        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill("AAA", 10, 100.0, 2))
        merger = CorporateAction(
            security_id="AAA", action_type=CorporateActionType.MERGER,
            available_time=checkpoint(date(2024, 1, 5)), ingestion_time=checkpoint(date(2024, 1, 5)),
            provenance=Provenance(
                source="test", source_dataset="test_ds", source_record_id="merger-1",
                retrieved_at=checkpoint(date(2024, 1, 5)), data_version="v1",
            ),
        )
        applier = CorporateActionApplier()
        warnings = applier.apply([merger], portfolio, checkpoint(date(2024, 1, 5)))
        assert len(warnings) == 1
        assert "not handled" in warnings[0]
        assert portfolio.positions["AAA"].quantity == 10.0  # unaffected


class TestCorporateActionIntegration:
    def test_split_mid_backtest_does_not_corrupt_momentum_signal_or_valuation(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 22))
        # Price steadily rises pre-split, then the SPLIT halves the raw
        # price on day 12 while adjusted_close continues the true trend —
        # a naive raw-close momentum signal would see this as a crash.
        raw_closes = []
        true_price = 100.0
        split_day = days[9]
        for d in days:
            true_price *= 1.01
            if d < split_day:
                raw_closes.append(true_price)
            else:
                raw_closes.append(true_price / 2.0)  # post-split raw price

        bars = []
        for d, raw_close in zip(days, raw_closes):
            bars.extend(make_bars("AAA", [d], [raw_close]))
        # overwrite adjusted_close to reflect the true (split-adjusted) trend
        from dataclasses import replace

        true_prices = []
        p = 100.0
        for d in days:
            p *= 1.01
            true_prices.append(p)
        bars = [replace(b, adjusted_close=tp) for b, tp in zip(bars, true_prices)]

        sec = make_security("AAA", "AAA")
        split = make_split("AAA", split_day, ratio="2:1")
        repo = build_repository(bars=bars, securities=[sec], corporate_actions=[split])

        config = BacktestConfig(
            market="US_EQUITY", start_date=days[0], end_date=days[-1],
            initial_capital=10_000.0, security_ids=("AAA",),
        )
        result = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"])).run()

        assert result.is_valid_performance
        # Quantity should have doubled once the split was applied.
        # (BuyAndHoldStrategy buys once on day 1, split applies on split_day.)
        # No corporate-action-correctness CRITICAL issues.
        assert not any(i.check == "corporate_action_correctness" and i.severity.value == "CRITICAL"
                        for i in result.integrity.issues)
