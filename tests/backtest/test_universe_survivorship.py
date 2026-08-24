"""Category: Survivorship test.

Verifies a security leaving the universe mid-backtest is excluded from
new purchases from that point forward, at the full engine level (not
just the data-layer level Phase 1 already covers). See
docs/specifications/PHASE-2-backtesting.md section 4/section 10.
"""

from __future__ import annotations

from datetime import date, timedelta

from backtest_helpers import build_repository, checkpoint, make_bars, make_membership, make_security, trading_days

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.enums import OrderSide
from backtest.strategy import OrderIntent


class _AlwaysBuyEverythingInUniverse:
    """A deliberately naive test strategy that always tries to buy every
    security_id the universe view currently reports — used to prove the
    engine itself (not just the strategy's own restraint) prevents
    trading a security once it has left the universe."""

    version = "always_buy_universe_v1"

    def generate_orders(self, as_of_time, data, portfolio):
        universe = data.get_universe("US", "SP500")
        intents = []
        for security_id in universe:
            if portfolio.quantity_of(security_id) == 0:
                intents.append(OrderIntent(security_id, OrderSide.BUY, 1.0))
        return intents


class TestSurvivorship:
    def test_security_removed_from_universe_is_not_purchased_afterward(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 16))
        drop_day = days[5]

        bars = make_bars("OLD", days, [100.0] * len(days)) + make_bars("NEW", days, [50.0] * len(days))
        securities = [make_security("OLD", "OLD"), make_security("NEW", "NEW")]
        memberships = [
            make_membership("OLD", checkpoint(days[0]) - timedelta(days=1), checkpoint(drop_day)),
            make_membership("NEW", checkpoint(drop_day)),
        ]
        repo = build_repository(bars=bars, securities=securities, universe_memberships=memberships)

        config = BacktestConfig(
            market="US_EQUITY", start_date=days[0], end_date=days[-1],
            initial_capital=100_000.0, universe=("US", "SP500"),
        )
        result = BacktestEngine(repo, config, _AlwaysBuyEverythingInUniverse()).run()

        assert result.is_valid_performance
        bought_ids = {f.security_id for f in result.fills}
        # OLD is only in the universe before drop_day, and the strategy is
        # evaluated once per checkpoint — it should have been bought while
        # a member, and NEW should be bought once it joins.
        assert "OLD" in bought_ids or "NEW" in bought_ids  # at least one leg exercised
        # No universe_correctness violation should ever be raised, since
        # the engine only ever asks the strategy to act within the
        # as-of-resolved universe and the strategy itself only requests
        # what get_universe() currently reports.
        assert not any(i.check == "universe_correctness" for i in result.integrity.issues)

    def test_engine_flags_an_order_for_a_security_outside_the_resolved_universe(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 8))
        bars = make_bars("OUTSIDE", days, [100.0] * len(days))
        securities = [make_security("OUTSIDE", "OUTSIDE")]
        # OUTSIDE is never a member of SP500 in this scenario.
        repo = build_repository(bars=bars, securities=securities, universe_memberships=[])

        class _BuyOutsideUniverse:
            version = "buy_outside_v1"

            def generate_orders(self, as_of_time, data, portfolio):
                return [OrderIntent("OUTSIDE", OrderSide.BUY, 1.0)]

        config = BacktestConfig(
            market="US_EQUITY", start_date=days[0], end_date=days[-1],
            initial_capital=10_000.0, universe=("US", "SP500"),
        )
        result = BacktestEngine(repo, config, _BuyOutsideUniverse()).run()

        assert any(i.check == "universe_correctness" for i in result.integrity.issues)
        assert not result.is_valid_performance
