"""Provenance separation tests.

See docs/specifications/PHASE-10-counterfactual-attribution.md section 6.
"""

from __future__ import annotations

from datetime import date

import pytest
from counterfactual_helpers import make_bars_repo, utc
from journal_helpers import make_fill

from backtest.enums import OrderSide

from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.models import TradeRecord
from trade_journal.repository import InMemoryTradeJournalRepository

from counterfactual.pipeline import run_counterfactual_analysis, run_counterfactual_analysis_for_provenance


def _seed_journal() -> InMemoryTradeJournalRepository:
    journal = InMemoryTradeJournalRepository()
    hist_decision = journal.record_decision(
        decision_time=utc(2024, 1, 2), security_id="AAA", decision=DecisionAction.BUY,
        provenance=TradeProvenance.HISTORICAL_SIMULATION,
    )
    journal.record_trade(
        decision_id=hist_decision.snapshot_id, fill=make_fill(security_id="AAA", price=100.0),
        position_after=10.0, provenance=TradeProvenance.HISTORICAL_SIMULATION,
    )

    live_decision = journal.record_decision(
        decision_time=utc(2024, 1, 2), security_id="BBB", decision=DecisionAction.BUY,
        provenance=TradeProvenance.LIVE_TRADING,
    )
    journal.record_trade(
        decision_id=live_decision.snapshot_id,
        fill=make_fill(order_id="ORD-000002", security_id="BBB", price=200.0),
        position_after=5.0, provenance=TradeProvenance.LIVE_TRADING,
    )
    return journal


class TestCounterfactualNeverMixesProvenance:
    def test_each_trades_record_reflects_only_its_own_security_data(self) -> None:
        journal = _seed_journal()
        repo = make_bars_repo({date(2024, 1, 2): 100.0, date(2024, 1, 9): 110.0}, security_id="AAA")

        trades = journal.list_trades()
        aaa_trade = next(t for t in trades if t.security_id == "AAA")
        bbb_trade = next(t for t in trades if t.security_id == "BBB")

        aaa_record = run_counterfactual_analysis(repo, journal, aaa_trade.trade_id, utc(2024, 1, 9))
        # BBB has no bars in this repository at all -- its counterfactual
        # must honestly report insufficient_data, never borrow AAA's price
        # series just because both happen to be in the same call sequence.
        bbb_record = run_counterfactual_analysis(repo, journal, bbb_trade.trade_id, utc(2024, 1, 9))

        aaa_hold = next(a for a in aaa_record.alternatives if a.action == "HOLD")
        bbb_hold = next(a for a in bbb_record.alternatives if a.action == "HOLD")
        assert aaa_hold.hypothetical_return == pytest.approx(0.10)
        assert bbb_hold.hypothetical_return is None
        assert bbb_hold.basis == "insufficient_data"

    def test_batch_by_provenance_never_pulls_in_the_other_provenance(self) -> None:
        journal = _seed_journal()
        repo = make_bars_repo({date(2024, 1, 2): 100.0, date(2024, 1, 9): 110.0}, security_id="AAA")

        historical_only = run_counterfactual_analysis_for_provenance(
            repo, journal, TradeProvenance.HISTORICAL_SIMULATION, utc(2024, 1, 9),
        )
        live_only = run_counterfactual_analysis_for_provenance(
            repo, journal, TradeProvenance.LIVE_TRADING, utc(2024, 1, 9),
        )

        assert len(historical_only) == 1
        assert len(live_only) == 1
        assert historical_only[0].trade_id != live_only[0].trade_id
