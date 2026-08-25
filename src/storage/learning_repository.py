"""DuckDB persistent implementations of Phase 9's four Learning Engine
repository Protocols.

See docs/specifications/PHASE-9-learning-engine.md section 15 and
ADR-0015. Four new tables in Phase 4's existing catalog file -- the
same point-lookup/filter/join-heavy criterion ADR-0010 section 1 /
ADR-0011 section 4 / ADR-0012 section 8 / ADR-0013 section 8 / ADR-0014
already applied to every other Phase 5-8 dataset.
"""

from __future__ import annotations

import dataclasses
from typing import Optional

from storage.engine import StorageEngine
from storage.serialization import (
    candidate_model_to_payload,
    evaluation_result_to_payload,
    json_dumps,
    json_loads,
    learning_experiment_to_payload,
    payload_to_candidate_model,
    payload_to_evaluation_result,
    payload_to_learning_experiment,
    payload_to_training_dataset,
    to_utc_naive,
    training_dataset_to_payload,
)

from learning.models import CandidateModelArtifact, EvaluationResult, LearningExperimentRecord, TrainingDataset

from trade_journal.enums import TradeProvenance


class DuckDBTrainingDatasetRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, dataset: TrainingDataset) -> TrainingDataset:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM training_datasets WHERE dataset_version = ?", [dataset.dataset_version]
        ).fetchone()
        if existing is not None:
            return payload_to_training_dataset(json_loads(existing[0]))

        storage_id = conn.execute("SELECT nextval('training_dataset_id_seq')").fetchone()[0]
        dataset = dataclasses.replace(dataset, dataset_id=f"TDS-{storage_id:06d}")
        payload = training_dataset_to_payload(dataset)
        conn.execute(
            "INSERT INTO training_datasets (dataset_id, dataset_version, created_at, provenance, "
            "feature_version, label_version, configuration_version, sample_count, excluded_count, "
            "quality_status, as_of_cutoff, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                dataset.dataset_id, dataset.dataset_version, to_utc_naive(dataset.created_at),
                dataset.provenance.value, dataset.feature_version, dataset.label_version,
                dataset.configuration_version, dataset.sample_count, dataset.excluded_count,
                dataset.quality_status, to_utc_naive(dataset.as_of_cutoff), json_dumps(payload),
            ],
        )
        return dataset

    def get(self, dataset_id: str) -> Optional[TrainingDataset]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM training_datasets WHERE dataset_id = ?", [dataset_id]
        ).fetchone()
        return payload_to_training_dataset(json_loads(row[0])) if row is not None else None

    def get_by_version(self, dataset_version: str) -> Optional[TrainingDataset]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM training_datasets WHERE dataset_version = ?", [dataset_version]
        ).fetchone()
        return payload_to_training_dataset(json_loads(row[0])) if row is not None else None

    def list_all(self, *, provenance: Optional[TradeProvenance] = None) -> list[TrainingDataset]:
        sql = "SELECT payload_json FROM training_datasets WHERE 1=1"
        params: list = []
        if provenance is not None:
            sql += " AND provenance = ?"
            params.append(provenance.value)
        sql += " ORDER BY created_at"
        cur = self._engine.connection.execute(sql, params)
        return [payload_to_training_dataset(json_loads(r[0])) for r in cur.fetchall()]


class DuckDBCandidateModelRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    @staticmethod
    def _natural_key(c: CandidateModelArtifact) -> str:
        return "|".join([c.dataset_version, c.trainer_version, str(c.seed), c.provenance.value])

    def record(self, candidate: CandidateModelArtifact) -> CandidateModelArtifact:
        conn = self._engine.connection
        key = self._natural_key(candidate)
        existing = conn.execute(
            "SELECT payload_json FROM candidate_models WHERE natural_key = ?", [key]
        ).fetchone()
        if existing is not None:
            return payload_to_candidate_model(json_loads(existing[0]))

        storage_id = conn.execute("SELECT nextval('candidate_model_id_seq')").fetchone()[0]
        candidate = dataclasses.replace(candidate, candidate_id=f"CAND-{storage_id:06d}")
        payload = candidate_model_to_payload(candidate)
        conn.execute(
            "INSERT INTO candidate_models (candidate_id, natural_key, status, trainer_version, "
            "dataset_id, dataset_version, label_version, seed, trained_at, provenance, "
            "experiment_id, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                candidate.candidate_id, key, candidate.status.value, candidate.trainer_version,
                candidate.dataset_id, candidate.dataset_version, candidate.label_version, candidate.seed,
                to_utc_naive(candidate.trained_at), candidate.provenance.value, candidate.experiment_id,
                json_dumps(payload),
            ],
        )
        return candidate

    def get(self, candidate_id: str) -> Optional[CandidateModelArtifact]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM candidate_models WHERE candidate_id = ?", [candidate_id]
        ).fetchone()
        return payload_to_candidate_model(json_loads(row[0])) if row is not None else None

    def list_all(self, *, dataset_id: Optional[str] = None) -> list[CandidateModelArtifact]:
        sql = "SELECT payload_json FROM candidate_models WHERE 1=1"
        params: list = []
        if dataset_id is not None:
            sql += " AND dataset_id = ?"
            params.append(dataset_id)
        sql += " ORDER BY trained_at"
        cur = self._engine.connection.execute(sql, params)
        return [payload_to_candidate_model(json_loads(r[0])) for r in cur.fetchall()]


class DuckDBEvaluationRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    @staticmethod
    def _natural_key(e: EvaluationResult) -> str:
        return "|".join([e.candidate_id, e.dataset_version, e.evaluator_version])

    def record(self, evaluation: EvaluationResult) -> EvaluationResult:
        conn = self._engine.connection
        key = self._natural_key(evaluation)
        existing = conn.execute(
            "SELECT payload_json FROM evaluation_results WHERE natural_key = ?", [key]
        ).fetchone()
        if existing is not None:
            return payload_to_evaluation_result(json_loads(existing[0]))

        storage_id = conn.execute("SELECT nextval('evaluation_id_seq')").fetchone()[0]
        evaluation = dataclasses.replace(evaluation, evaluation_id=f"EVAL-{storage_id:06d}")
        payload = evaluation_result_to_payload(evaluation)
        conn.execute(
            "INSERT INTO evaluation_results (evaluation_id, natural_key, candidate_id, dataset_id, "
            "dataset_version, evaluator_version, evaluated_at, provenance, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                evaluation.evaluation_id, key, evaluation.candidate_id, evaluation.dataset_id,
                evaluation.dataset_version, evaluation.evaluator_version, to_utc_naive(evaluation.evaluated_at),
                evaluation.provenance.value, json_dumps(payload),
            ],
        )
        return evaluation

    def get(self, evaluation_id: str) -> Optional[EvaluationResult]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM evaluation_results WHERE evaluation_id = ?", [evaluation_id]
        ).fetchone()
        return payload_to_evaluation_result(json_loads(row[0])) if row is not None else None

    def list_all(self, *, candidate_id: Optional[str] = None) -> list[EvaluationResult]:
        sql = "SELECT payload_json FROM evaluation_results WHERE 1=1"
        params: list = []
        if candidate_id is not None:
            sql += " AND candidate_id = ?"
            params.append(candidate_id)
        sql += " ORDER BY evaluated_at"
        cur = self._engine.connection.execute(sql, params)
        return [payload_to_evaluation_result(json_loads(r[0])) for r in cur.fetchall()]


class DuckDBLearningExperimentRepository:
    """Dedupes on `(dataset_version, candidate_id, evaluation_id)`, not
    the caller-supplied `experiment_id` -- the same reasoning as the
    other three Learning Engine repositories (see module docstring /
    schema.py comment): a specific training run is uniquely identified
    by which dataset/candidate/evaluation it ties together, not by an
    in-process counter's next value."""

    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    @staticmethod
    def _natural_key(e: LearningExperimentRecord) -> str:
        return "|".join([e.dataset_version, e.candidate_id, e.evaluation_id])

    def record(self, experiment: LearningExperimentRecord) -> LearningExperimentRecord:
        conn = self._engine.connection
        key = self._natural_key(experiment)
        existing = conn.execute(
            "SELECT payload_json FROM learning_experiments WHERE natural_key = ?", [key]
        ).fetchone()
        if existing is not None:
            return payload_to_learning_experiment(json_loads(existing[0]))

        storage_id = conn.execute("SELECT nextval('learning_experiment_id_seq')").fetchone()[0]
        experiment = dataclasses.replace(experiment, experiment_id=f"LRN-{storage_id:06d}")
        payload = learning_experiment_to_payload(experiment)
        conn.execute(
            "INSERT INTO learning_experiments (experiment_id, natural_key, dataset_id, dataset_version, "
            "trainer_version, evaluator_version, candidate_id, evaluation_id, configuration_version, "
            "seed, provenance, status, created_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                experiment.experiment_id, key, experiment.dataset_id, experiment.dataset_version,
                experiment.trainer_version, experiment.evaluator_version, experiment.candidate_id,
                experiment.evaluation_id, experiment.configuration_version, experiment.seed,
                experiment.provenance.value, experiment.status, to_utc_naive(experiment.created_at),
                json_dumps(payload),
            ],
        )
        return experiment

    def get(self, experiment_id: str) -> Optional[LearningExperimentRecord]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM learning_experiments WHERE experiment_id = ?", [experiment_id]
        ).fetchone()
        return payload_to_learning_experiment(json_loads(row[0])) if row is not None else None

    def list_all(self) -> list[LearningExperimentRecord]:
        cur = self._engine.connection.execute(
            "SELECT payload_json FROM learning_experiments ORDER BY created_at"
        )
        return [payload_to_learning_experiment(json_loads(r[0])) for r in cur.fetchall()]
