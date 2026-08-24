"""Category: Deterministic replay test.
Category: Reproducibility test.

See docs/specifications/PHASE-2-backtesting.md section 14 (test 1: same
inputs replayed twice produce an identical order/fill sequence; test 14:
same data + code + config + seed run twice yields identical
PerformanceReport values).
"""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, make_benchmark, make_security, trading_days

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.strategy import BuyAndHoldStrategy, SimpleMomentumStrategy


def _build_scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 1, 31))
    aaa_closes = [100.0 * (1.002**i) for i in range(len(days))]
    bbb_closes = [50.0 * (0.999**i) for i in range(len(days))]
    bars = make_bars("AAA", days, aaa_closes) + make_bars("BBB", days, bbb_closes)
    securities = [make_security("AAA", "AAA"), make_security("BBB", "BBB")]
    bench = make_benchmark(days, [4000.0 * (1.0006**i) for i in range(len(days))])
    repo = build_repository(bars=bars, securities=securities, benchmarks=bench)

    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1],
        initial_capital=50_000.0, security_ids=("AAA", "BBB"), benchmark_id="SP500",
        code_version="test-commit-abc123", seed=42,
    )
    return repo, config


class TestDeterministicReplay:
    def test_identical_order_and_fill_sequence_on_replay(self) -> None:
        repo, config = _build_scenario()

        result1 = BacktestEngine(repo, config, SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=5, top_n=1, rebalance_every=5)).run()
        result2 = BacktestEngine(repo, config, SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=5, top_n=1, rebalance_every=5)).run()

        def order_signature(order):
            return (order.security_id, order.side, order.quantity, order.order_type, order.status, order.decision_time)

        def fill_signature(fill):
            return (fill.security_id, fill.side, fill.quantity, fill.price, fill.decision_time, fill.execution_time)

        assert [order_signature(o) for o in result1.orders] == [order_signature(o) for o in result2.orders]
        assert [fill_signature(f) for f in result1.fills] == [fill_signature(f) for f in result2.fills]

    def test_identical_replay_for_buy_and_hold(self) -> None:
        repo, config = _build_scenario()
        result1 = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA", "BBB"])).run()
        result2 = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA", "BBB"])).run()
        assert len(result1.fills) == len(result2.fills) > 0
        for f1, f2 in zip(result1.fills, result2.fills):
            assert f1.price == f2.price
            assert f1.quantity == f2.quantity


class TestReproducibility:
    def test_same_data_code_config_seed_yields_identical_performance_report(self) -> None:
        repo, config = _build_scenario()
        result1 = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA", "BBB"])).run()
        result2 = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA", "BBB"])).run()
        assert result1.performance == result2.performance

    def test_same_inputs_yield_identical_integrity_status(self) -> None:
        repo, config = _build_scenario()
        result1 = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA", "BBB"])).run()
        result2 = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA", "BBB"])).run()
        assert result1.integrity.status == result2.integrity.status
        assert len(result1.integrity.issues) == len(result2.integrity.issues)

    def test_experiment_record_captures_config_for_reproducibility(self) -> None:
        repo, config = _build_scenario()
        result = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA", "BBB"])).run()
        exp = result.experiment
        assert exp.code_version == "test-commit-abc123"
        assert exp.seed == 42
        assert exp.data_version  # non-empty — actual data versions read were recorded
        assert exp.configuration_version  # content hash of the config

    def test_different_config_yields_different_configuration_version(self) -> None:
        repo, config = _build_scenario()
        result1 = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA", "BBB"])).run()

        from dataclasses import replace

        config2 = replace(config, initial_capital=75_000.0)
        result2 = BacktestEngine(repo, config2, BuyAndHoldStrategy(["AAA", "BBB"])).run()

        assert result1.experiment.configuration_version != result2.experiment.configuration_version

    def test_experiment_ids_increment_monotonically_within_a_shared_tracker(self) -> None:
        from backtest.experiment import ExperimentTracker

        repo, config = _build_scenario()
        tracker = ExperimentTracker()
        r1 = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA", "BBB"]), experiment_tracker=tracker).run()
        r2 = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA", "BBB"]), experiment_tracker=tracker).run()
        assert r1.experiment.experiment_id == "BT-000001"
        assert r2.experiment.experiment_id == "BT-000002"
