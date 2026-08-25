"""compute_candidate_decision_alternative: runs an actually-existing,
runnable alternative decision process (a `predict.predictor.Predictor` +
`decision.agent.DecisionAgent` pair) at a trade's own `decision_time`,
and reports what it would have decided -- the "alternative_action_1" /
"alternative_action_2" slot PROJECT_MASTER_PLAN.md section 33 and
Phase 3 (`docs/specifications/PHASE-3-trade-journal.md` section 7.2)
reserved for Phase 11, and ADR-0016 section 7 confirmed belongs here:
"comparing the selected action against a different model's or
strategy's hypothetical decision requires that alternative to actually
exist and be runnable."

See docs/specifications/PHASE-11-model-evolution.md section 8.

Point-in-time safety: the candidate `predictor`/`decision_agent` see
only an `AsOfDataView` whose clock is pinned to `decision_time` -- the
exact same `backtest.asof.AsOfDataView` + `backtest.clock.BacktestClock`
point-in-time guard every other phase's live decision path already uses
(Phase 2/5/6/7), not a new one invented here. Only the *return
measurement* afterwards is retrospective (uses `evaluation_time`,
already elapsed by call time), reusing Phase 3/10's own
`compute_hold_counterfactual`/`compute_cash_counterfactual` verbatim
rather than duplicating their price-fetch logic.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Optional, Sequence

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock
from backtest.portfolio import PortfolioView

from counterfactual.counterfactual import compute_cash_counterfactual

from data_infra.repository import DataRepository

from decision.agent import DecisionAgent

from predict.predictor import Predictor

from regime.models import CompositeRegimeObservation

from trade_journal.analysis import compute_hold_counterfactual
from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.models import AlternativeOutcome, CounterfactualRecord

# DecisionAction values whose realized exposure this function can turn
# into a return figure by reusing Phase 3's HOLD price-replay unchanged
# (a long position established at decision_time) or negated (a short).
# HOLD/EXIT/NO_TRADE all mean "no new directional exposure was taken" --
# economically equivalent to Phase 10's CASH counterfactual for the
# purpose of this return calculation (no position sizing/quantity is
# modeled here, matching HOLD/CASH's own documented simplicity).
_LONG_ACTIONS = frozenset({DecisionAction.BUY})
_SHORT_ACTIONS = frozenset({DecisionAction.SELL})
_FLAT_ACTIONS = frozenset({DecisionAction.HOLD, DecisionAction.EXIT, DecisionAction.NO_TRADE})


def compute_candidate_decision_alternative(
    repository: DataRepository,
    security_id: str,
    decision_time: datetime,
    evaluation_time: datetime,
    portfolio_state: Optional[PortfolioView],
    predictor: Predictor,
    decision_agent: DecisionAgent,
    *,
    candidate_id: str,
    regime: Optional[CompositeRegimeObservation] = None,
    risk_free_rate: float = 0.0,
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
    experiment_id: Optional[str] = None,
) -> AlternativeOutcome:
    if evaluation_time < decision_time:
        raise ValueError("evaluation_time must not be before decision_time")

    clock = BacktestClock(checkpoints=(decision_time,))
    data_view = AsOfDataView(repository, clock)

    prediction = predictor.predict(data_view, security_id, provenance=provenance, experiment_id=experiment_id)
    decision = decision_agent.decide(
        security_id, decision_time, prediction, regime, portfolio_state,
        provenance=provenance, experiment_id=experiment_id,
    )

    basis_suffix = f"candidate_model:{candidate_id}:{decision_agent.__class__.__name__}"

    if decision.action in _LONG_ACTIONS:
        base = compute_hold_counterfactual(repository, security_id, decision_time, evaluation_time)
        return dataclasses.replace(
            base, action=decision.action.value,
            basis=None if base.basis is None else f"{base.basis}|{basis_suffix}",
        )

    if decision.action in _SHORT_ACTIONS:
        base = compute_hold_counterfactual(repository, security_id, decision_time, evaluation_time)
        negated_return = None if base.hypothetical_return is None else -base.hypothetical_return
        return dataclasses.replace(
            base, action=decision.action.value, hypothetical_return=negated_return,
            basis=None if base.basis is None else f"{base.basis}|short|{basis_suffix}",
        )

    # _FLAT_ACTIONS (HOLD/EXIT/NO_TRADE): no new directional exposure
    base = compute_cash_counterfactual(decision_time, evaluation_time, risk_free_rate=risk_free_rate)
    return dataclasses.replace(base, action=decision.action.value, basis=f"{base.basis}|{basis_suffix}")


def append_candidate_alternatives(
    record: CounterfactualRecord, candidate_alternatives: Sequence[AlternativeOutcome]
) -> CounterfactualRecord:
    """Appends one or more candidate-model alternatives onto an existing
    `CounterfactualRecord` (e.g. the (HOLD, CASH) record Phase 10's
    `build_counterfactual_record` already produced) without modifying
    Phase 3/10 source -- `trade_journal.models.CounterfactualRecord.
    alternatives` is already an arbitrary-length tuple built exactly for
    this ("alternative_action_1"/"alternative_action_2" is a slot count
    from the master plan's prose, not a fixed-width schema)."""
    if not candidate_alternatives:
        return record
    return dataclasses.replace(record, alternatives=record.alternatives + tuple(candidate_alternatives))
