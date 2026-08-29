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

        actual = compute_contribution_report_from_fills(fills, 10_000.0, final_prices={"BBB": 220.0})

        assert actual == expected


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
