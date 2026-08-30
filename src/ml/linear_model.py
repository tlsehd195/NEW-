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
        pivot_row = max(range(col, n), key=lambda r: abs(augmented[r][col]))
        if abs(augmented[pivot_row][col]) < 1e-12:
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
