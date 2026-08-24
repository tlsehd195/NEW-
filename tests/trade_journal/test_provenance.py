"""Category: Provenance.
Category: Historical/paper/live separation.

See docs/specifications/PHASE-3-trade-journal.md sections 10.
"""

from __future__ import annotations

from journal_helpers import make_fill, make_order, utc

from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.repository import InMemoryTradeJournalRepository


class TestProvenance:
    def test_default_provenance_is_historical_simulation(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                             decision=DecisionAction.BUY, order=make_order())
        assert decision.provenance == TradeProvenance.HISTORICAL_SIMULATION

    def test_paper_and_live_provenance_can_be_tagged(self) -> None:
        journal = InMemoryTradeJournalRepository()
        paper = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                          decision=DecisionAction.BUY, order=make_order(order_id="ORD-P"),
                                          provenance=TradeProvenance.PAPER_TRADING)
        live = journal.record_decision(decision_time=utc(2024, 1, 3), security_id="AAA",
                                         decision=DecisionAction.BUY, order=make_order(order_id="ORD-L"),
                                         provenance=TradeProvenance.LIVE_TRADING)
        assert paper.provenance == TradeProvenance.PAPER_TRADING
        assert live.provenance == TradeProvenance.LIVE_TRADING


class TestProvenanceSeparation:
    def _seed(self, journal: InMemoryTradeJournalRepository) -> None:
        for i, provenance in enumerate(
            [TradeProvenance.HISTORICAL_SIMULATION, TradeProvenance.PAPER_TRADING, TradeProvenance.LIVE_TRADING]
        ):
            order = make_order(order_id=f"ORD-{i}")
            decision = journal.record_decision(
                decision_time=utc(2024, 1, 2 + i), security_id="AAA", decision=DecisionAction.BUY,
                order=order, provenance=provenance, experiment_id=f"EXP-{i}",
            )
            fill = make_fill(order_id=f"ORD-{i}", execution_time=utc(2024, 1, 3 + i))
            journal.record_trade(decision_id=decision.snapshot_id, fill=fill, position_after=10.0,
                                   provenance=provenance, experiment_id=f"EXP-{i}")

    def test_list_trades_filters_by_provenance(self) -> None:
        journal = InMemoryTradeJournalRepository()
        self._seed(journal)

        historical = journal.list_trades(provenance=TradeProvenance.HISTORICAL_SIMULATION)
        paper = journal.list_trades(provenance=TradeProvenance.PAPER_TRADING)
        live = journal.list_trades(provenance=TradeProvenance.LIVE_TRADING)

        assert len(historical) == 1 and historical[0].provenance == TradeProvenance.HISTORICAL_SIMULATION
        assert len(paper) == 1 and paper[0].provenance == TradeProvenance.PAPER_TRADING
        assert len(live) == 1 and live[0].provenance == TradeProvenance.LIVE_TRADING

    def test_unfiltered_list_returns_all_provenances_mixed_but_labeled(self) -> None:
        journal = InMemoryTradeJournalRepository()
        self._seed(journal)
        all_trades = journal.list_trades()
        assert len(all_trades) == 3
        assert {t.provenance for t in all_trades} == {
            TradeProvenance.HISTORICAL_SIMULATION, TradeProvenance.PAPER_TRADING, TradeProvenance.LIVE_TRADING,
        }

    def test_list_decisions_also_filters_by_provenance(self) -> None:
        journal = InMemoryTradeJournalRepository()
        self._seed(journal)
        assert len(journal.list_decisions(provenance=TradeProvenance.LIVE_TRADING)) == 1
