"""Shared test helpers for the Phase 9 Learning Engine test suite."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from journal_helpers import make_fill, make_order, utc

from backtest.enums import OrderSide
from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.experience import build_experience_records
from trade_journal.models import ExperienceRecord
from trade_journal.repository import InMemoryTradeJournalRepository, TradeJournalRepository


def build_journal_with_closed_trades(
    count: int, *, start: datetime = utc(2024, 1, 2), realized_return_fn=None,
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
) -> tuple[TradeJournalRepository, list[ExperienceRecord]]:
    """Builds a journal with `count` fully-closed (SELL) trades, one per
    day starting at `start`, each with a distinct, deterministic
    realized_return -- a clean chronological series for temporal-split
    and leakage tests."""
    journal = InMemoryTradeJournalRepository()
    realized_return_fn = realized_return_fn or (lambda i: 0.01 * ((i % 5) - 2))
    for i in range(count):
        day = start + timedelta(days=i)
        oid = f"ORD-{i:04d}"
        decision = journal.record_decision(
            decision_time=day, security_id="AAA", decision=DecisionAction.SELL,
            order=make_order(oid, side=OrderSide.SELL, decision_time=day), provenance=provenance,
        )
        journal.record_trade(
            decision_id=decision.snapshot_id,
            fill=make_fill(oid, side=OrderSide.SELL, decision_time=day, execution_time=day + timedelta(hours=1)),
            position_after=0.0, realized_pnl=100.0 * realized_return_fn(i), realized_return=realized_return_fn(i),
            provenance=provenance,
        )
    records = build_experience_records(journal, provenance=provenance, created_at=start + timedelta(days=count + 1))
    return journal, records


def build_journal_with_open_trade(
    *, decision_time: datetime = utc(2024, 1, 2), provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
) -> tuple[TradeJournalRepository, list[ExperienceRecord]]:
    """One opening BUY with no realized outcome yet (reward/realized_return
    both None) -- the "no_realized_outcome" Data Cleaning case."""
    journal = InMemoryTradeJournalRepository()
    decision = journal.record_decision(
        decision_time=decision_time, security_id="AAA", decision=DecisionAction.BUY,
        order=make_order("ORD-OPEN", side=OrderSide.BUY, decision_time=decision_time), provenance=provenance,
    )
    journal.record_trade(
        decision_id=decision.snapshot_id, fill=make_fill("ORD-OPEN", side=OrderSide.BUY, decision_time=decision_time),
        position_after=10.0, provenance=provenance,
    )
    records = build_experience_records(journal, provenance=provenance, created_at=decision_time + timedelta(days=1))
    return journal, records


__all__ = [
    "utc", "build_journal_with_closed_trades", "build_journal_with_open_trade",
]
