"""Category: Experiment -> Persistent Storage integration (Phase 4 spec
section 16, Integration).
"""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, make_benchmark, make_security, trading_days

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.experiment import ExperimentTracker
from backtest.strategy import BuyAndHoldStrategy, SimpleMomentumStrategy

from storage.config import StorageConfig
from storage.engine import StorageEngine
from storage.experiment_repository import DuckDBExperimentRepository


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 2, 29))
    bars = make_bars("AAA", days, [100.0 + i * 0.4 for i in range(len(days))])
    securities = [make_security("AAA", "AAA")]
    bench = make_benchmark(days, [4000.0 + i for i in range(len(days))])
    repo = build_repository(bars=bars, securities=securities, benchmarks=bench)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=50_000.0,
        security_ids=("AAA",), benchmark_id="SP500", code_version="exp-storage-test",
    )
    return repo, config


class TestExperimentToStorage:
    def test_multiple_experiments_from_one_session_all_persist_and_are_queryable(self, tmp_path) -> None:
        repo, config = _scenario()
        tracker = ExperimentTracker()
        r1 = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"]), experiment_tracker=tracker).run()
        r2 = BacktestEngine(
            repo, config, SimpleMomentumStrategy(["AAA"], lookback_days=10, top_n=1, rebalance_every=5),
            experiment_tracker=tracker,
        ).run()

        engine = StorageEngine(StorageConfig(tmp_path / "store"))
        exp_repo = DuckDBExperimentRepository(engine)
        exp_repo.record(r1.experiment)
        exp_repo.record(r2.experiment)

        all_experiments = exp_repo.list_all()
        assert {e.experiment_id for e in all_experiments} == {"BT-000001", "BT-000002"}
        assert {e.strategy_version for e in all_experiments} == {"buy_and_hold_v1", "simple_momentum_v1"}
        engine.close()

    def test_sql_analysis_across_persisted_experiments(self, tmp_path) -> None:
        """The point of putting experiments in DuckDB rather than only
        Parquet/JSON is direct SQL analysis across a growing registry
        (Phase 4 spec section 7, long-horizon query interface) --
        exercise that directly rather than only via the repository API."""
        repo, config = _scenario()
        tracker = ExperimentTracker()
        r1 = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"]), experiment_tracker=tracker).run()
        r2 = BacktestEngine(
            repo, config, SimpleMomentumStrategy(["AAA"], lookback_days=10, top_n=1, rebalance_every=5),
            experiment_tracker=tracker,
        ).run()

        engine = StorageEngine(StorageConfig(tmp_path / "store"))
        exp_repo = DuckDBExperimentRepository(engine)
        exp_repo.record(r1.experiment)
        exp_repo.record(r2.experiment)

        rows = engine.connection.execute(
            "SELECT experiment_id, strategy_version, sharpe_ratio FROM experiments ORDER BY experiment_id"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "BT-000001"
        assert rows[0][2] == r1.experiment.metrics.sharpe_ratio
        engine.close()

    def test_experiment_survives_restart_with_full_configuration(self, tmp_path) -> None:
        repo, config = _scenario()
        result = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"])).run()

        store_config = StorageConfig(tmp_path / "store")
        engine1 = StorageEngine(store_config)
        DuckDBExperimentRepository(engine1).record(result.experiment)
        engine1.close()

        engine2 = StorageEngine(store_config)
        reloaded = DuckDBExperimentRepository(engine2).get(result.experiment.experiment_id)
        assert reloaded.configuration_version == result.experiment.configuration_version
        assert reloaded.data_version == result.experiment.data_version
        assert reloaded.benchmark == result.experiment.benchmark
        engine2.close()
