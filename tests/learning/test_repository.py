"""Category: Learning Repository Test -- `InMemoryCandidateModelRepository`
/`InMemoryEvaluationRepository` reference implementations (Phase 9,
`learning.repository`).

External review finding (Session 36 continued): every `CandidateTrainer`
carries its own process-local id counter starting at "CAND-000001" (see
`learning.trainer`/`evolution.trainer`), so two different trainers used
together -- `evolution.pipeline.generate_candidate_batch`'s documented
purpose -- can hand `record()` two distinct candidates that both claim
the same `candidate_id`. `storage.learning_repository
.DuckDBCandidateModelRepository` already resolves this by reassigning
its own id from a DB sequence at persistence time; these in-memory
repositories now do the same, so they don't silently overwrite one
candidate with another under a colliding key."""

from __future__ import annotations

from datetime import datetime, timezone

from learning.enums import CandidateModelStatus
from learning.models import CandidateModelArtifact, EvaluationMetrics, EvaluationResult
from learning.repository import InMemoryCandidateModelRepository, InMemoryEvaluationRepository

from trade_journal.enums import TradeProvenance


def utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def _candidate(*, candidate_id="CAND-000001", trainer_version="trainer_a", seed=None) -> CandidateModelArtifact:
    return CandidateModelArtifact(
        candidate_id=candidate_id,
        status=CandidateModelStatus.CANDIDATE,
        trainer_version=trainer_version,
        dataset_id="TDS-000001",
        dataset_version="dsv-1",
        feature_version="fv-1",
        label_version="lv-1",
        parameters={"predicted_value": 1.0},
        seed=seed,
        trained_at=utc(2024, 3, 1),
        provenance=TradeProvenance.HISTORICAL_SIMULATION,
    )


def _metrics() -> EvaluationMetrics:
    return EvaluationMetrics(sample_count=1, mean_absolute_error=0.1, mean_squared_error=0.01, mean_label=1.0)


def _evaluation(*, evaluation_id="EVAL-000001", candidate_id="CAND-000001", evaluator_version="evaluator_v1") -> EvaluationResult:
    return EvaluationResult(
        evaluation_id=evaluation_id,
        candidate_id=candidate_id,
        dataset_id="TDS-000001",
        dataset_version="dsv-1",
        train_metrics=_metrics(),
        validation_metrics=_metrics(),
        test_metrics=_metrics(),
        baseline_metrics=_metrics(),
        evaluator_version=evaluator_version,
        evaluated_at=utc(2024, 3, 1),
        provenance=TradeProvenance.HISTORICAL_SIMULATION,
    )


class TestInMemoryCandidateModelRepositoryIdCollision:
    def test_two_distinct_candidates_sharing_a_trainer_assigned_id_are_both_kept(self) -> None:
        repo = InMemoryCandidateModelRepository()
        # two different trainers, each with its own counter starting at
        # 1 -- both hand the repository "CAND-000001"
        a = repo.record(_candidate(candidate_id="CAND-000001", trainer_version="trainer_a"))
        b = repo.record(_candidate(candidate_id="CAND-000001", trainer_version="trainer_b"))

        assert a.candidate_id != b.candidate_id
        assert {c.trainer_version for c in repo.list_all()} == {"trainer_a", "trainer_b"}
        assert repo.get(a.candidate_id).trainer_version == "trainer_a"
        assert repo.get(b.candidate_id).trainer_version == "trainer_b"

    def test_recording_the_same_natural_key_twice_is_still_idempotent(self) -> None:
        repo = InMemoryCandidateModelRepository()
        first = repo.record(_candidate(candidate_id="CAND-000001", trainer_version="trainer_a"))
        second = repo.record(_candidate(candidate_id="CAND-000001", trainer_version="trainer_a"))
        assert first.candidate_id == second.candidate_id
        assert len(repo.list_all()) == 1


class TestInMemoryEvaluationRepositoryIdCollision:
    def test_two_distinct_evaluations_sharing_an_evaluator_assigned_id_are_both_kept(self) -> None:
        repo = InMemoryEvaluationRepository()
        a = repo.record(_evaluation(evaluation_id="EVAL-000001", candidate_id="CAND-000001"))
        b = repo.record(_evaluation(evaluation_id="EVAL-000001", candidate_id="CAND-000002"))

        assert a.evaluation_id != b.evaluation_id
        assert {e.candidate_id for e in repo.list_all()} == {"CAND-000001", "CAND-000002"}

    def test_recording_the_same_natural_key_twice_is_still_idempotent(self) -> None:
        repo = InMemoryEvaluationRepository()
        first = repo.record(_evaluation(evaluation_id="EVAL-000001", candidate_id="CAND-000001"))
        second = repo.record(_evaluation(evaluation_id="EVAL-000001", candidate_id="CAND-000001"))
        assert first.evaluation_id == second.evaluation_id
        assert len(repo.list_all()) == 1
