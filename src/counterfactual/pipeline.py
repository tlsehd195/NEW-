"""Counterfactual orchestration.

See docs/specifications/PHASE-10-counterfactual-attribution.md. Reads
already-recorded Trade Journal data (Phase 3, unmodified) and assembles a
CounterfactualRecord; storage is the caller's responsibility, mirroring
Phase 9's `learning.pipeline` design (compute here, persist there) --
this module never calls `journal.record_counterfactual` itself, so
running it twice never mutates the journal on its own.

Attribution has no equivalent orchestration function here:
`counterfactual.attribution.build_attribution_result` already takes an
already-fetched `backtest.experiment.ExperimentRecord` directly and is
the complete computation entry point -- wrapping it in another function
that also performed the `ExperimentRepository.get()` lookup would import
the storage layer into a domain package, which no other phase does
either (storage depends on domain packages, never the reverse).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from data_infra.repository import DataRepository

from trade_journal.models import CounterfactualRecord
from trade_journal.repository import TradeJournalRepository

from counterfactual.counterfactual import build_counterfactual_record


def run_counterfactual_analysis(
    data_repository: DataRepository,
    journal: TradeJournalRepository,
    trade_id: str,
    evaluation_time: datetime,
    *,
    risk_free_rate: float = 0.0,
    computed_at: Optional[datetime] = None,
) -> Optional[CounterfactualRecord]:
    """None (not an exception) when the trade or its decision cannot be
    found -- fail-closed, mirroring Phase 7's portfolio_state_unavailable
    -> NO_TRADE discipline rather than raising for a caller-recoverable
    condition."""
    trade = journal.get_trade(trade_id)
    if trade is None:
        return None
    decision = journal.get_decision(trade.decision_id)
    if decision is None:
        return None
    return build_counterfactual_record(
        data_repository,
        trade,
        decision.decision,
        decision.decision_time,
        evaluation_time,
        risk_free_rate=risk_free_rate,
        computed_at=computed_at,
    )


def run_counterfactual_analysis_for_provenance(
    data_repository: DataRepository,
    journal: TradeJournalRepository,
    provenance,
    evaluation_time: datetime,
    *,
    risk_free_rate: float = 0.0,
    computed_at: Optional[datetime] = None,
) -> list[CounterfactualRecord]:
    """Batch helper over every trade of one TradeProvenance -- never
    mixes trades of different provenance in one call (Phase 10 spec
    section 6)."""
    records: list[CounterfactualRecord] = []
    for trade in journal.list_trades(provenance=provenance):
        record = run_counterfactual_analysis(
            data_repository, journal, trade.trade_id, evaluation_time,
            risk_free_rate=risk_free_rate, computed_at=computed_at,
        )
        if record is not None:
            records.append(record)
    return records
