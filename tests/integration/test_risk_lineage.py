"""Category: Integration Test -- Regime -> Prediction -> Decision ->
Position Sizing -> Risk Engine full chain, persisted through the same
DuckDB catalog, SQL-joinable, with correct lineage fields (Phase 8 spec
section 9, 11, 12).
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
from storage.risk_repository import DuckDBPositionSizingRepository, DuckDBRiskRepository

from decision.agent import BaselineRuleDecisionAgent
from decision.config import DecisionConfig

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor

from regime.config import RegimeConfig
from regime.detector import RegimeDetector

from risk.config import PositionSizingConfig, RiskConfig
from risk.engine import DeterministicPortfolioRiskEngine
from risk.sizing import DeterministicPositionSizer


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    bars = make_bars("AAA", days, drifting_prices(days))
    securities = [make_security("AAA", "AAA")]
    repo = build_repository(bars=bars, securities=securities)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA",), code_version="risk-lineage-integration-test",
    )
    return repo, config


class TestFullChainPersistenceAndLineage:
    def test_full_chain_persists_and_survives_restart(self, tmp_path) -> None:
        repo, config = _scenario()
        calendar = repo.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
        clock = BacktestClock(checkpoints)
        view = AsOfDataView(repo, clock)

        predictor = DriftPredictor(PredictionConfig(lookback_days=20))
        regime_detector = RegimeDetector(RegimeConfig())
        agent = BaselineRuleDecisionAgent(DecisionConfig())
        sizer = DeterministicPositionSizer(PositionSizingConfig())
        risk_engine = DeterministicPortfolioRiskEngine(RiskConfig())

        store_config = StorageConfig(tmp_path / "store")
        engine1 = StorageEngine(store_config)
        regime_repo1 = DuckDBRegimeRepository(engine1)
        prediction_repo1 = DuckDBPredictionRepository(engine1)
        decision_repo1 = DuckDBDecisionRepository(engine1)
        sizing_repo1 = DuckDBPositionSizingRepository(engine1)
        risk_repo1 = DuckDBRiskRepository(engine1)

        portfolio = PortfolioView(as_of_time=checkpoints[0], cash=100_000.0, positions={}, portfolio_value=100_000.0)
        recorded = 0
        for i in range(min(30, len(checkpoints))):
            clock.index = i
            prediction = predictor.predict(view, "AAA")
            regime = regime_detector.compute_composite(view, "AAA")
            decision = agent.decide("AAA", view.current_time, prediction, regime, portfolio)
            sizing = sizer.size("AAA", view.current_time, decision, prediction, regime, portfolio, current_price=100.0)
            checked = risk_engine.assess("AAA", view.current_time, sizing, portfolio, current_price=100.0)

            prediction_repo1.record(prediction)
            regime_repo1.record_composite(regime)
            decision_repo1.record(decision)
            sizing_repo1.record(sizing)
            risk_repo1.record(checked)
            recorded += 1

        assert recorded == 30
        engine1.close()

        engine2 = StorageEngine(store_config)
        assert len(DuckDBPredictionRepository(engine2).list_all(security_id="AAA")) == 30
        assert len(DuckDBRegimeRepository(engine2).list_composites(subject_id="AAA")) == 30
        assert len(DuckDBDecisionRepository(engine2).list_all(security_id="AAA")) == 30
        assert len(DuckDBPositionSizingRepository(engine2).list_all(security_id="AAA")) == 30
        assert len(DuckDBRiskRepository(engine2).list_all(security_id="AAA")) == 30
        engine2.close()

    def test_lineage_fields_trace_back_through_the_whole_chain(self, tmp_path) -> None:
        repo, config = _scenario()
        calendar = repo.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
        clock = BacktestClock(checkpoints)
        clock.index = 100
        view = AsOfDataView(repo, clock)

        predictor = DriftPredictor(PredictionConfig(lookback_days=20))
        regime_detector = RegimeDetector(RegimeConfig())
        agent = BaselineRuleDecisionAgent(DecisionConfig())
        sizer = DeterministicPositionSizer()
        risk_engine = DeterministicPortfolioRiskEngine()

        prediction = predictor.predict(view, "AAA")
        regime = regime_detector.compute_composite(view, "AAA")
        portfolio = PortfolioView(as_of_time=view.current_time, cash=100_000.0, positions={}, portfolio_value=100_000.0)
        decision = agent.decide("AAA", view.current_time, prediction, regime, portfolio)
        sizing = sizer.size("AAA", view.current_time, decision, prediction, regime, portfolio, current_price=100.0)
        checked = risk_engine.assess("AAA", view.current_time, sizing, portfolio, current_price=100.0)

        assert sizing.decision_id == decision.decision_id
        assert sizing.prediction_id == decision.prediction_id
        assert sizing.decision_version == decision.decision_version
        assert sizing.prediction_version == decision.prediction_version

        assert checked.sizing_id == sizing.sizing_id
        assert checked.decision_id == sizing.decision_id
        assert checked.prediction_id == sizing.prediction_id
        assert checked.sizing_version == sizing.sizing_version
        assert checked.decision_version == sizing.decision_version
        assert checked.strategy_version is None  # honest -- no Strategy consumer yet, same as Decision/Sizing

    def test_full_chain_is_sql_joinable_in_one_catalog(self, tmp_path) -> None:
        repo, config = _scenario()
        calendar = repo.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
        clock = BacktestClock(checkpoints)
        view = AsOfDataView(repo, clock)

        predictor = DriftPredictor(PredictionConfig(lookback_days=20))
        regime_detector = RegimeDetector(RegimeConfig())
        agent = BaselineRuleDecisionAgent(DecisionConfig())
        sizer = DeterministicPositionSizer()
        risk_engine = DeterministicPortfolioRiskEngine()

        engine = StorageEngine(StorageConfig(tmp_path / "store"))
        regime_repo = DuckDBRegimeRepository(engine)
        prediction_repo = DuckDBPredictionRepository(engine)
        decision_repo = DuckDBDecisionRepository(engine)
        sizing_repo = DuckDBPositionSizingRepository(engine)
        risk_repo = DuckDBRiskRepository(engine)

        portfolio = PortfolioView(as_of_time=checkpoints[0], cash=100_000.0, positions={}, portfolio_value=100_000.0)
        for i in range(min(30, len(checkpoints))):
            clock.index = i
            prediction = predictor.predict(view, "AAA")
            regime = regime_detector.compute_composite(view, "AAA")
            decision = agent.decide("AAA", view.current_time, prediction, regime, portfolio)
            sizing = sizer.size("AAA", view.current_time, decision, prediction, regime, portfolio, current_price=100.0)
            checked = risk_engine.assess("AAA", view.current_time, sizing, portfolio, current_price=100.0)
            prediction_repo.record(prediction)
            regime_repo.record_composite(regime)
            decision_repo.record(decision)
            sizing_repo.record(sizing)
            risk_repo.record(checked)

        rows = engine.connection.execute(
            "SELECT rk.security_id, rk.status, sz.status, d.action, p.expected_return, r.composite_label "
            "FROM risk_assessments rk "
            "JOIN position_sizing_results sz ON sz.sizing_id = rk.sizing_id "
            "JOIN decision_outputs d ON d.decision_id = rk.decision_id "
            "JOIN predictions p ON p.prediction_id = rk.prediction_id "
            "JOIN regime_composites r ON r.as_of_time = d.as_of_time AND r.subject_id = d.security_id "
            "LIMIT 5"
        ).fetchall()
        assert isinstance(rows, list)  # the five-way join executes -- all tables share one catalog
        engine.close()
