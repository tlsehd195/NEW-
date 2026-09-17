"""External review, ADR-0048's own original gap (closed this session):
`OrderIntent.features` -- plumbing that has existed since Session 36 --
was never actually populated by any real `Strategy`, including this
repository's own Phase 2 baseline (`SimpleMomentumStrategy`).
`Order.features` copies straight through from `OrderIntent.features`
unconditionally (`backtest.orders.Order` construction), so this is
checkable directly on `BacktestResult.orders` without a separate Trade
Journal ingestion step.

`BuyAndHoldStrategy` is deliberately not covered here: it has no
per-security score or signal at all (equal-weight buy of the whole
list), so there is nothing real to attach -- fabricating a feature for
it would violate this project's own never-fabricate discipline.
"""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, make_security, trading_days

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.strategy import SimpleMomentumStrategy


def _build_scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 1, 31))
    aaa_closes = [100.0 * (1.002**i) for i in range(len(days))]
    bbb_closes = [50.0 * (0.999**i) for i in range(len(days))]
    bars = make_bars("AAA", days, aaa_closes) + make_bars("BBB", days, bbb_closes)
    securities = [make_security("AAA", "AAA"), make_security("BBB", "BBB")]
    repo = build_repository(bars=bars, securities=securities)

    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1],
        initial_capital=50_000.0, security_ids=("AAA", "BBB"), code_version="test-commit-abc123",
    )
    return repo, config


class TestSimpleMomentumStrategyOrderIntentFeatures:
    def test_the_buy_order_carries_the_real_momentum_score(self) -> None:
        repo, config = _build_scenario()
        strategy = SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=5, top_n=1, rebalance_every=5)
        result = BacktestEngine(repo, config, strategy).run()

        buy_orders = [o for o in result.orders if o.security_id == "AAA" and o.side.value == "BUY"]
        assert buy_orders
        assert buy_orders[0].features is not None
        assert isinstance(buy_orders[0].features["momentum_score"], float)
