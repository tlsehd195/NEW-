"""Category: Leakage Test -- future data does not affect a past
TrainingDataset; feature cutoff and label separation; temporal split
integrity (Phase 9 spec section 5, 10).
"""

from __future__ import annotations

from datetime import timedelta

from learning_helpers import build_journal_with_closed_trades, utc

from learning.dataset import build_training_dataset
from learning.enums import SplitName

from trade_journal.enums import TradeProvenance
from trade_journal.experience import build_experience_records


class TestNoLookahead:
    def test_dataset_at_a_cutoff_is_unaffected_by_experiences_added_later(self) -> None:
        journal, records = build_journal_with_closed_trades(10)
        cutoff = utc(2024, 1, 6)

        before = build_training_dataset(
            journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION,
            as_of_cutoff=cutoff, created_at=utc(2024, 3, 1),
        )

        # Add 5 more, later, closed trades to the SAME journal.
        for i in range(10, 15):
            day = utc(2024, 1, 2) + timedelta(days=i)
            from journal_helpers import make_fill, make_order
            from backtest.enums import OrderSide
            from trade_journal.enums import DecisionAction

            oid = f"ORD-{i:04d}"
            decision = journal.record_decision(
                decision_time=day, security_id="AAA", decision=DecisionAction.SELL,
                order=make_order(oid, side=OrderSide.SELL, decision_time=day),
            )
            journal.record_trade(
                decision_id=decision.snapshot_id,
                fill=make_fill(oid, side=OrderSide.SELL, decision_time=day, execution_time=day + timedelta(hours=1)),
                position_after=0.0, realized_pnl=500.0, realized_return=0.5,
            )
        records_after = build_experience_records(journal, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 4, 1))

        after = build_training_dataset(
            journal, records_after, provenance=TradeProvenance.HISTORICAL_SIMULATION,
            as_of_cutoff=cutoff, created_at=utc(2024, 3, 1),
        )

        assert before.dataset.dataset_version == after.dataset.dataset_version
        assert before.dataset.sample_count == after.dataset.sample_count
        assert before.dataset.splits == after.dataset.splits
        assert {s.trade_id: s.label_value for s in before.labeled_samples} == {
            s.trade_id: s.label_value for s in after.labeled_samples
        }

    def test_no_experience_after_the_cutoff_appears_in_the_dataset(self) -> None:
        journal, records = build_journal_with_closed_trades(10)
        cutoff = utc(2024, 1, 6)
        result = build_training_dataset(
            journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION,
            as_of_cutoff=cutoff, created_at=utc(2024, 3, 1),
        )
        assert all(s.sample_as_of_time <= cutoff for s in result.labeled_samples)

    def test_replay_at_the_same_cutoff_is_deterministic(self) -> None:
        journal, records = build_journal_with_closed_trades(10)
        cutoff = utc(2024, 1, 6)
        r1 = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, as_of_cutoff=cutoff, created_at=utc(2024, 3, 1))
        r2 = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, as_of_cutoff=cutoff, created_at=utc(2024, 3, 1))
        assert r1.dataset.dataset_version == r2.dataset.dataset_version


class TestFeatureLabelCutoffSeparation:
    def test_feature_cutoff_time_never_exceeds_sample_as_of_time(self) -> None:
        journal, records = build_journal_with_closed_trades(10)
        result = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        for sample in result.labeled_samples:
            assert sample.feature_cutoff_time <= sample.sample_as_of_time

    def test_label_start_time_is_not_before_feature_cutoff(self) -> None:
        journal, records = build_journal_with_closed_trades(10)
        result = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        for sample in result.labeled_samples:
            assert sample.label_start_time >= sample.feature_cutoff_time


class TestTemporalSplitIntegrity:
    def test_no_train_sample_is_chronologically_after_any_test_sample(self) -> None:
        journal, records = build_journal_with_closed_trades(10)
        result = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        by_trade = {s.trade_id: s.sample_as_of_time for s in result.labeled_samples}
        max_train = max(by_trade[t] for t in result.dataset.splits[SplitName.TRAIN])
        min_test = min(by_trade[t] for t in result.dataset.splits[SplitName.TEST])
        assert max_train <= min_test

    def test_no_trade_id_appears_in_more_than_one_split(self) -> None:
        journal, records = build_journal_with_closed_trades(10)
        result = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        train = set(result.dataset.splits[SplitName.TRAIN])
        val = set(result.dataset.splits[SplitName.VALIDATION])
        test = set(result.dataset.splits[SplitName.TEST])
        assert train.isdisjoint(val)
        assert train.isdisjoint(test)
        assert val.isdisjoint(test)
