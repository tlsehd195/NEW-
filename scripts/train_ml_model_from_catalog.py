#!/usr/bin/env python3
"""ML Research Track (Track B) -- first concrete model. Fits
`ml.linear_model.LinearRegressionModel` (ordinary least squares, no
numpy/scikit-learn -- ADR-0043) on `ml.features.FEATURE_SPECS`'s 6
factor-score features against TRAIN, then evaluates it out-of-sample
on VALIDATION via the same rank-IC diagnostic
`compute_signal_ic_from_catalog.py`/`compute_fundamentals_ic_from_
catalog.py` already apply to rule-based scores -- the only fair
comparison against this project's existing factor-IC results.

Governance this script follows, per `docs/research/ML-RESEARCH-
PROTOCOL.md`:
  - Section 3/section 5: `[--start, --end]` must never overlap a
    locked window; this script never reads TEST-1, and it never even
    computes a TEST split at all -- `build_chronological_split`'s
    `test_start`/`test_end` fields are ignored entirely, ML-RESEARCH-
    PROTOCOL.md's "LOCK -> TEST (once)" stage is deliberately not
    reached by this first, exploratory model.
  - Section 4: leakage prevention is enforced at the feature/target
    layer this script calls into (`ml.features`/`ml.target`), not
    reimplemented here.
  - Section 6: every run prints its full experiment-governance record
    (feature_set_id, target_id, model_family, hyperparameter_set_id,
    training_window, validation_window, random_seed, dataset content
    hash, experiment_id) -- and `experiments_run_in_this_study`, since
    "more models is not more evidence" without also reporting how many
    were tried.
  - Section 7: `selection_reason` is filled in AFTER the VALIDATION IC
    is computed, never before -- there is exactly one candidate model
    family in this first run, so no multiple-comparisons correction is
    needed yet (would be, the moment a second candidate is added).

**TEST-1 protection, not a suggestion**: identical to the other
Signal-IC/walk-forward CLI scripts -- refuses (exit 1, no partial
output) if `[--start, --end]` overlaps
`strategy_research.locked_windows.TEST_1`, no override flag. Default
`--end` is `TEST_1.start`.

Usage:
    python3 scripts/train_ml_model_from_catalog.py \\
        --price-db-path ./data/real_2010_latest \\
        --fundamentals-db-path ./data/fundamentals_data \\
        --universe RESEARCH_UNIVERSE \\
        --start 2010-01-01 \\
        [--end 2023-04-28]  # defaults to TEST_1.start; anything later is refused
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE3  # noqa: E402
from data_infra.versioning import compute_data_version  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.fundamentals_repository import DuckDBFundamentalsRepository  # noqa: E402

from ml.dataset import build_ml_dataset  # noqa: E402
from ml.evaluate import evaluate_model_ic  # noqa: E402
from ml.features import FEATURE_IDS, FEATURE_SET_ID, FUNDAMENTALS_FEATURE_FNS, build_price_feature_fns  # noqa: E402
from ml.linear_model import LinearRegressionModel  # noqa: E402
from ml.target import HORIZON_DAYS, TARGET_ID  # noqa: E402

from strategy_research._dates import add_months  # noqa: E402
from strategy_research.locked_windows import TEST_1, overlaps_any_locked_window  # noqa: E402
from strategy_research.splits import build_chronological_split  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE3}
_MODEL_FAMILY = "ordinary_least_squares"
_MODEL_VERSION = "v1"


def _rebalance_dates(start: datetime, end: datetime, step_months: int) -> list[datetime]:
    dates = []
    current = start
    while current < end:
        dates.append(current)
        current = add_months(current, step_months)
    return dates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--price-db-path", required=True, type=Path, help="DuckDB catalog from ingest_real_market_data.py")
    parser.add_argument("--fundamentals-db-path", required=True, type=Path, help="DuckDB catalog from ingest_fundamentals_data.py")
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="RESEARCH_UNIVERSE")
    parser.add_argument("--start", required=True, type=str, help="YYYY-MM-DD -- TRAIN start")
    parser.add_argument(
        "--end", type=str, default=None,
        help="YYYY-MM-DD. Defaults to TEST_1.start -- the script refuses to run past that "
        "(see module docstring, no override flag). This is the VALIDATION end -- this "
        "script never touches a TEST region at all.",
    )
    parser.add_argument("--train-fraction", type=float, default=0.75, help="Fraction of [start, end] used for TRAIN; the remainder is VALIDATION")
    parser.add_argument("--step-months", type=int, default=2, help="Rebalance interval, matches this project's other Signal IC scripts' default")
    args = parser.parse_args(argv)

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = (
        datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if args.end is not None
        else TEST_1.start
    )

    locked = overlaps_any_locked_window(start, end)
    if locked:
        names = ", ".join(w.name for w in locked)
        print(
            f"ERROR: requested range [{start.date()}, {end.date()}) overlaps LOCKED window(s): {names}. "
            "Refusing to train or evaluate an ML model against an already-observed held-out TEST "
            "window -- see this script's own module docstring. No override flag exists for this.",
            file=sys.stderr,
        )
        return 1

    # This script deliberately never computes or reads a TEST region --
    # build_chronological_split's test_start/test_end are ignored on
    # purpose (see module docstring). A validation_fraction of
    # "whatever remains after train_fraction" that is itself never
    # touched keeps this call identical in shape to every other script
    # that already reuses build_chronological_split.
    remaining_fraction = 1.0 - args.train_fraction
    split = build_chronological_split(
        start, end, train_fraction=args.train_fraction, validation_fraction=remaining_fraction / 2.0,
    )

    universe = _UNIVERSES[args.universe]
    security_ids = list(universe.symbol_ids)

    price_engine = StorageEngine(StorageConfig(root_dir=args.price_db_path))
    fundamentals_engine = StorageEngine(StorageConfig(root_dir=args.fundamentals_db_path))
    try:
        price_repository = DuckDBDataRepository(price_engine)
        fundamentals_repository = DuckDBFundamentalsRepository(fundamentals_engine)

        price_score_fns = build_price_feature_fns(security_ids)
        train_dates = _rebalance_dates(split.train_start, split.train_end, args.step_months)
        validation_dates = _rebalance_dates(split.validation_start, split.validation_end, args.step_months)

        train_samples = build_ml_dataset(
            security_ids, train_dates, price_score_fns, FUNDAMENTALS_FEATURE_FNS,
            price_repository, fundamentals_repository,
        )
        if not train_samples:
            print("ERROR: no TRAIN samples had a complete feature vector and a computable target.", file=sys.stderr)
            return 1

        model = LinearRegressionModel(feature_ids=list(FEATURE_IDS))
        model.fit(train_samples)

        validation_summary = evaluate_model_ic(
            model, security_ids, validation_dates, price_score_fns, FUNDAMENTALS_FEATURE_FNS,
            price_repository, fundamentals_repository,
        )

        dataset_version = compute_data_version(
            {
                "universe_name": universe.name, "universe_version": universe.version,
                "feature_set_id": FEATURE_SET_ID, "target_id": TARGET_ID,
                "train_sample_count": len(train_samples),
                "train_start": split.train_start.isoformat(), "train_end": split.train_end.isoformat(),
                "validation_start": split.validation_start.isoformat(), "validation_end": split.validation_end.isoformat(),
            }
        )
        experiment_id = compute_data_version(
            {
                "model_family": _MODEL_FAMILY, "model_version": _MODEL_VERSION,
                "feature_set_id": FEATURE_SET_ID, "target_id": TARGET_ID,
                "hyperparameter_set_id": f"ridge={model.ridge}",
                "training_window": [split.train_start.isoformat(), split.train_end.isoformat()],
                "validation_window": [split.validation_start.isoformat(), split.validation_end.isoformat()],
                "universe_name": universe.name, "universe_version": universe.version,
                "step_months": args.step_months, "horizon_days": HORIZON_DAYS,
            }
        )[:16]

        print(f"ML experiment: {_MODEL_FAMILY} {_MODEL_VERSION} over {universe.name} {universe.version}")
        print(f"  experiment_id={experiment_id}")
        print(f"  dataset_version={dataset_version}")
        print(f"  feature_set_id={FEATURE_SET_ID} ({', '.join(FEATURE_IDS)})")
        print(f"  target_id={TARGET_ID} (horizon={HORIZON_DAYS}d)")
        print(f"  hyperparameter_set_id=ridge={model.ridge}")
        print("  random_seed=N/A (OLS is deterministic, no randomness)")
        print(f"  training_window=[{split.train_start.date()}, {split.train_end.date()}) train_samples={len(train_samples)}")
        print(f"  validation_window=[{split.validation_start.date()}, {split.validation_end.date()})")
        print(f"  experiments_run_in_this_study=1 (first ML model; no model-selection procedure applied yet)")
        print(f"  fitted_coefficients={model.coefficients}")
        print(f"  fitted_intercept={model.intercept}")
        print(f"  VALIDATION observations={len(validation_summary.observations)}")
        if validation_summary.mean_ic is None:
            print("  VALIDATION mean_ic=N/A (no observations had >= 2 securities with both a prediction and a forward return)")
        else:
            print(f"  VALIDATION mean_ic={validation_summary.mean_ic:.4f}")
            print(f"  VALIDATION ic_information_ratio={validation_summary.ic_information_ratio}")
            print(f"  VALIDATION positive_ic_ratio={validation_summary.positive_ic_ratio:.2%}")
        print(
            "  selection_reason=only candidate model family evaluated in this study; no "
            "multiple-comparisons correction applied (ML-RESEARCH-PROTOCOL.md section 7 -- "
            "would be required the moment a second candidate model is added)"
        )
        return 0
    finally:
        price_engine.close()
        fundamentals_engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
