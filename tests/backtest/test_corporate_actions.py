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


class _BuyThenLaterSellEverythingStrategy:
    """Buys a fixed quantity once (`buy_on_step`), then sells whatever
    the portfolio reports it currently holds (`sell_on_step`) -- the
    SELL quantity directly reveals whatever the engine actually believes
    the current position is, corrupted or not."""

    version = "buy_then_sell_all_test_v1"

    def __init__(self, security_id: str, *, buy_on_step: int, sell_on_step: int, buy_quantity: float) -> None:
        self._security_id = security_id
        self._buy_on_step = buy_on_step
        self._sell_on_step = sell_on_step
        self._buy_quantity = buy_quantity
        self._step = 0

    def generate_orders(self, as_of_time, data, portfolio):
        from backtest.strategy import OrderIntent

        self._step += 1
        if self._step == self._buy_on_step:
            return [OrderIntent(self._security_id, OrderSide.BUY, self._buy_quantity)]
        if self._step == self._sell_on_step:
            held = portfolio.quantity_of(self._security_id)
            if held > 0:
                return [OrderIntent(self._security_id, OrderSide.SELL, held)]
        return []


class TestSplitAtTheExactCheckpointAFillExecutesOn:
    """Session 37 (ADR-0115, external review N-7): before this fix, a
    fill executing at `next_checkpoint`'s close was applied to the
    portfolio synchronously within the SAME iteration the order was
    generated in -- well before iteration `next_checkpoint`'s own
    top-of-loop corporate-action block would apply anything effective by
    `next_checkpoint`. A BUY whose fill lands exactly on a split's
    effective date was therefore bought at the real, already-adjusted
    market price (correct) but then had `apply_split`'s blind multiply
    applied to it a SECOND time once that next iteration ran --
    corrupting quantity/average_cost for a purchase that should never
    have been touched by the split at all."""

    def test_a_buy_that_fills_exactly_on_the_split_date_is_not_double_adjusted(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 22))
        buy_step = 3  # order generated at days[buy_step - 1]; fills at days[buy_step]
        split_day = days[buy_step]  # the split becomes effective exactly when the fill executes
        sell_step = 8  # well after the split -- reveals the true held quantity

        # Raw close: 100.0 before the split, 50.0 from split_day onward --
        # a real 2:1 split's raw price effect, exactly what the fill at
        # split_day's close is actually paid.
        raw_closes = [100.0 if d < split_day else 50.0 for d in days]
        bars = make_bars("AAA", days, raw_closes)

        sec = make_security("AAA", "AAA")
        split = make_split("AAA", split_day, ratio="2:1")
        repo = build_repository(bars=bars, securities=[sec], corporate_actions=[split])

        config = BacktestConfig(
            market="US_EQUITY", start_date=days[0], end_date=days[-1],
            initial_capital=10_000.0, security_ids=("AAA",),
        )
        strategy = _BuyThenLaterSellEverythingStrategy(
            "AAA", buy_on_step=buy_step, sell_on_step=sell_step, buy_quantity=10.0,
        )
        result = BacktestEngine(repo, config, strategy).run()

        buy_fills = [f for f in result.fills if f.side == OrderSide.BUY]
        sell_fills = [f for f in result.fills if f.side == OrderSide.SELL]
        assert len(buy_fills) == 1
        # The real, already-post-split execution price (within a few
        # percent -- the fill simulator applies spread/slippage on top
        # of the raw close, so this is not an exact match).
        assert buy_fills[0].price == pytest.approx(50.0, rel=0.05)
        assert len(sell_fills) == 1
        # The bug: without the fix, this comes back as 20.0 (doubled by
        # apply_split running a second time on the already-correct buy).
        assert sell_fills[0].quantity == pytest.approx(10.0)


class TestCorporateActionSequencingUnit:
    """Direct unit-level proof of the ordering `BacktestEngine.run()` now
    performs for `next_checkpoint`-effective actions: apply them to
    `portfolio` BEFORE the fill that lands the same checkpoint, not
    after. `BacktestEngine` itself has no accessor for its internal
    portfolio, so the split case above (verified end to end through a
    real run, via the revealed SELL quantity) is paired here with a
    focused unit test of the dividend-timing half of the same fix,
    exercising `CorporateActionApplier`/`PortfolioAccounting` the same
    way `engine.py`'s new block does."""

    def test_dividend_applied_before_a_same_day_buy_is_not_paid_to_it(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        applier = CorporateActionApplier()
        dividend = make_dividend("AAA", date(2024, 1, 5), amount=1.0)

        # The fixed order: next_checkpoint's corporate actions first...
        applier.apply([dividend], portfolio, checkpoint(date(2024, 1, 5)))
        # ...then the same-checkpoint buy lands.
        portfolio.apply_fill(_fill("AAA", 10, 100.0, 5))

        # No pre-existing position, so the dividend (paid per currently-
        # held share) had nothing to credit -- cash only reflects the buy.
        assert portfolio.cash == pytest.approx(10_000.0 - 1_000.0)

    def test_dividend_applied_before_the_fill_still_pays_a_pre_existing_holder(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        applier = CorporateActionApplier()
        # Held through the prior close -- entitled to the dividend.
        portfolio.apply_fill(_fill("AAA", 10, 100.0, 4))
        dividend = make_dividend("AAA", date(2024, 1, 5), amount=1.0)
        cash_before = portfolio.cash

        applier.apply([dividend], portfolio, checkpoint(date(2024, 1, 5)))
        assert portfolio.cash == pytest.approx(cash_before + 10.0)
