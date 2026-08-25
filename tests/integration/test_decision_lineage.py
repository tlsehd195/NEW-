"""Category: Integration Test -- Regime -> Prediction -> Decision full
chain, persisted through the same DuckDB catalog, SQL-joinable, with
correct lineage fields (Phase 7 spec section 9, 11, 12).
"""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, make_security, trading_days
from predict_helpers import drifting_prices

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock, build_daily_checkpoints
from backtest.engine import BacktestConfig
from backtest.portfolio import PortfolioView

from storage.config import StorageConfig
from storage.decision_repository import DuckDBDecisionRepository
from storage.engine import StorageEngine
from storage.prediction_repository import DuckDBPredictionRepository
from storage.regime_repository import DuckDBRegimeRepository

from decision.agent import BaselineRuleDecisionAgent
from decision.config import DecisionConfig

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor

from regime.config import RegimeConfig
from regime.detector import RegimeDetector


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    bars = make_bars("AAA", days, drifting_prices(days))
    securities = [make_security("AAA", "AAA")]
    repo = build_repository(bars=bars, securities=securities)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA",), code_version="decision-lineage-integration-test",
    )
    return repo, config


class TestFullChainPersistenceAndLineage:
    def test_regime_prediction_decision_all_persist_and_survive_restart(self, tmp_path) -> None:
        repo, config = _scenario()
        calendar = repo.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
        clock = BacktestClock(checkpoints)
        view = AsOfDataView(repo, clock)

        predictor = DriftPredictor(PredictionConfig(lookback_days=20))
        regime_detector = RegimeDetector(RegimeConfig())
        agent = BaselineRuleDecisionAgent(DecisionConfig())

        store_config = StorageConfig(tmp_path / "store")
        engine1 = StorageEngine(store_config)
        regime_repo1 = DuckDBRegimeRepository(engine1)
        prediction_repo1 = DuckDBPredictionRepository(engine1)
        decision_repo1 = DuckDBDecisionRepository(engine1)

        portfolio = PortfolioView(as_of_time=checkpoints[0], cash=100_000.0, positions={}, portfolio_value=100_000.0)
        recorded = 0
        for i in range(len(checkpoints)):
            clock.index = i
            prediction = predictor.predict(view, "AAA")
            regime = regime_detector.compute_composite(view, "AAA")
            decision = agent.decide("AAA", view.current_time, prediction, regime, portfolio)

            prediction_repo1.record(prediction)
            regime_repo1.record_composite(regime)
            decision_repo1.record(decision)
            recorded += 1

        assert recorded == len(checkpoints)
        engine1.close()

        engine2 = StorageEngine(store_config)
        assert len(DuckDBPredictionRepository(engine2).list_all(security_id="AAA")) == len(checkpoints)
        assert len(DuckDBRegimeRepository(engine2).list_composites(subject_id="AAA")) == len(checkpoints)
        assert len(DuckDBDecisionRepository(engine2).list_all(security_id="AAA")) == len(checkpoints)
        engine2.close()

    def test_decision_lineage_fields_trace_back_to_the_prediction_and_regime_used(self, tmp_path) -> None:
        repo, config = _scenario()
        calendar = repo.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
        clock = BacktestClock(checkpoints)
        clock.index = 100
        view = AsOfDataView(repo, clock)

        predictor = DriftPredictor(PredictionConfig(lookback_days=20))
        regime_detector = RegimeDetector(RegimeConfig())
        agent = BaselineRuleDecisionAgent(DecisionConfig())

        prediction = predictor.predict(view, "AAA")
        regime = regime_detector.compute_composite(view, "AAA")
        portfolio = PortfolioView(as_of_time=view.current_time, cash=100_000.0, positions={}, portfolio_value=100_000.0)
        decision = agent.decide("AAA", view.current_time, prediction, regime, portfolio)

        assert decision.prediction_id == prediction.prediction_id
        assert decision.prediction_version == prediction.method_version
        from regime.enums import RegimeAxis

        assert decision.regime_version == regime.get(RegimeAxis.TREND).configuration_version
        assert decision.data_version == prediction.data_version

    def test_regime_prediction_decision_are_sql_joinable_in_one_catalog(self, tmp_path) -> None:
        repo, config = _scenario()
        calendar = repo.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
        clock = BacktestClock(checkpoints)
        view = AsOfDataView(repo, clock)

        predictor = DriftPredictor(PredictionConfig(lookback_days=20))
        regime_detector = RegimeDetector(RegimeConfig())
        agent = BaselineRuleDecisionAgent(DecisionConfig())

        engine = StorageEngine(StorageConfig(tmp_path / "store"))
        regime_repo = DuckDBRegimeRepository(engine)
        prediction_repo = DuckDBPredictionRepository(engine)
        decision_repo = DuckDBDecisionRepository(engine)

        portfolio = PortfolioView(as_of_time=checkpoints[0], cash=100_000.0, positions={}, portfolio_value=100_000.0)
        for i in range(min(30, len(checkpoints))):
            clock.index = i
            prediction = predictor.predict(view, "AAA")
            regime = regime_detector.compute_composite(view, "AAA")
            decision = agent.decide("AAA", view.current_time, prediction, regime, portfolio)
            prediction_repo.record(prediction)
            regime_repo.record_composite(regime)
            decision_repo.record(decision)

        rows = engine.connection.execute(
            "SELECT d.security_id, d.action, p.expected_return, r.composite_label "
            "FROM decision_outputs d "
            "JOIN predictions p ON p.prediction_id = d.prediction_id "
            "JOIN regime_composites r ON r.as_of_time = d.as_of_time AND r.subject_id = d.security_id "
            "LIMIT 5"
        ).fetchall()
        assert isinstance(rows, list)  # the three-way join executes -- all tables share one catalog
        engine.close()
