"""Category: persistence, restart, idempotency for the persistent
Attribution store (Phase 10 spec section 4.5, 10). Mirrors
tests/storage/test_trade_journal_persistence.py's
post_trade_analyses/counterfactuals restart-safety pattern -- the same
append/latest-wins discipline, applied to the new attribution_results
table.
"""

from __future__ import annotations

from counterfactual_helpers import make_experiment_record, make_performance_report, utc
from storage_helpers import new_engine

from storage.config import StorageConfig
from storage.counterfactual_repository import DuckDBAttributionRepository
from storage.engine import StorageEngine

from counterfactual.attribution import build_attribution_result


def _result(experiment_id: str = "BT-000001"):
    metrics = make_performance_report(cumulative_return=0.10, benchmark_cumulative_return=0.06)
    experiment = make_experiment_record(experiment_id=experiment_id, metrics=metrics)
    return build_attribution_result(experiment, computed_at=utc(2024, 6, 2))


class TestPersistenceAndRestart:
    def test_attribution_result_survives_restart(self, tmp_path) -> None:
        config = StorageConfig(tmp_path / "store")
        engine1 = StorageEngine(config)
        repo1 = DuckDBAttributionRepository(engine1)

        result = _result()
        repo1.record(result)
        engine1.close()

        engine2 = StorageEngine(config)
        repo2 = DuckDBAttributionRepository(engine2)
        reloaded = repo2.get("BT-000001")
        assert reloaded == result
        engine2.close()

    def test_reopening_an_empty_store_does_not_crash(self, tmp_path) -> None:
        config = StorageConfig(tmp_path / "store")
        engine1 = StorageEngine(config)
        engine1.close()

        engine2 = StorageEngine(config)
        repo2 = DuckDBAttributionRepository(engine2)
        assert repo2.get("BT-000001") is None
        assert repo2.list_all() == []
        engine2.close()


class TestRecordAndGet:
    def test_record_then_get_round_trips_exactly(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBAttributionRepository(engine)
        result = _result()
        repo.record(result)
        assert repo.get("BT-000001") == result
        engine.close()

    def test_recording_again_is_safe_and_get_returns_the_latest(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBAttributionRepository(engine)
        first = _result()
        repo.record(first)

        metrics = make_performance_report(cumulative_return=0.12, benchmark_cumulative_return=0.06)
        second = build_attribution_result(
            make_experiment_record(experiment_id="BT-000001", metrics=metrics), computed_at=utc(2024, 6, 3)
        )
        repo.record(second)

        assert repo.get("BT-000001") == second
        assert repo.get_history("BT-000001") == (first, second)
        engine.close()

    def test_different_experiments_do_not_collide(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBAttributionRepository(engine)
        a = _result(experiment_id="BT-000001")
        b = _result(experiment_id="BT-000002")
        repo.record(a)
        repo.record(b)
        assert repo.get("BT-000001").experiment_id == "BT-000001"
        assert repo.get("BT-000002").experiment_id == "BT-000002"
        engine.close()

    def test_list_all_returns_every_recorded_result(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBAttributionRepository(engine)
        repo.record(_result(experiment_id="BT-000001"))
        repo.record(_result(experiment_id="BT-000002"))
        assert {r.experiment_id for r in repo.list_all()} == {"BT-000001", "BT-000002"}
        engine.close()
