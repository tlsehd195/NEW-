"""Category: Persistence Test -- save, reload, idempotency, as_of query
for the persistent Decision store (Phase 7 spec section 11-12)."""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, trading_days
from predict_helpers import drifting_prices, view_at

from storage.config import StorageConfig
from storage.decision_repository import DuckDBDecisionRepository
from storage.engine import StorageEngine
from storage_helpers import new_engine

from backtest.portfolio import PortfolioView

from decision.agent import BaselineRuleDecisionAgent
from decision.config import DecisionConfig

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor

from regime.config import RegimeConfig
from regime.detector import RegimeDetector

from trade_journal.enums import TradeProvenance


def _decision():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    bars = make_bars("AAA", days, drifting_prices(days))
    repo = build_repository(bars=bars)
    view = view_at(repo, days, len(days) - 1)

    prediction = DriftPredictor(PredictionConfig(lookback_days=20)).predict(view, "AAA")
    regime = RegimeDetector(RegimeConfig()).compute_composite(view, "AAA")
    portfolio = PortfolioView(as_of_time=view.current_time, cash=100_000.0, positions={}, portfolio_value=100_000.0)
    return BaselineRuleDecisionAgent(DecisionConfig()).decide("AAA", view.current_time, prediction, regime, portfolio)


class TestPersistenceAndRestart:
    def test_decision_survives_restart(self, tmp_path) -> None:
        config = StorageConfig(tmp_path / "store")
        decision = _decision()

        engine1 = StorageEngine(config)
        repo1 = DuckDBDecisionRepository(engine1)
        stored = repo1.record(decision)
        engine1.close()

        engine2 = StorageEngine(config)
        repo2 = DuckDBDecisionRepository(engine2)
        reloaded = repo2.get(stored.decision_id)
        assert reloaded is not None
        assert reloaded.action == decision.action
        assert reloaded.decision_reason == decision.decision_reason
        assert reloaded.target_weight_hint == decision.target_weight_hint
        engine2.close()


class TestIdempotency:
    def test_recording_the_same_decision_twice_does_not_duplicate(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDecisionRepository(engine)
        decision = _decision()
        d1 = repo.record(decision)
        d2 = repo.record(decision)
        assert d1.decision_id == d2.decision_id
        assert len(repo.list_all()) == 1
        engine.close()


class TestPointInTimeLookup:
    def test_get_as_of_returns_the_most_recent_at_or_before(self, tmp_path) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days))
        data_repo = build_repository(bars=bars)
        predictor = DriftPredictor(PredictionConfig(lookback_days=20))
        regime_detector = RegimeDetector(RegimeConfig())
        agent = BaselineRuleDecisionAgent()

        engine = new_engine(tmp_path)
        decision_repo = DuckDBDecisionRepository(engine)
        for i in (50, 100, 150):
            view = view_at(data_repo, days, i)
            prediction = predictor.predict(view, "AAA")
            regime = regime_detector.compute_composite(view, "AAA")
            portfolio = PortfolioView(as_of_time=view.current_time, cash=100_000.0, positions={}, portfolio_value=100_000.0)
            decision_repo.record(agent.decide("AAA", view.current_time, prediction, regime, portfolio))

        from backtest_helpers import checkpoint

        found = decision_repo.get_as_of("AAA", checkpoint(days[120]))
        assert found is not None
        assert found.as_of_time == checkpoint(days[100])

        too_early = decision_repo.get_as_of("AAA", checkpoint(days[10]))
        assert too_early is None
        engine.close()


class TestProvenanceAndLineage:
    def test_provenance_filter_isolates_categories(self, tmp_path) -> None:
        import dataclasses

        engine = new_engine(tmp_path)
        repo = DuckDBDecisionRepository(engine)
        decision = _decision()
        hist = dataclasses.replace(decision, decision_id="DEC-OUT-H", provenance=TradeProvenance.HISTORICAL_SIMULATION)
        paper = dataclasses.replace(decision, decision_id="DEC-OUT-P", provenance=TradeProvenance.PAPER_TRADING)
        repo.record(hist)
        repo.record(paper)

        assert len(repo.list_all(provenance=TradeProvenance.HISTORICAL_SIMULATION)) == 1
        assert len(repo.list_all(provenance=TradeProvenance.PAPER_TRADING)) == 1
        assert len(repo.list_all(provenance=TradeProvenance.LIVE_TRADING)) == 0
        engine.close()

    def test_full_lineage_round_trips(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDecisionRepository(engine)
        decision = _decision()
        repo.record(decision)

        reloaded = repo.get(decision.decision_id)
        assert reloaded.prediction_id == decision.prediction_id
        assert reloaded.prediction_version == decision.prediction_version
        assert reloaded.regime_version == decision.regime_version
        assert reloaded.feature_version == decision.feature_version
        assert reloaded.decision_version == decision.decision_version
        assert reloaded.model_version is None
        assert reloaded.strategy_version is None
        assert reloaded.risk_version is None
        engine.close()
