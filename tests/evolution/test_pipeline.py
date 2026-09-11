"""Category: Model Evolution Pipeline Test --
`evaluate_candidate_batch`'s per-candidate predict_fn wiring (Phase 11
spec section 3, ADR-0049)."""

from __future__ import annotations

from learning_helpers import build_journal_with_closed_trades, utc

from evolution.pipeline import evaluate_candidate_batch, generate_candidate_batch
from learning.dataset import build_training_dataset
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


def _dataset_result(count: int = 30):
    journal, records = build_journal_with_closed_trades(
        count, features_fn=_exact_features, realized_return_fn=_exact_label,
    )
    return build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))


class TestEvaluateCandidateBatchUsesEachCandidatesOwnPredictFn:
    """Session 37 (ADR-0115, external review, previously-remaining
    MEDIUM): before `trainers` existed on this function, EVERY candidate
    was evaluated with `predict_fn=None`, which predicts the same
    constant `candidate.parameters["predicted_value"]` for every sample
    -- correct for `MeanRewardBaselineTrainer`, but silently wrong for
    `LinearRegressionTrainer`, which implements its own real per-sample
    `predict()` (ADR-0049) that `learning.pipeline.run_learning_pipeline`
    already wires up correctly for a single candidate. A batch
    comparison including a feature-based trainer could never actually
    show its real per-sample accuracy."""

    def test_without_trainers_a_linear_model_is_misevaluated_as_a_constant(self) -> None:
        result = _dataset_result()
        trainers = [LinearRegressionTrainer(["feature_a", "feature_b"])]
        candidates = generate_candidate_batch(result.dataset, result.labeled_samples, trainers, trained_at=utc(2024, 3, 1))
        [evaluation] = evaluate_candidate_batch(
            candidates, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1),
        )
        # Unfitted: `predicted_value` isn't even in `parameters` (a
        # linear model has no single constant prediction), so the
        # None-predict_fn fallback silently predicts 0.0 for every
        # sample -- nowhere near the real, near-exact linear fit.
        assert evaluation.test_metrics.mean_absolute_error > 1.0

    def test_with_trainers_a_linear_model_is_evaluated_with_its_own_real_predictions(self) -> None:
        result = _dataset_result()
        trainers = [LinearRegressionTrainer(["feature_a", "feature_b"])]
        candidates = generate_candidate_batch(result.dataset, result.labeled_samples, trainers, trained_at=utc(2024, 3, 1))
        [evaluation] = evaluate_candidate_batch(
            candidates, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1), trainers=trainers,
        )
        # The exact, noiseless linear relationship is recoverable almost
        # perfectly -- a real test of the fitted model, not a constant.
        assert evaluation.test_metrics.mean_absolute_error < 0.05

    def test_a_constant_trainer_is_unaffected_by_passing_trainers(self) -> None:
        """MeanRewardBaselineTrainer has no `predict()` of its own --
        `getattr(trainer, "predict", None)` correctly falls back to
        `None`, so passing `trainers` changes nothing for it."""
        result = _dataset_result()
        trainers = [MeanRewardBaselineTrainer()]
        candidates = generate_candidate_batch(result.dataset, result.labeled_samples, trainers, trained_at=utc(2024, 3, 1))
        without = evaluate_candidate_batch(candidates, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1))
        with_trainers = evaluate_candidate_batch(
            candidates, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1), trainers=trainers,
        )
        assert without[0].test_metrics.mean_absolute_error == with_trainers[0].test_metrics.mean_absolute_error

    def test_mismatched_trainers_length_raises(self) -> None:
        result = _dataset_result()
        trainers = [LinearRegressionTrainer(["feature_a", "feature_b"])]
        candidates = generate_candidate_batch(result.dataset, result.labeled_samples, trainers, trained_at=utc(2024, 3, 1))
        try:
            evaluate_candidate_batch(
                candidates, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1), trainers=[],
            )
            assert False, "expected ValueError"
        except ValueError:
            pass
