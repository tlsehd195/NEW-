"""Category: Version / Lineage Test -- ModelLineageRecord tracks each
candidate's generation and parent, with generation always derived (never
caller-supplied)."""

from __future__ import annotations

import dataclasses

import pytest

from evolution_helpers import build_dataset, utc

from evolution.lineage import derive_lineage
from evolution.models import ModelLineageRecord
from evolution.repository import InMemoryModelLineageRepository
from evolution.trainer import TrailingWindowMeanTrainer

from learning.trainer import MeanRewardBaselineTrainer


class TestDeriveLineage:
    def test_root_candidate_has_generation_zero_and_no_parent(self) -> None:
        result = build_dataset(15)
        candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        lineage = derive_lineage(candidate, lineage_basis="initial")
        assert lineage.generation == 0
        assert lineage.parent_candidate_id is None

    def test_child_candidate_generation_is_parent_plus_one(self) -> None:
        result = build_dataset(15)
        root_candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        root_lineage = derive_lineage(root_candidate)

        # distinct trainer instances each allocate their own in-process
        # "CAND-000001" -- give the child a distinct id the way a
        # storage-layer sequence would (ADR-0015 section 6 precedent).
        child_candidate = TrailingWindowMeanTrainer(window=4).train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        child_candidate = dataclasses.replace(child_candidate, candidate_id="CAND-000002")
        child_lineage = derive_lineage(child_candidate, parent=root_lineage, lineage_basis="hyperparameter_variation")

        assert child_lineage.generation == 1
        assert child_lineage.parent_candidate_id == root_candidate.candidate_id
        assert child_lineage.candidate_id != child_lineage.parent_candidate_id

    def test_grandchild_generation_is_two(self) -> None:
        result = build_dataset(15)
        gen0_candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        gen0 = derive_lineage(dataclasses.replace(gen0_candidate, candidate_id="CAND-000001"))
        gen1_candidate = TrailingWindowMeanTrainer(window=3).train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        gen1_candidate = dataclasses.replace(gen1_candidate, candidate_id="CAND-000002")
        gen1 = derive_lineage(gen1_candidate, parent=gen0, lineage_basis="hyperparameter_variation")
        gen2_candidate = TrailingWindowMeanTrainer(window=6).train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        gen2_candidate = dataclasses.replace(gen2_candidate, candidate_id="CAND-000003")
        gen2 = derive_lineage(gen2_candidate, parent=gen1, lineage_basis="hyperparameter_variation")
        assert gen2.generation == 2
        assert gen2.parent_candidate_id == gen1_candidate.candidate_id


class TestModelLineageRecordValidation:
    def test_root_cannot_have_nonzero_generation(self) -> None:
        with pytest.raises(ValueError):
            ModelLineageRecord(
                candidate_id="CAND-000001", parent_candidate_id=None, generation=1,
                lineage_basis="initial", dataset_id="TDS-000001", dataset_version="v1",
                provenance=_provenance(),
            )

    def test_child_cannot_have_generation_zero(self) -> None:
        with pytest.raises(ValueError):
            ModelLineageRecord(
                candidate_id="CAND-000002", parent_candidate_id="CAND-000001", generation=0,
                lineage_basis="hyperparameter_variation", dataset_id="TDS-000001", dataset_version="v1",
                provenance=_provenance(),
            )

    def test_negative_generation_rejected(self) -> None:
        with pytest.raises(ValueError):
            ModelLineageRecord(
                candidate_id="CAND-000003", parent_candidate_id=None, generation=-1,
                lineage_basis="initial", dataset_id="TDS-000001", dataset_version="v1",
                provenance=_provenance(),
            )

    def test_self_referential_parent_rejected(self) -> None:
        with pytest.raises(ValueError):
            ModelLineageRecord(
                candidate_id="CAND-000004", parent_candidate_id="CAND-000004", generation=1,
                lineage_basis="hyperparameter_variation", dataset_id="TDS-000001", dataset_version="v1",
                provenance=_provenance(),
            )


class TestInMemoryModelLineageRepository:
    def test_record_is_idempotent_on_candidate_id(self) -> None:
        result = build_dataset(15)
        candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        lineage = derive_lineage(candidate)
        repo = InMemoryModelLineageRepository()
        first = repo.record(lineage)
        second = repo.record(derive_lineage(candidate, lineage_basis="a_different_basis_string"))
        assert first is second
        assert repo.get(candidate.candidate_id).lineage_basis == "initial"

    def test_get_children(self) -> None:
        import dataclasses

        result = build_dataset(15)
        root_candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        root_lineage = derive_lineage(root_candidate)
        repo = InMemoryModelLineageRepository()
        repo.record(root_lineage)

        # a distinct trainer instance allocates its own in-process
        # "CAND-000001" -- in real usage a storage-layer sequence gives
        # each persisted candidate a unique id (the same discipline
        # ADR-0015 section 6 already established); simulate that here.
        child_candidate = TrailingWindowMeanTrainer(window=3).train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        child_candidate = dataclasses.replace(child_candidate, candidate_id="CAND-000002")
        child_lineage = derive_lineage(child_candidate, parent=root_lineage, lineage_basis="hyperparameter_variation")
        repo.record(child_lineage)

        children = repo.get_children(root_candidate.candidate_id)
        assert len(children) == 1
        assert children[0].candidate_id == child_candidate.candidate_id


def _provenance():
    from trade_journal.enums import TradeProvenance

    return TradeProvenance.HISTORICAL_SIMULATION
