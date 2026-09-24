"""Category: per-security P&L contribution / concentration analysis
(backtest.contribution) -- added per the master instruction's "Symbol
Contribution" / concentration-check requirement."""

from __future__ import annotations

import pytest
from backtest_helpers import utc

from backtest.contribution import compute_contribution_report, compute_contribution_report_from_fills
from backtest.enums import OrderSide
from backtest.fills import Fill
from backtest.portfolio import PortfolioAccounting

from data_infra.enums import CorporateActionType
from data_infra.models import CorporateAction, Provenance


def _split_action(security_id, ratio, effective_day, available_day=None) -> CorporateAction:
    effective = utc(2024, 1, effective_day, 0)
    available = utc(2024, 1, available_day if available_day is not None else effective_day, 0)
    return CorporateAction(
        security_id=security_id,
        action_type=CorporateActionType.SPLIT,
        available_time=available,
        ingestion_time=available,
        effective_time=effective,
        details={"ratio": ratio},
        provenance=Provenance(
            source="test", source_dataset="test", source_record_id=f"{security_id}-split-{effective_day}",
            retrieved_at=available, data_version="v1",
        ),
    )


def _fill(security_id, side, quantity, price, decision_day=1, execution_day=2) -> Fill:
    return Fill(
        order_id=f"ORD-{security_id}-{decision_day}-{side.value}",
        security_id=security_id,
        side=side,
        quantity=quantity,
        reference_price=price,
        price=price,
        commission=0.0,
        spread_cost=0.0,
        slippage_cost=0.0,
        decision_time=utc(2024, 1, decision_day, 20),
        execution_time=utc(2024, 1, execution_day, 20),
        data_version=f"v-{execution_day}",
    )


class TestRealizedOnly:
    def test_single_winning_trade_is_the_sole_contributor(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill("AAA", OrderSide.BUY, 10, 100.0))
        portfolio.apply_fill(_fill("AAA", OrderSide.SELL, 10, 110.0))

        report = compute_contribution_report(portfolio, final_prices={})

        assert report.total_pnl == pytest.approx(100.0)  # (110-100)*10
        assert report.num_securities == 1
        assert report.top_contributor.security_id == "AAA"
        assert report.top_contributor.share_of_total_pnl == pytest.approx(1.0)

    def test_two_securities_equal_contribution_gives_50_50_shares(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill("AAA", OrderSide.BUY, 10, 100.0))
        portfolio.apply_fill(_fill("AAA", OrderSide.SELL, 10, 110.0))  # +100
        portfolio.apply_fill(_fill("BBB", OrderSide.BUY, 10, 100.0))
        portfolio.apply_fill(_fill("BBB", OrderSide.SELL, 10, 110.0))  # +100

        report = compute_contribution_report(portfolio, final_prices={})

        assert report.total_pnl == pytest.approx(200.0)
        shares = {c.security_id: c.share_of_total_pnl for c in report.contributions}
        assert shares["AAA"] == pytest.approx(0.5)
        assert shares["BBB"] == pytest.approx(0.5)
        assert report.herfindahl_index == pytest.approx(0.5)  # 0.5^2 + 0.5^2
        assert report.equal_weight_share == pytest.approx(0.5)  # 1/2

    def test_one_dominant_winner_produces_high_concentration(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill("BIG", OrderSide.BUY, 100, 100.0))
        portfolio.apply_fill(_fill("BIG", OrderSide.SELL, 100, 200.0))  # +10,000
        portfolio.apply_fill(_fill("SMALL", OrderSide.BUY, 10, 100.0))
        portfolio.apply_fill(_fill("SMALL", OrderSide.SELL, 10, 101.0))  # +10

        report = compute_contribution_report(portfolio, final_prices={})

        assert report.top_contributor.security_id == "BIG"
        assert report.top_1_share_of_positive_pnl == pytest.approx(10_000.0 / 10_010.0)
        # Far above the 1/2 equal-weight reference -- genuinely concentrated.
        assert report.herfindahl_index > report.equal_weight_share

    def test_a_loss_and_a_gain_that_cancel_still_show_as_concentrated_via_hhi(self) -> None:
        """Regression guard: HHI must use ABSOLUTE shares, not signed
        ones -- a +1000/-1000 pair sums to zero total_pnl (share
        undefined) but is NOT a diversified, low-risk result, and must
        not silently compute an HHI that hides that."""
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill("WINNER", OrderSide.BUY, 10, 100.0))
        portfolio.apply_fill(_fill("WINNER", OrderSide.SELL, 10, 200.0))  # +1000
        portfolio.apply_fill(_fill("LOSER", OrderSide.BUY, 10, 100.0))
        portfolio.apply_fill(_fill("LOSER", OrderSide.SELL, 10, 0.0))  # -1000

        report = compute_contribution_report(portfolio, final_prices={})

        assert report.total_pnl == pytest.approx(0.0)
        for c in report.contributions:
            assert c.share_of_total_pnl is None  # undefined, not fabricated as 0
        assert report.herfindahl_index == pytest.approx(0.5)  # still detects the concentration


class TestUnrealizedPositions:
    def test_open_position_contributes_unrealized_pnl_using_final_prices(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill("OPEN", OrderSide.BUY, 10, 100.0))  # never sold

        report = compute_contribution_report(portfolio, final_prices={"OPEN": 150.0})

        assert report.total_pnl == pytest.approx(500.0)  # (150-100)*10
        assert report.contributions[0].realized_pnl == pytest.approx(0.0)
        assert report.contributions[0].unrealized_pnl == pytest.approx(500.0)

    def test_missing_final_price_falls_back_to_average_cost_like_unrealized_pnl_does(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill("OPEN", OrderSide.BUY, 10, 100.0))

        report = compute_contribution_report(portfolio, final_prices={})  # OPEN not priced

        assert report.total_pnl == pytest.approx(0.0)  # falls back to average_cost -> no P&L


class TestFromFillsConvenienceWrapper:
    def test_replaying_fills_produces_the_same_report_as_a_live_portfolio(self) -> None:
        fills = [
            _fill("AAA", OrderSide.BUY, 10, 100.0),
            _fill("AAA", OrderSide.SELL, 10, 150.0),
            _fill("BBB", OrderSide.BUY, 5, 200.0),
        ]

        live_portfolio = PortfolioAccounting(10_000.0)
        for f in fills:
            live_portfolio.apply_fill(f)
        expected = compute_contribution_report(live_portfolio, final_prices={"BBB": 220.0})

        actual = compute_contribution_report_from_fills(fills, 10_000.0, final_prices={"BBB": 220.0}, corporate_actions=())

        assert actual == expected


class TestFromFillsCorporateActionReplay:
    """External audit finding (2026-09-24, confirmed by direct
    reproduction): replaying fills alone, without also replaying
    corporate actions, silently desynchronizes from the engine's real
    portfolio state the moment a split occurs mid-holding."""

    def test_split_between_buy_and_sell_matches_the_engines_own_realized_pnl(self) -> None:
        buy = _fill("AAA", OrderSide.BUY, 100, 10.0, decision_day=1, execution_day=1)
        sell = _fill("AAA", OrderSide.SELL, 200, 6.0, decision_day=10, execution_day=10)
        split = _split_action("AAA", "2:1", effective_day=5)

        # The real engine's own path: apply_fill -> apply_split -> apply_fill.
        engine_portfolio = PortfolioAccounting(10_000.0)
        engine_portfolio.apply_fill(buy)
        engine_portfolio.apply_split("AAA", 2.0)
        engine_portfolio.apply_fill(sell)

        report = compute_contribution_report_from_fills(
            [buy, sell], 10_000.0, final_prices={}, corporate_actions=[split],
        )

        assert report.total_pnl == pytest.approx(engine_portfolio.realized_pnl)
        assert report.total_pnl == pytest.approx(200.0)  # (6 - 5) * 200, matches the engine exactly (zero commission in this fixture)

    def test_omitting_a_real_split_reproduces_the_confirmed_pre_fix_wrong_number(self) -> None:
        """Documents the exact bug the external audit caught -- pinned
        as a regression test, not just described in a docstring. This
        is what happens if a caller forgets to pass corporate_actions;
        it is NOT the correct number, and this test exists so nobody
        mistakes it for one."""
        buy = _fill("AAA", OrderSide.BUY, 100, 10.0, decision_day=1, execution_day=1)
        sell = _fill("AAA", OrderSide.SELL, 200, 6.0, decision_day=10, execution_day=10)

        report = compute_contribution_report_from_fills(
            [buy, sell], 10_000.0, final_prices={}, corporate_actions=(),
        )

        # (6 - 10) * 200 -- the sell's real 200sh treated against the
        # replay's un-split 100sh position (this fixture's zero
        # commission means the magnitude differs from the audit's own
        # commission-bearing reproduction, but the mechanism -- and the
        # sign-flip vs. the engine's real +200.0 -- is the same confirmed bug).
        assert report.total_pnl == pytest.approx(-800.0)

    def test_dividend_between_fills_matches_the_engines_own_cash_accounting(self) -> None:
        buy = _fill("AAA", OrderSide.BUY, 100, 10.0, decision_day=1, execution_day=1)
        sell = _fill("AAA", OrderSide.SELL, 100, 12.0, decision_day=10, execution_day=10)
        dividend = CorporateAction(
            security_id="AAA", action_type=CorporateActionType.DIVIDEND,
            available_time=utc(2024, 1, 5), ingestion_time=utc(2024, 1, 5),
            effective_time=utc(2024, 1, 5), details={"amount": 0.50},
            provenance=Provenance(source="test", source_dataset="test", source_record_id="AAA-div-5", retrieved_at=utc(2024, 1, 5), data_version="v1"),
        )

        engine_portfolio = PortfolioAccounting(10_000.0)
        engine_portfolio.apply_fill(buy)
        engine_portfolio.apply_dividend("AAA", 0.50, utc(2024, 1, 5))
        engine_portfolio.apply_fill(sell)

        report = compute_contribution_report_from_fills(
            [buy, sell], 10_000.0, final_prices={}, corporate_actions=[dividend],
        )

        # apply_dividend does not touch realized_pnl (Phase 2 spec) --
        # this asserts the dividend replay doesn't corrupt the fill-only
        # realized_pnl the way a mishandled event could.
        assert report.total_pnl == pytest.approx(engine_portfolio.realized_pnl)
        assert report.total_pnl == pytest.approx(200.0)  # (12 - 10) * 100

    def test_split_after_the_last_fill_still_corrects_unrealized_pnl(self) -> None:
        buy = _fill("AAA", OrderSide.BUY, 100, 10.0, decision_day=1, execution_day=1)
        split = _split_action("AAA", "2:1", effective_day=5)

        engine_portfolio = PortfolioAccounting(10_000.0)
        engine_portfolio.apply_fill(buy)
        engine_portfolio.apply_split("AAA", 2.0)
        expected = compute_contribution_report(engine_portfolio, final_prices={"AAA": 6.0})

        report = compute_contribution_report_from_fills(
            [buy], 10_000.0, final_prices={"AAA": 6.0}, corporate_actions=[split],
        )

        assert report == expected

    def test_action_with_no_orderable_timestamp_is_skipped_not_guessed(self) -> None:
        buy = _fill("AAA", OrderSide.BUY, 100, 10.0, decision_day=1, execution_day=1)
        sell = _fill("AAA", OrderSide.SELL, 100, 12.0, decision_day=10, execution_day=10)
        unorderable = CorporateAction(
            security_id="AAA", action_type=CorporateActionType.SPLIT,
            available_time=utc(2024, 1, 5), ingestion_time=utc(2024, 1, 5),
            details={"ratio": "2:1"},  # no event_time/effective_time
            provenance=Provenance(source="test", source_dataset="test", source_record_id="AAA-unorderable", retrieved_at=utc(2024, 1, 5), data_version="v1"),
        )

        report = compute_contribution_report_from_fills(
            [buy, sell], 10_000.0, final_prices={}, corporate_actions=[unorderable],
        )

        # Skipped, not applied at a guessed time -- matches the plain
        # fill-only replay (no split effect at all).
        assert report.total_pnl == pytest.approx(200.0)  # (12 - 10) * 100, split never applied


class TestEmptyPortfolio:
    def test_no_trades_returns_empty_report_not_a_fabricated_zero_concentration(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)

        report = compute_contribution_report(portfolio, final_prices={})

        assert report.contributions == ()
        assert report.total_pnl == 0.0
        assert report.num_securities == 0
        assert report.top_contributor is None
        assert report.bottom_contributor is None
        assert report.top_1_share_of_positive_pnl is None
        assert report.herfindahl_index is None
        assert report.equal_weight_share is None
