"""Category: persistence, restart, idempotency, provenance, version
lineage for the persistent Prediction store (Phase 6 spec section 11, 13)."""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, trading_days
from predict_helpers import drifting_prices, view_at

from storage.config import StorageConfig
from storage.engine import StorageEngine
from storage.prediction_repository import DuckDBPredictionRepository
from storage_helpers import new_engine

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor

from trade_journal.enums import TradeProvenance


def _prediction():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    bars = make_bars("AAA", days, drifting_prices(days))
    repo = build_repository(bars=bars)
    view = view_at(repo, days, len(days) - 1)
    return DriftPredictor().predict(view, "AAA")


class TestPersistenceAndRestart:
    def test_prediction_survives_restart(self, tmp_path) -> None:
        config = StorageConfig(tmp_path / "store")
        prediction = _prediction()

        engine1 = StorageEngine(config)
        repo1 = DuckDBPredictionRepository(engine1)
        stored = repo1.record(prediction)
        engine1.close()

        engine2 = StorageEngine(config)
        repo2 = DuckDBPredictionRepository(engine2)
        reloaded = repo2.get(stored.prediction_id)
        assert reloaded is not None
        assert reloaded.expected_return == prediction.expected_return
        assert reloaded.probability == prediction.probability
        assert reloaded.configuration_version == prediction.configuration_version
        engine2.close()


class TestIdempotency:
    def test_recording_the_same_prediction_twice_does_not_duplicate(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBPredictionRepository(engine)
        prediction = _prediction()
        p1 = repo.record(prediction)
        p2 = repo.record(prediction)
        assert p1.prediction_id == p2.prediction_id
        assert len(repo.list_all()) == 1
        engine.close()


class TestPointInTimeLookup:
    def test_get_as_of_returns_the_most_recent_at_or_before(self, tmp_path) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days))
        data_repo = build_repository(bars=bars)
        predictor = DriftPredictor()

        engine = new_engine(tmp_path)
        pred_repo = DuckDBPredictionRepository(engine)
        for i in (50, 100, 150):
            pred_repo.record(predictor.predict(view_at(data_repo, days, i), "AAA"))

        from backtest_helpers import checkpoint

        found = pred_repo.get_as_of("AAA", checkpoint(days[120]))
        assert found is not None
        assert found.as_of_time == checkpoint(days[100])

        too_early = pred_repo.get_as_of("AAA", checkpoint(days[10]))
        assert too_early is None
        engine.close()


class TestProvenanceAndVersionLineage:
    def test_provenance_filter_isolates_categories(self, tmp_path) -> None:
        import dataclasses

        engine = new_engine(tmp_path)
        repo = DuckDBPredictionRepository(engine)
        prediction = _prediction()
        hist = dataclasses.replace(
            prediction, prediction_id="PRED-H", provenance=TradeProvenance.HISTORICAL_SIMULATION,
        )
        paper = dataclasses.replace(
            prediction, prediction_id="PRED-P", provenance=TradeProvenance.PAPER_TRADING,
        )
        repo.record(hist)
        repo.record(paper)

        assert len(repo.list_all(provenance=TradeProvenance.HISTORICAL_SIMULATION)) == 1
        assert len(repo.list_all(provenance=TradeProvenance.PAPER_TRADING)) == 1
        assert len(repo.list_all(provenance=TradeProvenance.LIVE_TRADING)) == 0
        engine.close()

    def test_full_lineage_round_trips(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBPredictionRepository(engine)
        prediction = _prediction()
        repo.record(prediction)

        reloaded = repo.get(prediction.prediction_id)
        assert reloaded.feature_version == prediction.feature_version
        assert reloaded.method_version == prediction.method_version
        assert reloaded.data_version == prediction.data_version
        assert reloaded.model_version == prediction.model_version
        engine.close()
