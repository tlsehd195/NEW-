"""Category: Unit Test -- LinearRegressionTrainer (ADR-0048/0049).

Uses a deterministic, EXACT linear relationship between features and
realized_return (no noise) so the fitted coefficients/intercept can be
asserted against known true values, not just "some plausible number" --
the same "hand-verifiable" discipline `test_trainer.py`'s
MeanRewardBaselineTrainer tests already apply to the mean predictor.
"""

from __future__ import annotations

import pytest
from learning_helpers import build_journal_with_closed_trades, utc

from learning.dataset import build_training_dataset
from learning.enums import CandidateModelStatus, SplitName
from learning.evaluation import Evaluator
from learning.linear_trainer import LinearRegressionTrainer
from learning.trainer import MeanRewardBaselineTrainer

from trade_journal.enums import TradeProvenance

_TRUE_COEF_A = 2.0
_TRUE_COEF_B = -1.0
_TRUE_INTERCEPT = 5.0


def _exact_features(i: int) -> dict:
    return {"feature_a": i * 0.1, "feature_b": float(i % 3)}


def _exact_label(i: int) -> float:
    features = _exact_features(i)
    return _TRUE_COEF_A * features["feature_a"] + _TRUE_COEF_B * features["feature_b"] + _TRUE_INTERCEPT


def _dataset_result(count: int = 30, *, features_fn=_exact_features, realized_return_fn=_exact_label):
    journal, records = build_journal_with_closed_trades(count, features_fn=features_fn, realized_return_fn=realized_return_fn)
    return build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))


class TestFitsARealNonConstantModel:
    def test_status_is_always_candidate(self) -> None:
        result = _dataset_result()
        candidate = LinearRegressionTrainer(["feature_a", "feature_b"]).train(
            result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1),
        )
        assert candidate.status == CandidateModelStatus.CANDIDATE

    def test_recovers_the_exact_known_linear_relationship(self) -> None:
        result = _dataset_result()
        candidate = LinearRegressionTrainer(["feature_a", "feature_b"]).train(
            result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1),
        )
        assert candidate.parameters["fitted"] is True
        coefficients = candidate.parameters["coefficients"]
        assert coefficients["feature_a"] == pytest.approx(_TRUE_COEF_A, abs=1e-3)
        assert coefficients["feature_b"] == pytest.approx(_TRUE_COEF_B, abs=1e-3)
        assert candidate.parameters["intercept"] == pytest.approx(_TRUE_INTERCEPT, abs=1e-3)

    def test_predict_matches_the_true_relationship_on_unseen_test_split_samples(self) -> None:
        result = _dataset_result()
        trainer = LinearRegressionTrainer(["feature_a", "feature_b"])
        candidate = trainer.train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))

        test_ids = set(result.dataset.splits[SplitName.TEST])
        test_samples = [s for s in result.labeled_samples if s.trade_id in test_ids]
        assert test_samples  # sanity: the split actually has samples

        for sample in test_samples:
            prediction = trainer.predict(candidate, sample)
            assert prediction == pytest.approx(sample.label_value, abs=1e-3)

    def test_trainer_only_reads_the_train_split(self) -> None:
        """Mirrors MeanRewardBaselineTrainer's own leakage-guard test --
        mutating VALIDATION/TEST features must not change the fit at all."""
        import dataclasses

        result = _dataset_result()
        trainer = LinearRegressionTrainer(["feature_a", "feature_b"])
        candidate_before = trainer.train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))

        non_train_ids = set(result.dataset.splits[SplitName.VALIDATION]) | set(result.dataset.splits[SplitName.TEST])
        mutated = [
            dataclasses.replace(s, features={"feature_a": 999.0, "feature_b": 999.0}, label_value=999.0)
            if s.trade_id in non_train_ids else s
            for s in result.labeled_samples
        ]
        candidate_after = trainer.train(result.dataset, mutated, trained_at=utc(2024, 3, 1))
        assert candidate_before.parameters["coefficients"] == candidate_after.parameters["coefficients"]
        assert candidate_before.parameters["intercept"] == candidate_after.parameters["intercept"]


class TestNeverFabricates:
    def test_no_features_at_all_never_fits(self) -> None:
        """Every existing Strategy today sets no OrderIntent.features --
        this is the realistic default case, not an edge case."""
        result = _dataset_result(features_fn=lambda i: None)
        candidate = LinearRegressionTrainer(["feature_a", "feature_b"]).train(
            result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1),
        )
        assert candidate.parameters["fitted"] is False
        assert candidate.parameters["coefficients"] is None
        assert candidate.parameters["intercept"] is None
        assert candidate.parameters["train_sample_count"] == 0

    def test_samples_missing_a_required_feature_are_excluded_not_fabricated(self) -> None:
        def _partial_features(i: int) -> dict:
            # Every 3rd sample is missing "feature_b" entirely.
            if i % 3 == 0:
                return {"feature_a": i * 0.1}
            return _exact_features(i)

        result = _dataset_result(features_fn=_partial_features)
        candidate = LinearRegressionTrainer(["feature_a", "feature_b"]).train(
            result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1),
        )
        train_ids = set(result.dataset.splits[SplitName.TRAIN])
        full_train_count = sum(1 for s in result.labeled_samples if s.trade_id in train_ids)
        assert candidate.parameters["train_sample_count"] < full_train_count

    def test_predict_returns_none_when_the_candidate_never_fit(self) -> None:
        result = _dataset_result(features_fn=lambda i: None)
        trainer = LinearRegressionTrainer(["feature_a", "feature_b"])
        candidate = trainer.train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        some_sample = result.labeled_samples[0]
        assert trainer.predict(candidate, some_sample) is None

    def test_predict_returns_none_for_a_sample_missing_a_required_feature(self) -> None:
        result = _dataset_result()
        trainer = LinearRegressionTrainer(["feature_a", "feature_b"])
        candidate = trainer.train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        import dataclasses

        incomplete_sample = dataclasses.replace(result.labeled_samples[0], features={"feature_a": 1.0})
        assert trainer.predict(candidate, incomplete_sample) is None

    def test_empty_train_split_does_not_crash(self) -> None:
        result = _dataset_result(count=0)
        candidate = LinearRegressionTrainer(["feature_a", "feature_b"]).train(
            result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1),
        )
        assert candidate.parameters["fitted"] is False

    def test_requires_at_least_one_feature_id(self) -> None:
        with pytest.raises(ValueError):
            LinearRegressionTrainer([])


class TestEvaluatorPerSamplePrediction:
    def test_evaluator_reports_near_zero_error_for_the_exact_relationship(self) -> None:
        result = _dataset_result()
        trainer = LinearRegressionTrainer(["feature_a", "feature_b"])
        candidate = trainer.train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))

        evaluation = Evaluator().evaluate(
            candidate, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1),
            predict_fn=trainer.predict,
        )
        assert evaluation.test_metrics.mean_absolute_error == pytest.approx(0.0, abs=1e-3)
        assert evaluation.train_metrics.mean_absolute_error == pytest.approx(0.0, abs=1e-3)

    def test_evaluator_default_path_is_unaffected_by_predict_fn_existing(self) -> None:
        """MeanRewardBaselineTrainer has no predict method -- Evaluator
        must fall back to its original constant-prediction behavior
        exactly as before this session's change."""
        result = _dataset_result()
        candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        evaluation = Evaluator().evaluate(candidate, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1))
        assert evaluation.train_metrics.sample_count == 18  # unchanged split sizing at count=30

    def test_evaluator_excludes_unscoreable_samples_from_sample_count(self) -> None:
        import dataclasses

        result = _dataset_result()
        trainer = LinearRegressionTrainer(["feature_a", "feature_b"])
        candidate = trainer.train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))

        test_ids = set(result.dataset.splits[SplitName.TEST])
        full_test_count = sum(1 for s in result.labeled_samples if s.trade_id in test_ids)
        # Strip features from exactly one TEST sample -> it can no longer be scored.
        stripped = False
        samples = []
        for s in result.labeled_samples:
            if not stripped and s.trade_id in test_ids:
                samples.append(dataclasses.replace(s, features=None))
                stripped = True
            else:
                samples.append(s)

        evaluation = Evaluator().evaluate(
            candidate, result.dataset, samples, evaluated_at=utc(2024, 3, 1), predict_fn=trainer.predict,
        )
        assert evaluation.test_metrics.sample_count == full_test_count - 1
