"""The first model family for the ML Research Track: ordinary least
squares with an intercept, fit via the closed-form normal equations,
solved by pure-Python Gauss-Jordan elimination with partial pivoting.

**Why this model, and why no numpy/scikit-learn (ADR-0043)**: the
feature set has 6 factor scores on ~a few hundred samples at most (this
project's real universe is 39-40 symbols, annual-cadence fundamentals)
-- exactly the regime where the simplest possible model is the correct
starting point, not a compromise. `ML-RESEARCH-PROTOCOL.md` section 13
requires any ML dependency to be justified by "a specific, justified
model family being actually implemented" (ADR-0039's reasoning,
reapplied) -- plain OLS on 6 features needs no linear-algebra library,
so none is added. A regularized/nonlinear model family would be its
own future ADR, justified only if this one's VALIDATION result
warrants the added complexity and dependency.

A small ridge term is added to the normal-equations diagonal purely
for numerical stability against near-collinear factor scores (several
of these factors are correlated by construction, e.g. `roa`/`roe` both
scale with profitability) -- this is NOT a tuned hyperparameter subject
to model-selection multiple-testing; it is fixed before any data is
seen, exists only to keep the linear solve numerically well-posed, and
is recorded as part of this model's fixed `ModelSpec.hyperparameters`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

_RIDGE = 1e-6


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    model_family: str
    version: str
    hyperparameters: dict
    feature_set_id: str
    target_id: str
    training_period: str
    validation_period: str
    experiment_id: str


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gauss-Jordan elimination with partial pivoting -- no numpy, see
    module docstring. Raises `ValueError` on a singular matrix rather
    than returning a fabricated/garbage solution."""
    n = len(vector)
    augmented = [list(matrix[i]) + [vector[i]] for i in range(n)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(augmented[r][col]) if math.isfinite(augmented[r][col]) else -1.0)
        pivot_value = augmented[pivot_row][col]
        # `abs(nan) < 1e-12` is False (every comparison against NaN is
        # False in Python) -- a NaN-poisoned input previously sailed
        # straight through this guard and produced a "successful" fit
        # with all-NaN coefficients instead of raising, contradicting
        # this function's own "never a fabricated fit" docstring claim.
        if not math.isfinite(pivot_value) or abs(pivot_value) < 1e-12:
            raise ValueError("singular matrix -- cannot fit linear model on this data")
        augmented[col], augmented[pivot_row] = augmented[pivot_row], augmented[col]
        pivot_value = augmented[col][col]
        augmented[col] = [v / pivot_value for v in augmented[col]]
        for row in range(n):
            if row == col:
                continue
            factor = augmented[row][col]
            if factor == 0.0:
                continue
            augmented[row] = [augmented[row][k] - factor * augmented[col][k] for k in range(n + 1)]
    return [augmented[i][n] for i in range(n)]


@dataclass
class LinearRegressionModel:
    feature_ids: Sequence[str]
    ridge: float = _RIDGE
    _coefficients: Optional[dict] = field(default=None, init=False, repr=False)
    _intercept: Optional[float] = field(default=None, init=False, repr=False)

    def fit(self, samples: Sequence) -> None:
        """`samples` are `ml.dataset.MLSample`s (or anything with
        `.features: dict` and `.target: float`). Raises `ValueError` if
        `samples` is empty -- never silently fits on nothing."""
        if not samples:
            raise ValueError("cannot fit LinearRegressionModel on an empty sample set")
        feature_ids = list(self.feature_ids)
        # Design matrix rows: [1.0, feature_1, feature_2, ...] -- the
        # leading 1.0 is the intercept column.
        rows = [[1.0] + [s.features[f] for f in feature_ids] for s in samples]
        targets = [s.target for s in samples]
        m = len(feature_ids) + 1

        xtx = [[sum(rows[i][a] * rows[i][b] for i in range(len(rows))) for b in range(m)] for a in range(m)]
        for i in range(m):
            xtx[i][i] += self.ridge
        xty = [sum(rows[i][a] * targets[i] for i in range(len(rows))) for a in range(m)]

        solution = _solve_linear_system(xtx, xty)
        self._intercept = solution[0]
        self._coefficients = dict(zip(feature_ids, solution[1:]))

    def predict(self, features: dict) -> float:
        if self._coefficients is None or self._intercept is None:
            raise RuntimeError("fit() must be called before predict()")
        missing = set(self.feature_ids) - set(features)
        if missing:
            raise ValueError(f"predict() missing feature(s): {sorted(missing)}")
        return self._intercept + sum(self._coefficients[f] * features[f] for f in self.feature_ids)

    @property
    def coefficients(self) -> Optional[dict]:
        return dict(self._coefficients) if self._coefficients is not None else None

    @property
    def intercept(self) -> Optional[float]:
        return self._intercept


# ADR-0043 Decision 5: a second model family -- Ridge regression with
# the regularization strength chosen by cross-validation, rather than
# fixed for numerical stability alone (`LinearRegressionModel`'s own
# default `ridge=1e-6` above). Motivated directly by a real observed
# problem: the first OLS fit's `leverage` coefficient came back
# negative despite a positive raw univariate Signal IC, plausibly a
# multicollinearity artifact among the correlated profitability
# features (`roe`/`roa`/`net_margin`/`leverage`) -- genuine
# regularization is the standard fix for exactly this instability.
# Decision 5's own real result confirmed this helps: `ml_ridge` showed
# measurably better fold-consistency than unregularized `ml_ols`
# (58% vs 53%), on data Decision 5's own writeup called "little" --
# ADR-0087 (the account owner's "strengthen regularization" direction,
# paired with `MLStrategyParameters.train_window_months` extended to 84
# months for the complementary "more data" direction) widens this grid
# upward so the CV search can select a materially stronger penalty than
# 100.0 if the now-longer training history warrants one. Extending
# upward only (never removing the original weaker candidates) keeps
# every prior real result's chosen ridge value still reachable by this
# same grid -- fixed here before any new result exists, per RULE 0.8.
CANDIDATE_RIDGES: tuple[float, ...] = (0.001, 0.01, 0.1, 1.0, 10.0, 100.0, 500.0, 1000.0)


def select_ridge_via_expanding_window_cv(
    samples: Sequence, feature_ids: Sequence[str],
    candidate_ridges: Sequence[float] = CANDIDATE_RIDGES, folds: int = 3,
) -> float:
    """Picks the ridge strength that minimizes out-of-fold squared
    error on TRAIN alone, via an EXPANDING-WINDOW chronological CV --
    each CV fold trains on every sample strictly before a cutoff date
    and tests on the samples in the following block, mirroring this
    project's own walk-forward discipline (`strategy_research.
    walk_forward_evaluation`). Deliberately never a random k-fold
    split: samples from temporally-adjacent dates are correlated, so a
    random split would let a held-out sample's near-neighbors sit in
    its own training fold, inflating the out-of-fold error estimate's
    apparent reliability without genuinely testing generalization to a
    LATER, not-yet-seen period -- the same reasoning this project
    already applies to `build_chronological_split` never shuffling.

    `candidate_ridges` is a small, pre-registered, log-spaced grid
    (`CANDIDATE_RIDGES`) -- fixed before this function is ever called
    against a real result, not searched after seeing one. This
    function is called only on samples already confined to TRAIN (see
    `MLStrategy._fit`); it never reads VALIDATION or TEST data, so it
    adds no new leakage surface.

    Falls back to the smallest (weakest) candidate ridge when there is
    too little TRAIN history to form `folds` meaningful chronological
    splits, or when every candidate fails to fit on every fold (e.g. a
    persistently singular design matrix) -- never raises, never
    fabricates a result."""
    distinct_dates = sorted({s.as_of_time for s in samples})
    if len(distinct_dates) < folds + 1:
        return candidate_ridges[0]

    cutoffs = [distinct_dates[int(len(distinct_dates) * (i + 1) / (folds + 1))] for i in range(folds)]
    best_ridge = candidate_ridges[0]
    best_error: Optional[float] = None
    for ridge in candidate_ridges:
        errors: list[float] = []
        for i, cutoff in enumerate(cutoffs):
            block_end = cutoffs[i + 1] if i + 1 < len(cutoffs) else None
            cv_train = [s for s in samples if s.as_of_time < cutoff]
            cv_test = [
                s for s in samples
                if cutoff <= s.as_of_time and (block_end is None or s.as_of_time < block_end)
            ]
            if len(cv_train) < len(feature_ids) + 2 or not cv_test:
                continue
            model = LinearRegressionModel(feature_ids=list(feature_ids), ridge=ridge)
            try:
                model.fit(cv_train)
            except ValueError:
                continue
            for sample in cv_test:
                prediction = model.predict(sample.features)
                errors.append((prediction - sample.target) ** 2)
        if not errors:
            continue
        mean_error = sum(errors) / len(errors)
        if best_error is None or mean_error < best_error:
            best_error = mean_error
            best_ridge = ridge
    return best_ridge
