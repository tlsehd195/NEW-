"""Category: deterministic replay, benchmark comparison, transaction
cost, slippage, metric correctness, reproducibility (Phase 4 spec section
16, Baseline).
"""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, make_benchmark, make_security, trading_days

from backtest.engine import BacktestConfig
from backtest.strategy import BuyAndHoldStrategy, SimpleMomentumStrategy

from storage_helpers import new_engine
from storage.experiment_repository import DuckDBExperimentRepository
from storage.experience_repository import DuckDBExperienceRepository
from storage.trade_journal_repository import DuckDBTradeJournalRepository

from baseline.report import build_comparison_report, compare_reports, format_report_text
from baseline.runner import run_baseline, run_multiple_baselines


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 3, 29))
    aaa = [100.0 * (1.001**i) for i in range(len(days))]
    bbb = [50.0 * (0.9995**i) for i in range(len(days))]
    bars = make_bars("AAA", days, aaa) + make_bars("BBB", days, bbb)
    securities = [make_security("AAA", "AAA"), make_security("BBB", "BBB")]
    bench = make_benchmark(days, [4000.0 * (1.0004**i) for i in range(len(days))])
    repo = build_repository(bars=bars, securities=securities, benchmarks=bench)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA", "BBB"), benchmark_id="SP500", code_version="phase4-baseline-test", seed=1,
    )
    return repo, config


class TestDeterministicReplay:
    def test_two_runs_produce_identical_fill_sequence(self, tmp_path) -> None:
        repo, config = _scenario()

        engine1 = new_engine(tmp_path, "run1")
        run1 = run_baseline(BuyAndHoldStrategy(["AAA", "BBB"]), "buy_and_hold", repo, config,
                             journal=DuckDBTradeJournalRepository(engine1))
        engine1.close()

        engine2 = new_engine(tmp_path, "run2")
        run2 = run_baseline(BuyAndHoldStrategy(["AAA", "BBB"]), "buy_and_hold", repo, config,
                             journal=DuckDBTradeJournalRepository(engine2))
        engine2.close()

        def sig(f):
            return (f.security_id, f.side, f.quantity, f.price, f.execution_time)

        assert [sig(f) for f in run1.backtest_result.fills] == [sig(f) for f in run2.backtest_result.fills]


class TestReproducibility:
    def test_identical_performance_report_across_runs(self, tmp_path) -> None:
        repo, config = _scenario()
        engine1 = new_engine(tmp_path, "run1")
        run1 = run_baseline(SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=10, top_n=1, rebalance_every=5),
                             "simple_momentum", repo, config, journal=DuckDBTradeJournalRepository(engine1))
        engine1.close()

        engine2 = new_engine(tmp_path, "run2")
        run2 = run_baseline(SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=10, top_n=1, rebalance_every=5),
                             "simple_momentum", repo, config, journal=DuckDBTradeJournalRepository(engine2))
        engine2.close()

        assert run1.backtest_result.performance == run2.backtest_result.performance

    def test_persisted_experiment_reproduces_same_metrics_after_restart(self, tmp_path) -> None:
        from storage.config import StorageConfig
        from storage.engine import StorageEngine

        repo, config = _scenario()
        store_config = StorageConfig(tmp_path / "store")
        engine1 = StorageEngine(store_config)
        journal1 = DuckDBTradeJournalRepository(engine1)
        exp_repo1 = DuckDBExperimentRepository(engine1)
        run = run_baseline(BuyAndHoldStrategy(["AAA", "BBB"]), "buy_and_hold", repo, config,
                            journal=journal1, experiment_repo=exp_repo1)
        engine1.close()

        engine2 = StorageEngine(store_config)
        exp_repo2 = DuckDBExperimentRepository(engine2)
        reloaded = exp_repo2.get(run.backtest_result.experiment.experiment_id)
        assert reloaded.metrics == run.backtest_result.performance
        engine2.close()


class TestBenchmarkComparisonAndMetrics:
    def test_report_contains_all_required_metric_fields(self, tmp_path) -> None:
        repo, config = _scenario()
        engine = new_engine(tmp_path)
        run = run_baseline(BuyAndHoldStrategy(["AAA", "BBB"]), "buy_and_hold", repo, config,
                            journal=DuckDBTradeJournalRepository(engine))
        report = build_comparison_report(run)
        p = report.performance
        required = [
            p.cumulative_return, p.cagr, p.annualized_volatility, p.sharpe_ratio, p.sortino_ratio,
            p.max_drawdown, p.turnover, p.total_transaction_cost, p.excess_return,
            p.benchmark_cumulative_return, p.benchmark_cagr, p.benchmark_max_drawdown,
        ]
        assert all(v is not None for v in required)
        assert report.benchmark is not None
        engine.close()

    def test_excess_return_matches_strategy_minus_benchmark(self, tmp_path) -> None:
        repo, config = _scenario()
        engine = new_engine(tmp_path)
        run = run_baseline(BuyAndHoldStrategy(["AAA", "BBB"]), "buy_and_hold", repo, config,
                            journal=DuckDBTradeJournalRepository(engine))
        p = run.backtest_result.performance
        assert p.excess_return == p.cumulative_return - p.benchmark_cumulative_return
        engine.close()

    def test_transaction_cost_and_slippage_are_nonzero_by_default(self, tmp_path) -> None:
        repo, config = _scenario()
        engine = new_engine(tmp_path)
        run = run_baseline(BuyAndHoldStrategy(["AAA", "BBB"]), "buy_and_hold", repo, config,
                            journal=DuckDBTradeJournalRepository(engine))
        assert run.backtest_result.performance.total_transaction_cost > 0
        exp = run.backtest_result.experiment
        assert exp.transaction_cost_config["fixed_per_trade"] > 0
        assert exp.slippage_config  # non-empty -- a real (non-zero) slippage model was used
        engine.close()

    def test_format_report_text_includes_benchmark_info(self, tmp_path) -> None:
        repo, config = _scenario()
        engine = new_engine(tmp_path)
        run = run_baseline(BuyAndHoldStrategy(["AAA", "BBB"]), "buy_and_hold", repo, config,
                            journal=DuckDBTradeJournalRepository(engine))
        text = format_report_text(build_comparison_report(run))
        assert "Sharpe Ratio" in text
        assert "benchmark_id=SP500" in text
        engine.close()


class TestMultipleBaselineComparison:
    def test_run_multiple_baselines_gives_distinct_experiment_ids(self, tmp_path) -> None:
        repo, config = _scenario()
        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        exp_repo = DuckDBExperimentRepository(engine)
        xp_repo = DuckDBExperienceRepository(engine)

        runs = run_multiple_baselines(
            {
                "buy_and_hold": BuyAndHoldStrategy(["AAA", "BBB"]),
                "simple_momentum": SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=10, top_n=1, rebalance_every=5),
            },
            repo, config, journal=journal, experiment_repo=exp_repo, experience_repo=xp_repo,
        )
        ids = [r.backtest_result.experiment.experiment_id for r in runs]
        assert len(ids) == len(set(ids)) == 2
        assert len(exp_repo.list_all()) == 2

        reports = [build_comparison_report(r) for r in runs]
        table = compare_reports(reports)
        assert "buy_and_hold" in table and "simple_momentum" in table
        engine.close()

    def test_baseline_purpose_is_not_return_maximization_no_ranking_field(self) -> None:
        """Phase 4's own stated purpose (Part B point 12): the report
        compares baselines, it does not declare a winner. Verify the
        report type carries no rank/best/winner field."""
        from baseline.report import BaselineComparisonReport

        field_names = {f.name for f in __import__("dataclasses").fields(BaselineComparisonReport)}
        assert not any("rank" in n or "winner" in n or "best" in n for n in field_names)
