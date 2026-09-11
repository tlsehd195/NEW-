"""Category: Persistence Test -- save, reload, idempotency, as_of query
for the persistent Position Sizing / Risk store (Phase 8 spec section
11-12)."""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, checkpoint, make_bars, trading_days
from decision_helpers import view_at
from predict_helpers import drifting_prices
from storage_helpers import new_engine

from backtest.portfolio import PortfolioView

from decision.agent import BaselineRuleDecisionAgent
from decision.config import DecisionConfig

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor

from regime.config import RegimeConfig
from regime.detector import RegimeDetector

from risk.enums import RiskCheckStatus
from risk.engine import DeterministicPortfolioRiskEngine
from risk.sizing import DeterministicPositionSizer

from storage.risk_repository import DuckDBPositionSizingRepository, DuckDBRiskRepository

from trade_journal.enums import TradeProvenance


def _sizing_and_risk():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    bars = make_bars("AAA", days, drifting_prices(days))
    repo = build_repository(bars=bars)
    view = view_at(repo, days, len(days) - 1)

    prediction = DriftPredictor(PredictionConfig(lookback_days=20)).predict(view, "AAA")
    regime = RegimeDetector(RegimeConfig()).compute_composite(view, "AAA")
    portfolio = PortfolioView(as_of_time=view.current_time, cash=100_000.0, positions={}, portfolio_value=100_000.0)
    decision = BaselineRuleDecisionAgent(DecisionConfig()).decide("AAA", view.current_time, prediction, regime, portfolio)

    bars_here = view.get_bars("AAA", view.current_time, view.current_time)
    price = 100.0  # deterministic fixed price for a persistence-focused test

    sizing = DeterministicPositionSizer().size("AAA", view.current_time, decision, prediction, regime, portfolio, current_price=price)
    checked = DeterministicPortfolioRiskEngine().assess("AAA", view.current_time, sizing, portfolio, current_price=price, value_history=[100_000.0] * 6)
    return sizing, checked


class TestPersistenceAndRestart:
    def test_sizing_and_risk_survive_restart(self, tmp_path) -> None:
        sizing, checked = _sizing_and_risk()
        engine1 = new_engine(tmp_path)
        sizing_repo1 = DuckDBPositionSizingRepository(engine1)
        risk_repo1 = DuckDBRiskRepository(engine1)
        stored_sizing = sizing_repo1.record(sizing)
        stored_risk = risk_repo1.record(checked)
        engine1.close()

        engine2 = new_engine(tmp_path)
        sizing_repo2 = DuckDBPositionSizingRepository(engine2)
        risk_repo2 = DuckDBRiskRepository(engine2)
        reloaded_sizing = sizing_repo2.get(stored_sizing.sizing_id)
        reloaded_risk = risk_repo2.get(stored_risk.risk_id)
        assert reloaded_sizing is not None
        assert reloaded_sizing.status == sizing.status
        assert reloaded_sizing.reason == sizing.reason
        assert reloaded_risk is not None
        assert reloaded_risk.status == checked.status
        assert reloaded_risk.risk_state is not None
        assert reloaded_risk.risk_state.portfolio_value == checked.risk_state.portfolio_value
        engine2.close()


class TestIdempotency:
    def test_recording_the_same_sizing_result_twice_does_not_duplicate(self, tmp_path) -> None:
        sizing, _ = _sizing_and_risk()
        engine = new_engine(tmp_path)
        repo = DuckDBPositionSizingRepository(engine)
        r1 = repo.record(sizing)
        r2 = repo.record(sizing)
        assert r1.sizing_id == r2.sizing_id
        assert len(repo.list_all()) == 1
        engine.close()

    def test_recording_the_same_risk_assessment_twice_does_not_duplicate(self, tmp_path) -> None:
        _, checked = _sizing_and_risk()
        engine = new_engine(tmp_path)
        repo = DuckDBRiskRepository(engine)
        c1 = repo.record(checked)
        c2 = repo.record(checked)
        assert c1.risk_id == c2.risk_id
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
        sizer = DeterministicPositionSizer()
        risk_engine = DeterministicPortfolioRiskEngine()

        engine = new_engine(tmp_path)
        sizing_repo = DuckDBPositionSizingRepository(engine)
        risk_repo = DuckDBRiskRepository(engine)
        for i in (50, 100, 150):
            view = view_at(data_repo, days, i)
            prediction = predictor.predict(view, "AAA")
            regime = regime_detector.compute_composite(view, "AAA")
            portfolio = PortfolioView(as_of_time=view.current_time, cash=100_000.0, positions={}, portfolio_value=100_000.0)
            decision = agent.decide("AAA", view.current_time, prediction, regime, portfolio)
            sizing = sizer.size("AAA", view.current_time, decision, prediction, regime, portfolio, current_price=100.0)
            checked = risk_engine.assess("AAA", view.current_time, sizing, portfolio, current_price=100.0)
            sizing_repo.record(sizing)
            risk_repo.record(checked)

        found_sizing = sizing_repo.get_as_of("AAA", checkpoint(days[120]))
        assert found_sizing is not None
        assert found_sizing.as_of_time == checkpoint(days[100])

        found_risk = risk_repo.get_as_of("AAA", checkpoint(days[120]))
        assert found_risk is not None
        assert found_risk.as_of_time == checkpoint(days[100])

        too_early_sizing = sizing_repo.get_as_of("AAA", checkpoint(days[10]))
        assert too_early_sizing is None
        engine.close()


class TestProvenanceAndLineage:
    def test_provenance_filter_isolates_categories(self, tmp_path) -> None:
        import dataclasses

        sizing, checked = _sizing_and_risk()
        engine = new_engine(tmp_path)
        sizing_repo = DuckDBPositionSizingRepository(engine)
        hist = dataclasses.replace(sizing, sizing_id="SIZE-H", provenance=TradeProvenance.HISTORICAL_SIMULATION)
        paper = dataclasses.replace(sizing, sizing_id="SIZE-P", provenance=TradeProvenance.PAPER_TRADING)
        sizing_repo.record(hist)
        sizing_repo.record(paper)

        assert len(sizing_repo.list_all(provenance=TradeProvenance.HISTORICAL_SIMULATION)) == 1
        assert len(sizing_repo.list_all(provenance=TradeProvenance.PAPER_TRADING)) == 1
        assert len(sizing_repo.list_all(provenance=TradeProvenance.LIVE_TRADING)) == 0
        engine.close()

    def test_full_lineage_round_trips(self, tmp_path) -> None:
        sizing, checked = _sizing_and_risk()
        engine = new_engine(tmp_path)
        sizing_repo = DuckDBPositionSizingRepository(engine)
        risk_repo = DuckDBRiskRepository(engine)
        sizing_repo.record(sizing)
        risk_repo.record(checked)

        reloaded_sizing = sizing_repo.get(sizing.sizing_id)
        assert reloaded_sizing.decision_id == sizing.decision_id
        assert reloaded_sizing.decision_version == sizing.decision_version
        assert reloaded_sizing.prediction_version == sizing.prediction_version

        reloaded_risk = risk_repo.get(checked.risk_id)
        assert reloaded_risk.sizing_id == checked.sizing_id
        assert reloaded_risk.decision_id == checked.decision_id
        assert reloaded_risk.sizing_version == checked.sizing_version
        assert reloaded_risk.strategy_version is None
        engine.close()


class TestGetAsOfTieBreak:
    def test_position_sizing_tie_deterministically_prefers_the_higher_sizing_id(self, tmp_path) -> None:
        # ADR-0117: two sizing results for the same security/as_of_time
        # (a different decision_id so the natural-key dedup doesn't
        # collapse them) used to resolve a tie via a bare
        # `ORDER BY as_of_time DESC LIMIT 1`.
        from datetime import datetime, timezone

        from risk.models import PositionSizingResult
        from trade_journal.enums import DecisionAction

        as_of = datetime(2024, 6, 1, 20, tzinfo=timezone.utc)

        def _sizing(sizing_id: str, decision_id: str) -> PositionSizingResult:
            return PositionSizingResult(
                sizing_id=sizing_id, security_id="AAA", as_of_time=as_of, status=RiskCheckStatus.PASS,
                reason="normal_sizing", decision_id=decision_id, decision_action=DecisionAction.BUY,
                proposed_target_weight=0.1, proposed_target_quantity=50.0, current_weight=0.0,
                current_quantity=0.0, sizing_version="sizer-v1", feature_version="feat-v1",
            )

        engine = new_engine(tmp_path)
        repo = DuckDBPositionSizingRepository(engine)
        repo.record(_sizing("SIZE-000001", "DEC-OUT-000001"))
        repo.record(_sizing("SIZE-000002", "DEC-OUT-000002"))

        result = repo.get_as_of("AAA", as_of)
        assert result is not None
        assert result.sizing_id == "SIZE-000002"
        engine.close()

    def test_risk_checked_tie_deterministically_prefers_the_higher_risk_id(self, tmp_path) -> None:
        from datetime import datetime, timezone

        from risk.models import RiskCheckedPosition

        as_of = datetime(2024, 6, 1, 20, tzinfo=timezone.utc)

        def _checked(risk_id: str, sizing_id: str) -> RiskCheckedPosition:
            return RiskCheckedPosition(
                risk_id=risk_id, security_id="AAA", as_of_time=as_of, status=RiskCheckStatus.PASS,
                reason="normal_sizing", breached_limits=(), final_target_weight=0.1, final_target_quantity=50.0,
                sizing_id=sizing_id, decision_id="DEC-OUT-000001", prediction_id=None,
                risk_state=None, risk_version="risk-v1", feature_version="feat-v1",
            )

        engine = new_engine(tmp_path)
        repo = DuckDBRiskRepository(engine)
        repo.record(_checked("RISK-000001", "SIZE-000001"))
        repo.record(_checked("RISK-000002", "SIZE-000002"))

        result = repo.get_as_of("AAA", as_of)
        assert result is not None
        assert result.risk_id == "RISK-000002"
        engine.close()
