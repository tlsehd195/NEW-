"""Category: persistence, restart, idempotency, version metadata for the
persistent Experiment Registry (Phase 4 spec section 11, 16)."""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, make_benchmark, make_security, trading_days

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.experiment import ExperimentTracker

from backtest.strategy import BuyAndHoldStrategy

from storage.config import StorageConfig
from storage.engine import StorageEngine
from storage.experiment_repository import DuckDBExperimentRepository
from storage_helpers import new_engine


def _run_backtest(*, initial_capital: float = 10_000.0, experiment_tracker=None):
    days = trading_days(date(2024, 1, 2), date(2024, 1, 31))
    bars = make_bars("AAA", days, [100.0 + i * 0.5 for i in range(len(days))])
    securities = [make_security("AAA", "AAA")]
    bench = make_benchmark(days, [4000.0 + i for i in range(len(days))])
    repo = build_repository(bars=bars, securities=securities, benchmarks=bench)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=initial_capital,
        security_ids=("AAA",), benchmark_id="SP500", code_version="test-commit", seed=7,
    )
    return BacktestEngine(
        repo, config, BuyAndHoldStrategy(["AAA"]), experiment_tracker=experiment_tracker,
    ).run()


def _next_starting_id(exp_repo: DuckDBExperimentRepository) -> int:
    """What a real caller chaining independent `BacktestEngine` runs
    into the SAME persistent repository must do to seed each fresh
    `ExperimentTracker` past whatever's already stored (ADR-0115) --
    mirrors this project's own restart-safety convention elsewhere
    (e.g. storage.data_repository._compute_next_raw_batch_id)."""
    existing_ids = [r.experiment_id for r in exp_repo.list_all()]
    numeric = [int(eid.split("-")[1]) for eid in existing_ids if eid.startswith("BT-")]
    return (max(numeric) + 1) if numeric else 1


class TestExperimentPersistence:
    def test_record_and_get_round_trips_metrics_and_versions(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        exp_repo = DuckDBExperimentRepository(engine)
        result = _run_backtest()

        exp_repo.record(result.experiment)
        reloaded = exp_repo.get(result.experiment.experiment_id)

        assert reloaded is not None
        assert reloaded.experiment_id == result.experiment.experiment_id
        assert reloaded.strategy_version == result.experiment.strategy_version
        assert reloaded.data_version == result.experiment.data_version
        assert reloaded.code_version == "test-commit"
        assert reloaded.seed == 7
        assert reloaded.metrics == result.experiment.metrics
        assert reloaded.transaction_cost_config == result.experiment.transaction_cost_config
        engine.close()

    def test_recording_same_experiment_id_twice_is_idempotent(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        exp_repo = DuckDBExperimentRepository(engine)
        result = _run_backtest()
        exp_repo.record(result.experiment)
        exp_repo.record(result.experiment)
        assert len(exp_repo.list_all()) == 1
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        config = StorageConfig(tmp_path / "store")
        engine1 = StorageEngine(config)
        exp_repo1 = DuckDBExperimentRepository(engine1)
        result = _run_backtest()
        exp_repo1.record(result.experiment)
        engine1.close()

        engine2 = StorageEngine(config)
        exp_repo2 = DuckDBExperimentRepository(engine2)
        reloaded = exp_repo2.get(result.experiment.experiment_id)
        assert reloaded is not None
        assert reloaded.metrics.sharpe_ratio == result.experiment.metrics.sharpe_ratio
        engine2.close()

    def test_multiple_experiments_are_independently_queryable(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        exp_repo = DuckDBExperimentRepository(engine)
        r1 = _run_backtest()
        r2 = _run_backtest(initial_capital=50_000.0)  # a fresh BacktestEngine -> fresh tracker -> also "BT-000001"
        assert r1.experiment.experiment_id == r2.experiment.experiment_id == "BT-000001"
        assert r1.experiment.initial_capital != r2.experiment.initial_capital  # genuinely different runs

        exp_repo.record(r1.experiment)
        exp_repo.record(r2.experiment)

        # ADR-0115: this used to be documented as "idempotent no-op, by
        # design" -- but r2 is not a duplicate of r1, it is a second,
        # genuinely different experiment that merely happens to share
        # r1's auto-incremented id because each fresh ExperimentTracker
        # restarts its own counter at 1 (same restart-safety id-
        # collision class this project already guards against
        # elsewhere -- ai_gateway.QuotaManager, storage.data_repository
        # batch_id, evolution.ModelStatusTransition, etc.). The
        # repository's own natural-key dedup, correct in isolation,
        # silently discards r2's real result here. This is the actual,
        # confirmed (not merely hypothetical) behavior today -- no
        # production caller currently chains BacktestEngine output into
        # DuckDBExperimentRepository this way, so it is latent, not
        # exploited, but it is a real gap, not a design choice.
        assert len(exp_repo.list_all()) == 1
        assert exp_repo.get("BT-000001").initial_capital == r1.experiment.initial_capital  # r2 silently lost

    def test_a_caller_that_seeds_starting_id_from_the_repository_avoids_the_collision(self, tmp_path) -> None:
        # The fix path ADR-0115 added: ExperimentTracker(starting_id=...)
        # lets a caller that DOES chain independent runs into a shared
        # repository seed each fresh tracker past whatever is already
        # persisted, so a second genuinely different run gets its own,
        # distinct id instead of colliding with the first.
        engine = new_engine(tmp_path)
        exp_repo = DuckDBExperimentRepository(engine)

        r1 = _run_backtest()
        exp_repo.record(r1.experiment)

        next_id = _next_starting_id(exp_repo)
        r2 = _run_backtest(
            initial_capital=50_000.0, experiment_tracker=ExperimentTracker(starting_id=next_id),
        )
        assert r2.experiment.experiment_id != r1.experiment.experiment_id
        exp_repo.record(r2.experiment)

        assert len(exp_repo.list_all()) == 2
        assert exp_repo.get(r1.experiment.experiment_id).initial_capital == r1.experiment.initial_capital
        assert exp_repo.get(r2.experiment.experiment_id).initial_capital == r2.experiment.initial_capital
        engine.close()
