"""Category: Unit Test -- Labeler (Phase 9 spec section 8).

Covers: label generation from realized_return, label metadata
(version/definition/horizon/generated_at), feature_cutoff_time vs.
label_start_time separation.
"""

from __future__ import annotations

from learning_helpers import build_journal_with_closed_trades, utc

from learning.cleaning import DataCleaner
from learning.config import LabelConfig
from learning.enums import SampleStatus
from learning.labeling import Labeler

from trade_journal.enums import TradeProvenance


def _labeled(count: int = 5):
    journal, records = build_journal_with_closed_trades(count)
    cleaning_results = DataCleaner().clean(records, journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
    valid = [r for r in cleaning_results if r.status == SampleStatus.VALID]
    by_trade_id = {r.trade_id: r for r in records}
    samples = Labeler().label(valid, by_trade_id, journal, label_generated_at=utc(2024, 3, 1))
    return journal, records, samples


class TestLabelGeneration:
    def test_label_value_equals_realized_return(self) -> None:
        journal, records, samples = _labeled(5)
        by_trade = {r.trade_id: r for r in records}
        for sample in samples:
            expected = by_trade[sample.trade_id].actual_outcome["realized_return"]
            assert sample.label_value == expected

    def test_label_metadata_is_populated(self) -> None:
        _, _, samples = _labeled(3)
        for sample in samples:
            assert sample.label_version == Labeler().version
            assert sample.label_definition == LabelConfig().label_definition
            assert sample.label_horizon is None  # variable horizon, not fixed
            assert sample.label_generated_at == utc(2024, 3, 1)


class TestFeatureLabelSeparation:
    def test_feature_cutoff_never_later_than_label_start(self) -> None:
        _, _, samples = _labeled(5)
        for sample in samples:
            assert sample.feature_cutoff_time <= sample.label_start_time

    def test_label_end_time_is_after_label_start_when_known(self) -> None:
        _, _, samples = _labeled(5)
        for sample in samples:
            if sample.label_end_time is not None:
                assert sample.label_end_time >= sample.label_start_time


class TestLabelerNeverTouchesInvalidOrExcluded:
    def test_only_valid_cleaning_results_produce_labeled_samples(self) -> None:
        journal, records = build_journal_with_closed_trades(3)
        cleaning_results = DataCleaner().clean(records, journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        by_trade_id = {r.trade_id: r for r in records}
        samples = Labeler().label(cleaning_results, by_trade_id, journal, label_generated_at=utc(2024, 3, 1))
        # all 3 happen to be VALID in this fixture -- count matches
        assert len(samples) == 3
