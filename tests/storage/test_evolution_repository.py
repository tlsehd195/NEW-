"""Category: Persistence Test -- save, reload, idempotency, restart for
Phase 11's two Model Evolution stores (docs/specifications/
PHASE-11-model-evolution.md section 9)."""

from __future__ import annotations

from evolution_helpers import build_dataset, utc
from storage_helpers import new_engine

from evolution.config import PromotionConfig
from evolution.criteria import evaluate_transition
from evolution.lineage import derive_lineage

from learning.enums import CandidateModelStatus
from learning.evaluation import Evaluator
from learning.trainer import MeanRewardBaselineTrainer

from storage.evolution_repository import DuckDBModelLineageRepository, DuckDBModelStatusTransitionRepository


def _candidate_and_evaluation():
    result = build_dataset(20)
    candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
    evaluation = Evaluator().evaluate(candidate, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1))
    return candidate, evaluation


class TestModelStatusTransitionPersistence:
    def test_record_and_get_latest(self, tmp_path) -> None:
        candidate, evaluation = _candidate_and_evaluation()
        transition = evaluate_transition(
            candidate, evaluation, CandidateModelStatus.CANDIDATE, PromotionConfig(),
            transition_id="TRANS-000001", evaluated_at=utc(2024, 3, 1),
        )
        engine = new_engine(tmp_path)
        repo = DuckDBModelStatusTransitionRepository(engine)
        repo.record(transition)
        fetched = repo.get_latest(candidate.candidate_id)
        assert fetched == transition
        engine.close()

    def test_recording_the_same_transition_twice_is_idempotent(self, tmp_path) -> None:
        candidate, evaluation = _candidate_and_evaluation()
        transition = evaluate_transition(
            candidate, evaluation, CandidateModelStatus.CANDIDATE, PromotionConfig(),
            transition_id="TRANS-000001", evaluated_at=utc(2024, 3, 1),
        )
        engine = new_engine(tmp_path)
        repo = DuckDBModelStatusTransitionRepository(engine)
        repo.record(transition)
        repo.record(transition)
        assert len(repo.get_history(candidate.candidate_id)) == 1
        engine.close()

    def test_a_later_passing_retry_is_not_discarded_by_an_earlier_failed_attempt(self, tmp_path) -> None:
        """Session 37 (ADR-0115, external review N-9): before this fix,
        the DuckDB dedup query omitted `passed` -- a FAILED transition
        recorded first silently absorbed a later PASSING retry sharing
        the same (candidate_id, from_status, to_status,
        criteria_version), since `record()` treated it as an already-
        seen duplicate and returned the stale, still-failed row."""
        import dataclasses

        candidate, evaluation = _candidate_and_evaluation()
        engine = new_engine(tmp_path)
        repo = DuckDBModelStatusTransitionRepository(engine)

        failing = evaluate_transition(
            candidate, evaluation, CandidateModelStatus.CANDIDATE, PromotionConfig(),
            transition_id="TRANS-000001", evaluated_at=utc(2024, 3, 1),
        )
        failing = dataclasses.replace(failing, passed=False, reason="forced_failure_for_test")
        repo.record(failing)
        assert repo.get_current_status(candidate.candidate_id) == CandidateModelStatus.CANDIDATE

        passing = evaluate_transition(
            candidate, evaluation, CandidateModelStatus.CANDIDATE, PromotionConfig(),
            transition_id="TRANS-000002", evaluated_at=utc(2024, 3, 2),
        )
        assert passing.passed is True
        repo.record(passing)

        assert repo.get_current_status(candidate.candidate_id) == CandidateModelStatus.BACKTESTED
        assert len(repo.get_history(candidate.candidate_id)) == 2
        engine.close()

    def test_get_current_status_reflects_only_passed_transitions(self, tmp_path) -> None:
        candidate, evaluation = _candidate_and_evaluation()
        engine = new_engine(tmp_path)
        repo = DuckDBModelStatusTransitionRepository(engine)
        assert repo.get_current_status(candidate.candidate_id) == CandidateModelStatus.CANDIDATE

        passing = evaluate_transition(
            candidate, evaluation, CandidateModelStatus.CANDIDATE, PromotionConfig(),
            transition_id="TRANS-000010", evaluated_at=utc(2024, 3, 1),
        )
        repo.record(passing)
        assert repo.get_current_status(candidate.candidate_id) == CandidateModelStatus.BACKTESTED

        failing_config = PromotionConfig(min_validation_sample_count=10_000)
        failing = evaluate_transition(
            candidate, evaluation, passing.to_status, failing_config,
            transition_id="TRANS-000011", evaluated_at=utc(2024, 3, 1),
        )
        repo.record(failing)
        # a failed attempt is stored (auditable) but never advances current status
        assert repo.get_current_status(candidate.candidate_id) == CandidateModelStatus.BACKTESTED
        assert len(repo.get_history(candidate.candidate_id)) == 2
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        candidate, evaluation = _candidate_and_evaluation()
        transition = evaluate_transition(
            candidate, evaluation, CandidateModelStatus.CANDIDATE, PromotionConfig(),
            transition_id="TRANS-000020", evaluated_at=utc(2024, 3, 1),
        )
        engine1 = new_engine(tmp_path)
        DuckDBModelStatusTransitionRepository(engine1).record(transition)
        engine1.close()

        engine2 = new_engine(tmp_path)
        reloaded = DuckDBModelStatusTransitionRepository(engine2).get_latest(candidate.candidate_id)
        assert reloaded == transition
        engine2.close()


class TestModelLineagePersistence:
    def test_record_and_get(self, tmp_path) -> None:
        candidate, _ = _candidate_and_evaluation()
        lineage = derive_lineage(candidate)
        engine = new_engine(tmp_path)
        repo = DuckDBModelLineageRepository(engine)
        repo.record(lineage)
        assert repo.get(candidate.candidate_id) == lineage
        engine.close()

    def test_record_is_idempotent_on_candidate_id(self, tmp_path) -> None:
        candidate, _ = _candidate_and_evaluation()
        lineage = derive_lineage(candidate, lineage_basis="initial")
        engine = new_engine(tmp_path)
        repo = DuckDBModelLineageRepository(engine)
        repo.record(lineage)
        repo.record(derive_lineage(candidate, lineage_basis="a_different_basis"))
        assert repo.get(candidate.candidate_id).lineage_basis == "initial"
        engine.close()

    def test_get_children(self, tmp_path) -> None:
        import dataclasses

        candidate, _ = _candidate_and_evaluation()
        root = derive_lineage(candidate)
        child_candidate = dataclasses.replace(candidate, candidate_id="CAND-000002")
        child = derive_lineage(child_candidate, parent=root, lineage_basis="hyperparameter_variation")

        engine = new_engine(tmp_path)
        repo = DuckDBModelLineageRepository(engine)
        repo.record(root)
        repo.record(child)
        children = repo.get_children(candidate.candidate_id)
        assert len(children) == 1
        assert children[0].candidate_id == "CAND-000002"
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        candidate, _ = _candidate_and_evaluation()
        lineage = derive_lineage(candidate)
        engine1 = new_engine(tmp_path)
        DuckDBModelLineageRepository(engine1).record(lineage)
        engine1.close()

        engine2 = new_engine(tmp_path)
        reloaded = DuckDBModelLineageRepository(engine2).get(candidate.candidate_id)
        assert reloaded == lineage
        engine2.close()
