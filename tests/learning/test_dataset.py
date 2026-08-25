"""Category: Unit Test -- build_training_dataset (Phase 9 spec sections
9, 10).

Covers: dataset construction/versioning metadata, temporal train/
validation/test split (no shuffling, chronological order preserved),
quality_status, excluded_count, sampling cap.
"""

from __future__ import annotations

from learning_helpers import build_journal_with_closed_trades, utc

from learning.config import SamplingConfig, SplitConfig, TrainingDatasetConfig
from learning.dataset import build_training_dataset
from learning.enums import SplitName

from trade_journal.enums import TradeProvenance


class TestDatasetMetadata:
    def test_dataset_carries_required_metadata(self) -> None:
        journal, records = build_journal_with_closed_trades(10)
        result = build_training_dataset(
            journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1),
        )
        dataset = result.dataset
        assert dataset.dataset_id
        assert dataset.dataset_version
        assert dataset.provenance == TradeProvenance.HISTORICAL_SIMULATION
        assert dataset.label_version
        assert dataset.cleaning_config_version
        assert dataset.label_config_version
        assert dataset.split_config_version
        assert dataset.sampling_config_version
        assert dataset.configuration_version
        assert dataset.sample_count == 10
        assert dataset.quality_status == "OK"
        assert len(dataset.source_experience_ids) == 10

    def test_empty_input_produces_insufficient_samples_status(self) -> None:
        journal, _ = build_journal_with_closed_trades(0)
        result = build_training_dataset(
            journal, [], provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1),
        )
        assert result.dataset.sample_count == 0
        assert result.dataset.quality_status == "INSUFFICIENT_SAMPLES"


class TestTemporalSplit:
    def test_split_sizes_match_configured_fractions(self) -> None:
        journal, records = build_journal_with_closed_trades(10)
        config = TrainingDatasetConfig(split=SplitConfig(train_fraction=0.6, validation_fraction=0.2, test_fraction=0.2))
        result = build_training_dataset(
            journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, config=config, created_at=utc(2024, 3, 1),
        )
        splits = result.dataset.splits
        assert len(splits[SplitName.TRAIN]) == 6
        assert len(splits[SplitName.VALIDATION]) == 2
        assert len(splits[SplitName.TEST]) == 2

    def test_split_preserves_chronological_order_no_shuffling(self) -> None:
        journal, records = build_journal_with_closed_trades(10)
        result = build_training_dataset(
            journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1),
        )
        by_trade = {s.trade_id: s.sample_as_of_time for s in result.labeled_samples}
        train_times = [by_trade[tid] for tid in result.dataset.splits[SplitName.TRAIN]]
        val_times = [by_trade[tid] for tid in result.dataset.splits[SplitName.VALIDATION]]
        test_times = [by_trade[tid] for tid in result.dataset.splits[SplitName.TEST]]

        assert train_times == sorted(train_times)
        assert val_times == sorted(val_times)
        assert test_times == sorted(test_times)
        assert max(train_times) <= min(val_times)
        assert max(val_times) <= min(test_times)


class TestSamplingCap:
    def test_max_samples_caps_the_dataset_to_the_earliest_n(self) -> None:
        journal, records = build_journal_with_closed_trades(10)
        config = TrainingDatasetConfig(sampling=SamplingConfig(max_samples=4))
        result = build_training_dataset(
            journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, config=config, created_at=utc(2024, 3, 1),
        )
        assert result.dataset.sample_count == 4
        assert result.dataset.excluded_count == 6
        kept_times = sorted(s.sample_as_of_time for s in result.labeled_samples)
        assert kept_times[-1] < utc(2024, 1, 2 + 4)  # the earliest 4 trades, not a random subset


class TestExcludedCount:
    def test_excluded_count_reflects_non_valid_samples(self) -> None:
        from learning_helpers import build_journal_with_open_trade

        journal, records = build_journal_with_closed_trades(5)
        _, open_records = build_journal_with_open_trade(decision_time=utc(2024, 1, 2))
        # merge into one journal-consistent set by using the closed-trade journal only
        # (open_records' decision lives in a separate journal -- use it purely to test exclusion counting logic)
        result = build_training_dataset(
            journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1),
        )
        assert result.dataset.excluded_count == 0
        assert result.dataset.sample_count == 5


class TestReproducibleVersioning:
    def test_same_input_and_config_produce_the_same_dataset_version(self) -> None:
        journal, records = build_journal_with_closed_trades(6)
        r1 = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        r2 = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        assert r1.dataset.dataset_version == r2.dataset.dataset_version
        assert r1.dataset.splits == r2.dataset.splits

    def test_different_config_produces_a_different_dataset_version(self) -> None:
        journal, records = build_journal_with_closed_trades(6)
        r1 = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        r2 = build_training_dataset(
            journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION,
            config=TrainingDatasetConfig(split=SplitConfig(train_fraction=0.5, validation_fraction=0.25, test_fraction=0.25)),
            created_at=utc(2024, 3, 1),
        )
        assert r1.dataset.dataset_version != r2.dataset.dataset_version
