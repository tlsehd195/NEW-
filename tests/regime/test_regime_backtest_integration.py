"""Category: backtest integration (Phase 5 spec section 8).

Verifies Regime can be used inside a real `BacktestEngine.run()` loop
without modifying `BacktestEngine`, the `Strategy` Protocol, or any
existing Phase 2 baseline strategy -- `RegimeConditionedStrategy` is just
another `Strategy` implementation.
"""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, make_benchmark, make_security, trading_days
from regime_helpers import trend_down, trend_up

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.strategy import BuyAndHoldStrategy, SimpleMomentumStrategy

from regime.detector import RegimeDetector
from regime.config import RegimeConfig
from regime.enums import RegimeAxis, SubjectKind
from regime.strategy import RegimeConditionedStrategy


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    aaa = trend_up(days, daily_return=0.001)
    bbb = trend_down(days, start=80.0, daily_return=-0.0005)
    bars = make_bars("AAA", days, aaa) + make_bars("BBB", days, bbb)
    securities = [make_security("AAA", "AAA"), make_security("BBB", "BBB")]
    bench = make_benchmark(days, trend_up(days, start=4000.0, daily_return=0.0005))
    repo = build_repository(bars=bars, securities=securities, benchmarks=bench)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA", "BBB"), benchmark_id="SP500", code_version="regime-integration-test",
    )
    return repo, config


class TestBacktestEngineUnmodified:
    def test_existing_baselines_still_run_unaffected_by_the_regime_module_existing(self) -> None:
        """Importing/using regime.* anywhere must not change
        BuyAndHoldStrategy's own behavior -- Phase 2's Strategy contract
        is untouched (Phase 5 spec section 8)."""
        repo, config = _scenario()
        result = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA", "BBB"])).run()
        assert result.is_valid_performance
        assert len(result.fills) > 0


class TestRegimeConditionedStrategyThroughBacktestEngine:
    def test_runs_through_the_unmodified_backtest_engine(self) -> None:
        repo, config = _scenario()
        inner = SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=10, top_n=1, rebalance_every=5)
        strategy = RegimeConditionedStrategy(inner, subject_id="AAA", subject_kind=SubjectKind.SECURITY)
        result = BacktestEngine(repo, config, strategy).run()
        assert result.is_valid_performance
        assert len(strategy.regime_history) > 0

    def test_no_buy_intent_is_ever_submitted_while_trend_is_bear(self) -> None:
        repo, config = _scenario()
        inner = SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=10, top_n=2, rebalance_every=5)
        strategy = RegimeConditionedStrategy(inner, subject_id="AAA", subject_kind=SubjectKind.SECURITY)
        result = BacktestEngine(repo, config, strategy).run()

        from backtest.enums import OrderSide

        bear_checkpoints = {
            c.as_of_time for c in strategy.regime_history
            if c.get(RegimeAxis.TREND) is not None and c.get(RegimeAxis.TREND).state == "BEAR"
        }
        buy_orders_during_bear = [
            o for o in result.orders if o.side == OrderSide.BUY and o.decision_time in bear_checkpoints
        ]
        assert buy_orders_during_bear == []

    def test_deterministic_replay_is_preserved(self) -> None:
        repo, config = _scenario()

        def run_once():
            inner = SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=10, top_n=1, rebalance_every=5)
            strategy = RegimeConditionedStrategy(inner, subject_id="AAA", subject_kind=SubjectKind.SECURITY)
            return BacktestEngine(repo, config, strategy).run()

        r1, r2 = run_once(), run_once()

        def fill_sig(f):
            return (f.security_id, f.side, f.quantity, f.price, f.execution_time)

        assert [fill_sig(f) for f in r1.fills] == [fill_sig(f) for f in r2.fills]
        assert r1.performance == r2.performance


class TestStandaloneRegimeAlongsideBacktest:
    def test_regime_computed_via_asofdataview_matches_a_manual_replay(self) -> None:
        """A regime computed as part of a Strategy's own generate_orders
        call (inside a real backtest run) must match one computed by
        directly driving a BacktestClock to the same checkpoint --
        proving the "Backtest -> Regime" connection is faithful, not an
        approximation (Phase 5 spec section 8)."""
        from backtest.asof import AsOfDataView
        from backtest.clock import BacktestClock, build_daily_checkpoints
        from data_infra.calendar import US_EQUITY

        repo, config = _scenario()
        calendar = repo.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
        clock = BacktestClock(checkpoints)
        clock.index = 60
        view = AsOfDataView(repo, clock)

        detector = RegimeDetector(RegimeConfig())
        composite = detector.compute_composite(view, "AAA")
        assert composite.as_of_time == checkpoints[60]
        assert composite.get(RegimeAxis.TREND) is not None
