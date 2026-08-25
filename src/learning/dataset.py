"""build_training_dataset: orchestrates Data Cleaning -> Labeling ->
chronological Train/Validation/Test split into one `TrainingDataset`
(instruction sections 7, 8, 9, 10).

Reproducibility: the same `records` + `provenance` + `config` +
`as_of_cutoff` always produce the same `dataset_version` (a content
hash) and the same split assignment -- no randomness anywhere in this
module (instruction section 17, section 10: "random shuffle을 기본값으로
사용하지 않는다").

Leakage: `as_of_cutoff`, when supplied, excludes every experience whose
decision cannot be resolved *before* Data Cleaning ever sees it -- the
same "future data simply does not exist for this query" discipline
`backtest.asof.AsOfDataView` already established for market data,
applied here to Experience Dataset construction instead
(`tests/learning/test_learning_point_in_time.py` verifies rebuilding a
dataset at the same `as_of_cutoff` after new, later experiences are
added reproduces an identical dataset).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from data_infra.versioning import compute_data_version

from learning.cleaning import DataCleaner
from learning.config import TrainingDatasetConfig
from learning.enums import SampleStatus, SplitName
from learning.labeling import Labeler
from learning.models import CleaningResult, LabeledSample, TrainingDataset

from trade_journal.enums import TradeProvenance
from trade_journal.models import ExperienceRecord
from trade_journal.repository import TradeJournalRepository


class DatasetIdAllocator:
    def __init__(self) -> None:
        self._next_id = 1

    def allocate(self) -> str:
        did = f"TDS-{self._next_id:06d}"
        self._next_id += 1
        return did


@dataclass(frozen=True)
class DatasetBuildResult:
    dataset: TrainingDataset
    labeled_samples: tuple[LabeledSample, ...]
    cleaning_results: tuple[CleaningResult, ...]


def _resolve_decision_time(record: ExperienceRecord, journal: TradeJournalRepository) -> Optional[datetime]:
    decision = journal.get_decision(record.decision_id)
    return decision.decision_time if decision is not None else None


def _filter_by_cutoff(
    records: Sequence[ExperienceRecord], journal: TradeJournalRepository, as_of_cutoff: Optional[datetime],
) -> list[ExperienceRecord]:
    if as_of_cutoff is None:
        return list(records)
    kept: list[ExperienceRecord] = []
    for record in records:
        decision_time = _resolve_decision_time(record, journal)
        if decision_time is not None and decision_time <= as_of_cutoff:
            kept.append(record)
    return kept


def build_training_dataset(
    journal: TradeJournalRepository,
    records: Sequence[ExperienceRecord],
    *,
    provenance: TradeProvenance,
    config: TrainingDatasetConfig = TrainingDatasetConfig(),
    as_of_cutoff: Optional[datetime] = None,
    created_at: datetime,
    id_allocator: Optional[DatasetIdAllocator] = None,
) -> DatasetBuildResult:
    id_allocator = id_allocator or DatasetIdAllocator()

    scoped_records = _filter_by_cutoff(records, journal, as_of_cutoff)

    cleaner = DataCleaner(config.cleaning)
    cleaning_results = cleaner.clean(scoped_records, journal, provenance=provenance)

    valid_results = [r for r in cleaning_results if r.status == SampleStatus.VALID]
    valid_results.sort(key=lambda r: r.sample_as_of_time)
    if config.sampling.max_samples is not None:
        valid_results = valid_results[: config.sampling.max_samples]

    records_by_trade_id = {r.trade_id: r for r in scoped_records}
    labeler = Labeler(config.labeling)
    labeled_samples = labeler.label(valid_results, records_by_trade_id, journal, label_generated_at=created_at)
    labeled_samples.sort(key=lambda s: s.sample_as_of_time)

    split = config.split
    n = len(labeled_samples)
    n_train = int(n * split.train_fraction)
    n_val = int(n * split.validation_fraction)
    train_samples = labeled_samples[:n_train]
    val_samples = labeled_samples[n_train:n_train + n_val]
    test_samples = labeled_samples[n_train + n_val:]

    splits = {
        SplitName.TRAIN: tuple(s.trade_id for s in train_samples),
        SplitName.VALIDATION: tuple(s.trade_id for s in val_samples),
        SplitName.TEST: tuple(s.trade_id for s in test_samples),
    }

    source_experience_ids = tuple(sorted(s.experience_id for s in labeled_samples))
    data_versions = sorted({v for s in labeled_samples for v in s.data_version})
    feature_versions = {s.feature_version for s in labeled_samples if s.feature_version is not None}
    feature_version = sorted(feature_versions)[0] if feature_versions else None

    # A true content hash, not just an id-list hash: `trade_id`/
    # `experience_id` are scoped to a single TradeJournalRepository
    # instance (trade_journal/experience.py's own documented convention)
    # and therefore collide across two independently-built journals
    # (e.g. two different backtest runs each starting their own id
    # sequence at "TRD-000001") even when their actual sample content
    # differs. Hashing each sample's (trade_id, label_value,
    # sample_as_of_time) tuple, not just the id list, keeps
    # `dataset_version` a genuine content hash per this project's own
    # contract (data_infra.versioning.compute_data_version's docstring,
    # ADR-0003) -- two datasets are only version-identical when their
    # actual sample content, not merely their local id labels, matches.
    sample_fingerprint = sorted(
        (s.trade_id, s.label_value, s.sample_as_of_time.isoformat()) for s in labeled_samples
    )
    dataset_version = compute_data_version({
        "sample_fingerprint": sample_fingerprint,
        "source_experience_ids": list(source_experience_ids),
        "configuration_version": config.configuration_version(),
        "provenance": provenance.value,
        "as_of_cutoff": as_of_cutoff.isoformat() if as_of_cutoff is not None else None,
    })

    quality_status = "OK" if n > 0 else "INSUFFICIENT_SAMPLES"

    dataset = TrainingDataset(
        dataset_id=id_allocator.allocate(),
        dataset_version=dataset_version,
        created_at=created_at,
        source_experience_ids=source_experience_ids,
        provenance=provenance,
        feature_version=feature_version,
        label_version=labeler.version,
        data_version=tuple(data_versions),
        cleaning_config_version=config.cleaning.configuration_version(),
        label_config_version=config.labeling.configuration_version(),
        split_config_version=config.split.configuration_version(),
        sampling_config_version=config.sampling.configuration_version(),
        configuration_version=config.configuration_version(),
        sample_count=n,
        excluded_count=len(scoped_records) - n,
        quality_status=quality_status,
        splits=splits,
        as_of_cutoff=as_of_cutoff,
    )

    return DatasetBuildResult(
        dataset=dataset, labeled_samples=tuple(labeled_samples), cleaning_results=tuple(cleaning_results),
    )
