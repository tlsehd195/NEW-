"""Category: Model Comparison / Counterfactual Test -- an alternative,
actually-runnable decision process (Predictor + DecisionAgent) evaluated
at a trade's own decision_time, filling the "alternative_action_1/2"
slot PROJECT_MASTER_PLAN.md section 33 / ADR-0016 section 7 reserved for
Phase 11."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from counterfactual_helpers import make_bars_repo, utc as cf_utc

from decision.agent import BaselineRuleDecisionAgent
from decision.config import DecisionConfig

from evolution.counterfactual import append_candidate_alternatives, compute_candidate_decision_alternative

from predict.predictor import DriftPredictor, RandomWalkPredictor

from trade_journal.enums import DecisionAction
from trade_journal.models import AlternativeOutcome, CounterfactualRecord


def _uptrend_repo():
    closes = {}
    d = date(2024, 1, 2)
    price = 100.0
    for i in range(80):
        closes[d + timedelta(days=i)] = price
        price *= 1.01
    return make_bars_repo(closes)


def _flat_portfolio(as_of_time):
    from backtest.portfolio import PortfolioView

    return PortfolioView(as_of_time=as_of_time, cash=100_000.0, positions={}, portfolio_value=100_000.0)


class TestComputeCandidateDecisionAlternative:
    def test_buy_decision_uses_long_price_replay(self) -> None:
        repo = _uptrend_repo()
        decision_time = cf_utc(2024, 2, 20)
        evaluation_time = cf_utc(2024, 3, 1)
        alt = compute_candidate_decision_alternative(
            repo, "AAA", decision_time, evaluation_time, _flat_portfolio(decision_time),
            DriftPredictor(), BaselineRuleDecisionAgent(DecisionConfig(min_confidence=0.0, min_expected_return=-1.0)),
            candidate_id="CAND-000001",
        )
        assert alt.action == DecisionAction.BUY.value
        assert alt.hypothetical_return is not None
        assert alt.hypothetical_return > 0  # uptrend, long -> positive
        assert "candidate_model:CAND-000001" in alt.basis

    def test_no_trade_decision_uses_flat_cash_replay(self) -> None:
        repo = _uptrend_repo()
        decision_time = cf_utc(2024, 2, 20)
        evaluation_time = cf_utc(2024, 3, 1)
        alt = compute_candidate_decision_alternative(
            repo, "AAA", decision_time, evaluation_time, _flat_portfolio(decision_time),
            RandomWalkPredictor(), BaselineRuleDecisionAgent(DecisionConfig(min_confidence=2.0)),  # unreachable confidence -> always NO_TRADE
            candidate_id="CAND-000002",
        )
        assert alt.action == DecisionAction.NO_TRADE.value
        assert alt.hypothetical_return == 0.0  # zero risk-free rate default
        assert "candidate_model:CAND-000002" in alt.basis

    def test_evaluation_time_before_decision_time_rejected(self) -> None:
        repo = _uptrend_repo()
        decision_time = cf_utc(2024, 1, 20)
        with pytest.raises(ValueError):
            compute_candidate_decision_alternative(
                repo, "AAA", decision_time, decision_time - timedelta(days=1), _flat_portfolio(decision_time),
                DriftPredictor(), BaselineRuleDecisionAgent(), candidate_id="CAND-000003",
            )


class TestAppendCandidateAlternatives:
    def test_appends_without_removing_existing_alternatives(self) -> None:
        base = CounterfactualRecord(
            trade_id="TRD-000001", selected_action=DecisionAction.BUY,
            alternatives=(
                AlternativeOutcome(action="HOLD", hypothetical_return=0.01),
                AlternativeOutcome(action="CASH", hypothetical_return=0.0),
            ),
        )
        candidate_alt = AlternativeOutcome(action="SELL", hypothetical_return=-0.02, basis="candidate_model:CAND-000001")
        extended = append_candidate_alternatives(base, [candidate_alt])
        assert len(extended.alternatives) == 3
        assert extended.alternatives[:2] == base.alternatives
        assert extended.alternatives[2] == candidate_alt
        assert extended.trade_id == base.trade_id  # unrelated fields untouched

    def test_empty_candidate_list_is_a_no_op(self) -> None:
        base = CounterfactualRecord(trade_id="TRD-000002", selected_action=DecisionAction.HOLD)
        assert append_candidate_alternatives(base, []) is base
