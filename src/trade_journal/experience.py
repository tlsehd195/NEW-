"""Trade Journal -> Experience Dataset conversion.

See docs/specifications/PHASE-3-trade-journal.md section 5.8, 10.2.

Note on experience_id: scoped to a single build_experience_records()
call, not a globally monotonic sequence like the repository's DEC-/TRD-
ids — this is a derived, on-demand transformation (like a report),
not a stateful journal record requiring cross-call identity.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.models import ExperienceRecord
from trade_journal.repository import TradeJournalRepository


def build_experience_records(
    journal: TradeJournalRepository,
    *,
    provenance: Optional[TradeProvenance] = None,
    created_at: Optional[datetime] = None,
) -> list[ExperienceRecord]:
    records: list[ExperienceRecord] = []
    for index, trade in enumerate(journal.list_trades(provenance=provenance), start=1):
        decision = journal.get_decision(trade.decision_id)
        post_trade_analysis = journal.get_post_trade_analysis(trade.trade_id)
        counterfactual = journal.get_counterfactual(trade.trade_id)

        action = decision.decision if decision is not None else DecisionAction(trade.side.value)

        expected_outcome = None
        if decision is not None and (decision.expected_return is not None or decision.expected_risk is not None):
            expected_outcome = {
                "expected_return": decision.expected_return,
                "expected_risk": decision.expected_risk,
            }

        actual_outcome = {
            "realized_pnl": trade.realized_pnl,
            "realized_return": trade.realized_return,
            "holding_period": trade.holding_period,
        }

        # A reward signal is populated only for a trade that actually
        # realized a return (a closing/reducing SELL) — an opening BUY
        # has no realization yet, so reward stays None rather than being
        # fabricated as 0.0 or some other placeholder (Phase 3 spec
        # section 5.8: this identity mapping is a documented placeholder
        # default, not a claimed-correct reward function; the real reward
        # function design belongs to Phase 9).
        reward = trade.realized_return

        record = ExperienceRecord(
            experience_id=f"XR-{index:06d}",
            trade_id=trade.trade_id,
            decision_id=trade.decision_id,
            state={
                "market_state": decision.market_state if decision is not None else {},
                "portfolio_state": decision.portfolio_state if decision is not None else None,
            },
            action=action,
            actual_outcome=actual_outcome,
            expected_outcome=expected_outcome,
            reward=reward,
            market_regime=None,  # reserved — Phase 5
            risk_state=decision.risk_state if decision is not None else None,
            prediction_error=post_trade_analysis.prediction_error if post_trade_analysis is not None else None,
            counterfactual_results=counterfactual.alternatives if counterfactual is not None else None,
            provenance=trade.provenance,
            data_version=decision.data_version if decision is not None else None,
            strategy_version=decision.strategy_version if decision is not None else "unknown",
            model_version=decision.model_version if decision is not None else None,
            created_at=created_at,
        )
        records.append(record)
    return records
