"""Category: Provenance Test -- HISTORICAL_SIMULATION / PAPER_TRADING /
LIVE_TRADING are never mixed into one TrainingDataset (Phase 9 spec
section 6, instruction section 6).
"""

from __future__ import annotations

from learning_helpers import build_journal_with_closed_trades, utc

from learning.dataset import build_training_dataset

from trade_journal.enums import TradeProvenance
from trade_journal.experience import build_experience_records


class TestProvenanceIsolation:
    def test_dataset_built_from_historical_only_never_includes_paper_or_live(self) -> None:
        journal, hist_records = build_journal_with_closed_trades(5, provenance=TradeProvenance.HISTORICAL_SIMULATION)

        # Add PAPER_TRADING and LIVE_TRADING trades to the SAME journal.
        from journal_helpers import make_fill, make_order
        from backtest.enums import OrderSide
        from trade_journal.enums import DecisionAction
        from datetime import timedelta

        for i, provenance in enumerate([TradeProvenance.PAPER_TRADING, TradeProvenance.LIVE_TRADING]):
            day = utc(2024, 2, 1) + timedelta(days=i)
            oid = f"ORD-EXTRA-{i}"
            decision = journal.record_decision(
                decision_time=day, security_id="AAA", decision=DecisionAction.SELL,
                order=make_order(oid, side=OrderSide.SELL, decision_time=day), provenance=provenance,
            )
            journal.record_trade(
                decision_id=decision.snapshot_id,
                fill=make_fill(oid, side=OrderSide.SELL, decision_time=day, execution_time=day + timedelta(hours=1)),
                position_after=0.0, realized_pnl=1.0, realized_return=0.9, provenance=provenance,
            )

        all_records = build_experience_records(journal, created_at=utc(2024, 3, 1))
        result = build_training_dataset(
            journal, all_records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1),
        )
        assert result.dataset.provenance == TradeProvenance.HISTORICAL_SIMULATION
        assert result.dataset.sample_count == 5
        assert all(s.provenance == TradeProvenance.HISTORICAL_SIMULATION for s in result.labeled_samples)

    def test_provenance_is_a_required_argument_not_defaultable_to_mixing(self) -> None:
        import inspect

        params = inspect.signature(build_training_dataset).parameters
        assert params["provenance"].default is inspect.Parameter.empty

    def test_datasets_for_different_provenances_are_isolated_and_distinctly_versioned(self) -> None:
        journal_hist, hist_records = build_journal_with_closed_trades(4, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        journal_paper, paper_records = build_journal_with_closed_trades(4, provenance=TradeProvenance.PAPER_TRADING)

        hist_result = build_training_dataset(journal_hist, hist_records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        paper_result = build_training_dataset(journal_paper, paper_records, provenance=TradeProvenance.PAPER_TRADING, created_at=utc(2024, 3, 1))

        assert hist_result.dataset.provenance != paper_result.dataset.provenance
        assert hist_result.dataset.dataset_version != paper_result.dataset.dataset_version

    def test_requesting_live_trading_provenance_from_a_historical_only_journal_yields_empty_dataset(self) -> None:
        journal, records = build_journal_with_closed_trades(5, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        result = build_training_dataset(journal, records, provenance=TradeProvenance.LIVE_TRADING, created_at=utc(2024, 3, 1))
        assert result.dataset.sample_count == 0
        assert result.dataset.quality_status == "INSUFFICIENT_SAMPLES"
