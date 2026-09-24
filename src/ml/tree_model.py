"""The second model FAMILY for the ML Research Track (the first
nonlinear one): a small bagged ensemble of shallow CART regression
trees ("forest-lite"), pure Python, no new dependency.

**Why this model, and why now (ADR-0192)**: `linear_model.py`'s own
module docstring reserved "a regularized/nonlinear model family" as
"its own future ADR, justified only if [OLS's] VALIDATION result
warrants the added complexity" -- `ml_ols`/`ml_ridge` have since both
been run for real (`ADR-0043` Decisions 3-5, `ADR-0087`) and neither
clears the walk-forward `CANDIDATE` fold-consistency bar (53-58%
across several real runs). Every candidate this project has evaluated
so far, including two linear model families, assumes a LINEAR
combination of the 6 factor scores; a tree-based model tests a
genuinely different hypothesis (non-linear interactions and threshold
effects among the same 6 features) rather than re-running the same
linear hypothesis with different regularization.

**Why no `numpy`/`scikit-learn` here either**: the same reasoning
`linear_model.py` already gives applies with more force, not less --
this project's real per-fold TRAIN sizes are tiny (11-80 observations
across every real run recorded in `STRATEGY-VALIDATION-REPORT.md`). A
hand-rolled, heavily-regularized shallow tree ensemble is a better fit
for that regime than reaching for a general-purpose gradient-boosting
library whose default hyperparameter surface is tuned for
orders-of-magnitude more data and would need its own extensive
re-tuning (itself a multiple-comparisons risk) to avoid trivially
memorizing 11-80 rows. Per `ML-RESEARCH-PROTOCOL.md` section 13, a
dependency is added "when a specific, justified model family is
actually being implemented" -- this model family does not need one.

**Why the hyperparameters below are FIXED, not CV-searched**: mirrors
`linear_model.py`'s own `_RIDGE = 1e-6` precedent ("NOT a tuned
hyperparameter subject to model-selection multiple-testing"), extended
here to the whole tree/forest shape. `select_ridge_via_expanding_window_
cv` searches a grid because ridge strength has a wide, data-dependent
optimum; tree depth/leaf-size/estimator-count at N=11-80 do not --
anything past `max_depth=2` or a leaf smaller than roughly 10% of TRAIN
is expected to overfit regardless of what a CV search on the SAME tiny
TRAIN set would report (the CV estimate itself has high variance at
this N). Adding a hyperparameter search here would be a second,
undisclosed layer of multiple-comparisons risk stacked on top of
`compute_pbo`/`compute_dsr_for_all_candidates`'s own, which already
treats every strategy in the pool as a candidate the walk-forward/PBO/
DSR pipeline must independently clear. Fixed before any real result
from this module exists, per RULE 0.8.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional, Sequence

# Fixed before any data from this module is seen -- see module
# docstring "Why the hyperparameters below are FIXED, not CV-searched".
MAX_DEPTH = 2
MIN_SAMPLES_LEAF_FRACTION = 0.1
MIN_SAMPLES_LEAF_FLOOR = 3
N_ESTIMATORS = 25
FEATURE_SUBSAMPLE_SIZE = 3
DEFAULT_RANDOM_SEED = 20260924  # date this model family was added, arbitrary but fixed


@dataclass(frozen=True)
class _TreeNode:
    is_leaf: bool
    value: Optional[float] = None
    feature_id: Optional[str] = None
    threshold: Optional[float] = None
    left: Optional["_TreeNode"] = None
    right: Optional["_TreeNode"] = None


def _sse(targets: Sequence[float]) -> float:
    """Sum of squared error from the mean -- the CART variance-reduction
    split criterion. `0.0` for an empty or single-element sequence (no
    variance to reduce)."""
    if len(targets) < 2:
        return 0.0
    mean = sum(targets) / len(targets)
    return sum((t - mean) ** 2 for t in targets)


def _best_split(
    samples: Sequence, feature_ids: Sequence[str], min_samples_leaf: int,
) -> Optional[tuple[str, float]]:
    """Scans every candidate (feature, threshold) split -- threshold
    candidates are midpoints between consecutive distinct sorted values
    of that feature among `samples` -- and returns the one minimizing
    total child SSE, subject to both children having >= `min_samples_leaf`
    samples. Returns `None` if no split satisfies that floor (the node
    becomes a leaf)."""
    parent_sse = _sse([s.target for s in samples])
    best: Optional[tuple[str, float]] = None
    best_gain = 0.0
    for feature_id in feature_ids:
        values = sorted({s.features[feature_id] for s in samples})
        for i in range(len(values) - 1):
            threshold = (values[i] + values[i + 1]) / 2.0
            left = [s for s in samples if s.features[feature_id] <= threshold]
            right = [s for s in samples if s.features[feature_id] > threshold]
            if len(left) < min_samples_leaf or len(right) < min_samples_leaf:
                continue
            child_sse = _sse([s.target for s in left]) + _sse([s.target for s in right])
            gain = parent_sse - child_sse
            if gain > best_gain:
                best_gain = gain
                best = (feature_id, threshold)
    return best


def _build_tree(
    samples: Sequence, feature_ids: Sequence[str], depth: int,
    max_depth: int, min_samples_leaf: int,
) -> _TreeNode:
    leaf_value = sum(s.target for s in samples) / len(samples)
    if depth >= max_depth or len(samples) < 2 * min_samples_leaf:
        return _TreeNode(is_leaf=True, value=leaf_value)
    split = _best_split(samples, feature_ids, min_samples_leaf)
    if split is None:
        return _TreeNode(is_leaf=True, value=leaf_value)
    feature_id, threshold = split
    left_samples = [s for s in samples if s.features[feature_id] <= threshold]
    right_samples = [s for s in samples if s.features[feature_id] > threshold]
    return _TreeNode(
        is_leaf=False, feature_id=feature_id, threshold=threshold,
        left=_build_tree(left_samples, feature_ids, depth + 1, max_depth, min_samples_leaf),
        right=_build_tree(right_samples, feature_ids, depth + 1, max_depth, min_samples_leaf),
    )


def _predict_tree(node: _TreeNode, features: dict) -> float:
    while not node.is_leaf:
        node = node.left if features[node.feature_id] <= node.threshold else node.right
    return node.value


@dataclass
class RegressionTreeModel:
    """A single CART regression tree. Not intended to be used alone in
    this project's real pipeline (see `BaggedTreeModel` below) -- kept
    as its own class because `BaggedTreeModel` is built from many of
    these, and unit-testing tree-building logic in isolation (one tree,
    deterministic, no bootstrap resampling) is more direct than only
    testing it through the ensemble."""

    feature_ids: Sequence[str]
    max_depth: int = MAX_DEPTH
    min_samples_leaf_fraction: float = MIN_SAMPLES_LEAF_FRACTION
    min_samples_leaf_floor: int = MIN_SAMPLES_LEAF_FLOOR
    _root: Optional[_TreeNode] = field(default=None, init=False, repr=False)

    def fit(self, samples: Sequence) -> None:
        if not samples:
            raise ValueError("cannot fit RegressionTreeModel on an empty sample set")
        targets = [s.target for s in samples]
        if not all(math.isfinite(t) for t in targets):
            raise ValueError("cannot fit RegressionTreeModel on a non-finite target value")
        for s in samples:
            if not all(math.isfinite(s.features[f]) for f in self.feature_ids):
                raise ValueError("cannot fit RegressionTreeModel on a non-finite feature value")
        min_samples_leaf = max(self.min_samples_leaf_floor, int(len(samples) * self.min_samples_leaf_fraction))
        self._root = _build_tree(list(samples), list(self.feature_ids), 0, self.max_depth, min_samples_leaf)

    def predict(self, features: dict) -> float:
        if self._root is None:
            raise RuntimeError("fit() must be called before predict()")
        missing = set(self.feature_ids) - set(features)
        if missing:
            raise ValueError(f"predict() missing feature(s): {sorted(missing)}")
        return _predict_tree(self._root, features)


@dataclass
class BaggedTreeModel:
    """The actual model family this ADR adds: `n_estimators` shallow
    `RegressionTreeModel`s, each fit on an independent bootstrap
    resample of `samples` (sampling WITH replacement, same size as the
    original TRAIN set -- standard bagging) and, per tree, a random
    subsample of `FEATURE_SUBSAMPLE_SIZE` features considered for every
    split (the standard random-forest decorrelation trick, meaningful
    even at only 6 total features since each tree otherwise tends to
    pick the same dominant feature first). Prediction is the mean of
    all `n_estimators` trees' predictions.

    **Determinism**: uses a caller-supplied, explicit `random_seed` via
    a LOCAL `random.Random(random_seed)` instance -- never the global
    `random` module state -- so `fit()` is byte-for-byte reproducible
    given the same samples and seed, per `ML-RESEARCH-PROTOCOL.md`
    section 9 ("No ML code path may read wall-clock time as an input to
    training") and this project's existing seeded-training precedent
    (`learning.trainer.MeanRewardBaselineTrainer.train(..., seed=...)`).
    """

    feature_ids: Sequence[str]
    n_estimators: int = N_ESTIMATORS
    max_depth: int = MAX_DEPTH
    min_samples_leaf_fraction: float = MIN_SAMPLES_LEAF_FRACTION
    min_samples_leaf_floor: int = MIN_SAMPLES_LEAF_FLOOR
    feature_subsample_size: int = FEATURE_SUBSAMPLE_SIZE
    random_seed: int = DEFAULT_RANDOM_SEED
    _trees: list = field(default=None, init=False, repr=False)
    _tree_feature_ids: list = field(default=None, init=False, repr=False)

    def fit(self, samples: Sequence) -> None:
        if not samples:
            raise ValueError("cannot fit BaggedTreeModel on an empty sample set")
        samples = list(samples)
        targets = [s.target for s in samples]
        if not all(math.isfinite(t) for t in targets):
            raise ValueError("cannot fit BaggedTreeModel on a non-finite target value")
        for s in samples:
            if not all(math.isfinite(s.features[f]) for f in self.feature_ids):
                raise ValueError("cannot fit BaggedTreeModel on a non-finite feature value")

        rng = random.Random(self.random_seed)
        subsample_size = min(self.feature_subsample_size, len(self.feature_ids))
        n = len(samples)
        trees = []
        tree_feature_ids = []
        for _ in range(self.n_estimators):
            bootstrap = [samples[rng.randrange(n)] for _ in range(n)]
            tree_features = rng.sample(list(self.feature_ids), subsample_size)
            tree = RegressionTreeModel(
                feature_ids=tree_features, max_depth=self.max_depth,
                min_samples_leaf_fraction=self.min_samples_leaf_fraction,
                min_samples_leaf_floor=self.min_samples_leaf_floor,
            )
            try:
                tree.fit(bootstrap)
            except ValueError:
                # A degenerate bootstrap draw (e.g. every resampled row
                # shares the same feature value on every subsampled
                # feature) -- skip this tree rather than let one bad
                # draw raise for the whole ensemble; `_trees` requires
                # at least one successfully fit tree below.
                continue
            trees.append(tree)
            tree_feature_ids.append(tree_features)
        if not trees:
            raise ValueError("cannot fit BaggedTreeModel -- every bootstrap draw was degenerate")
        self._trees = trees
        self._tree_feature_ids = tree_feature_ids

    def predict(self, features: dict) -> float:
        if not self._trees:
            raise RuntimeError("fit() must be called before predict()")
        missing = set(self.feature_ids) - set(features)
        if missing:
            raise ValueError(f"predict() missing feature(s): {sorted(missing)}")
        predictions = [tree.predict(features) for tree in self._trees]
        return sum(predictions) / len(predictions)

    @property
    def n_trees_fit(self) -> int:
        """How many of `n_estimators` bootstrap draws actually produced
        a usable tree -- surfaced (not hidden) so a degenerate-heavy fit
        is visible rather than silently averaging over fewer trees than
        requested."""
        return len(self._trees) if self._trees is not None else 0
