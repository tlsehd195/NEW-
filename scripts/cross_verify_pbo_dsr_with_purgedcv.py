#!/usr/bin/env python3
"""Cross-verifies `strategy_research.pbo_dsr.compute_pbo`/
`compute_dsr_for_all_candidates` (this project's own PBO/Deflated Sharpe
Ratio implementation, ADR-0035) against the independent, third-party
`purgedcv` library, using the EXACT same input this project's own
production pipeline already computed and persisted.

**Why this exists**: `purgedcv` was adopted in ADR-0151 Decision 5 but
never wired in ("not yet connected to src/backtest/validation.py or
src/strategy_research/evidence.py"). This script is that connection --
`scripts/`-level only, `src/` completely unmodified, per this project's
"external stats libraries cross-check, never replace, the in-house
implementation" discipline (ADR-0151's own scoping). See ADR-0207.

**No new backtest is run.** Every number this script needs already
exists in a committed `run_full_validation.yml` report JSON
(`docs/research/reports/full-validation-*.json`) -- specifically each
candidate's `walk_forward.folds[i].{is_valid_performance,
net.cumulative_return}`. This script reconstructs the EXACT
`fold_returns_by_candidate` matrix `scripts/run_long_horizon_validation.py`
itself built (same common-valid-fold-index intersection across every
candidate -- see that script's own comment for why a per-candidate-only
filter would desynchronize fold positions) and feeds it to both
implementations.

**Two disclosed, non-bit-identical points between the two
implementations** (both confirmed by reading `purgedcv`'s own source,
not assumed):
1. `purgedcv.probability_of_backtest_overfitting`'s CSCV ranking metric
   defaults to Sharpe, not mean return -- this script passes
   `metric=lambda r: r.mean()` explicitly so both implementations rank
   candidates by the SAME statistic (mean net fold return), isolating
   the comparison to "does the CSCV combinatorial bookkeeping agree",
   not "which ranking statistic was used."
2. **Confirmed root cause of a real ~7pp PBO gap on this project's own
   real data (2026-09-26)**: when the fold count is NOT evenly
   divisible by `num_groups` (58 folds / 8 groups here -- `58 = 8*7+2`),
   `strategy_research.pbo_dsr.compute_pbo` puts the entire 2-fold
   remainder into the LAST group (sizes `[7,7,7,7,7,7,7,9]`, see that
   function's own "the last group absorbs any remainder" comment), while
   `purgedcv._pbo._contiguous_blocks` distributes the remainder across
   the FIRST `remainder` groups instead (sizes `[8,8,7,7,7,7,7,7]`,
   confirmed by reading its source directly). The Bailey et al. (2015)
   CSCV paper itself assumes an evenly-divisible fold count and does not
   specify a remainder convention -- neither choice is "more correct"
   per the paper, they are simply different, equally-defensible ad hoc
   extensions to the uneven case, and this script does not silently
   normalize away that difference. `self_check` below (this script's own
   reconstruction vs the report's persisted `pbo_probability`) is the
   real regression guard; the `pbo.absolute_difference` against
   `purgedcv` is honest cross-implementation disagreement from this one
   documented cause, not a bug in either side.
3. `purgedcv`'s own default Sharpe helper (`purgedcv._pbo.sharpe`) uses
   SAMPLE standard deviation (`ddof=1`); this project's own
   `compute_dsr_for_all_candidates` uses POPULATION standard deviation
   (`statistics.pstdev`, `ddof=0`). Both `probabilistic_sharpe_ratio`
   formulas are otherwise identical (Bailey & Lopez de Prado 2012 Eq. 7,
   confirmed by reading `purgedcv`'s own docstring against
   `pbo_dsr.py`'s) -- and DSR values on this project's real data agree
   to within 0.0014 (max) / 0.0005 (mean) absolute probability, the
   expected size of a population-vs-sample-stdev difference at 58
   observations. DSR values are reported side by side regardless, never
   forced into a false "PASS."

Usage:
    pip install -e '.[backtest-integrity-stats]'
    python3 scripts/cross_verify_pbo_dsr_with_purgedcv.py \\
        --report docs/research/reports/full-validation-20260925T160732Z.json \\
        --output docs/research/reports/pbo_dsr_purgedcv_cross_check.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np  # noqa: E402
import purgedcv  # noqa: E402

from strategy_research.pbo_dsr import compute_dsr_for_all_candidates, compute_pbo  # noqa: E402


def _load_fold_returns_by_candidate(report: dict) -> dict[str, list[float]]:
    """Reproduces `scripts/run_long_horizon_validation.py`'s own
    common-valid-fold-index intersection exactly, from the persisted
    report JSON instead of a live `WalkForwardAggregate`."""
    validity_by_candidate: dict[str, dict[int, bool]] = {}
    net_return_by_candidate: dict[str, dict[int, float]] = {}
    for name, candidate in report["results"].items():
        folds = candidate.get("walk_forward", {}).get("folds")
        if not folds:
            continue
        validity_by_candidate[name] = {f["fold_index"]: f["is_valid_performance"] for f in folds}
        net_return_by_candidate[name] = {f["fold_index"]: f["net"]["cumulative_return"] for f in folds}

    if not validity_by_candidate:
        raise ValueError("report has no candidates with walk_forward.folds -- nothing to cross-verify")

    common_valid_fold_indices = sorted(
        set.intersection(*[
            {idx for idx, valid in validity.items() if valid} for validity in validity_by_candidate.values()
        ])
    )
    if len(common_valid_fold_indices) < 8:
        raise ValueError(
            f"only {len(common_valid_fold_indices)} fold indices are valid across every candidate -- "
            "need at least 8 (num_groups) to cross-verify"
        )

    return {
        name: [net_return_by_candidate[name][idx] for idx in common_valid_fold_indices]
        for name in validity_by_candidate
    }


def _our_variance_of_trial_sharpes(fold_returns_by_candidate: dict[str, list[float]]) -> tuple[float, int]:
    """Exactly `compute_dsr_for_all_candidates`'s own `variance_of_trial_sharpes`
    computation, exposed here so it can be fed into `purgedcv.
    deflated_sharpe_ratio` too (the library requires the caller to
    supply this -- see this module's own docstring point 2)."""
    names = sorted(fold_returns_by_candidate)
    observed = [
        statistics.mean(fold_returns_by_candidate[n]) / statistics.pstdev(fold_returns_by_candidate[n])
        for n in names
    ]
    return statistics.pvariance(observed), len(names)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", required=True, help="a run_full_validation.yml report JSON")
    parser.add_argument("--output", default=None, help="output comparison JSON path")
    args = parser.parse_args(argv)

    report = json.loads(Path(args.report).read_text())
    fold_returns_by_candidate = _load_fold_returns_by_candidate(report)
    names = sorted(fold_returns_by_candidate)
    fold_count = len(fold_returns_by_candidate[names[0]])
    num_groups = 8  # matches run_long_horizon_validation.py's own compute_pbo(..., num_groups=8 default)

    # -- Our own implementation, recomputed from the same reconstructed
    # matrix as a sanity check that this script's own fold-alignment
    # logic actually matches production (should equal report["pbo_dsr_result"]).
    our_pbo = compute_pbo(fold_returns_by_candidate, num_groups=num_groups)
    our_dsr = compute_dsr_for_all_candidates(fold_returns_by_candidate)

    reported_pbo = report.get("pbo_dsr_result", {}).get("pbo_probability")
    self_check_matches = reported_pbo is not None and abs(our_pbo.probability - reported_pbo) < 1e-9

    # -- purgedcv, same input matrix, mean-return ranking metric (see
    # module docstring point 1).
    returns_matrix = np.array([fold_returns_by_candidate[n] for n in names], dtype=float)
    purgedcv_pbo_result = purgedcv.probability_of_backtest_overfitting(
        returns_matrix, n_splits=num_groups, metric=lambda r: float(np.mean(r)),
    )

    var_sharpe, num_trials = _our_variance_of_trial_sharpes(fold_returns_by_candidate)
    purgedcv_dsr_by_name = {
        name: purgedcv.deflated_sharpe_ratio(
            np.array(fold_returns_by_candidate[name], dtype=float),
            n_trials=num_trials,
            var_sharpe=var_sharpe,
        )
        for name in names
    }

    dsr_diffs = [abs(our_dsr[name].deflated_sharpe_ratio - purgedcv_dsr_by_name[name]) for name in names]

    comparison = {
        "source_report": str(args.report),
        "candidate_count": len(names),
        "common_valid_fold_count": fold_count,
        "num_groups": num_groups,
        "self_check": {
            "reported_pbo_probability": reported_pbo,
            "recomputed_our_pbo_probability": our_pbo.probability,
            "matches_reported": self_check_matches,
        },
        "pbo": {
            "our_probability": our_pbo.probability,
            "purgedcv_probability": purgedcv_pbo_result.pbo,
            "our_num_combinations": our_pbo.num_combinations,
            "purgedcv_num_combinations": purgedcv_pbo_result.n_combos,
            "absolute_difference": abs(our_pbo.probability - purgedcv_pbo_result.pbo),
        },
        "dsr": {
            "var_sharpe_across_trials": var_sharpe,
            "num_trials": num_trials,
            "by_candidate": {
                name: {
                    "our_dsr": our_dsr[name].deflated_sharpe_ratio,
                    "purgedcv_dsr": purgedcv_dsr_by_name[name],
                    "absolute_difference": abs(our_dsr[name].deflated_sharpe_ratio - purgedcv_dsr_by_name[name]),
                }
                for name in names
            },
            "max_absolute_difference": max(dsr_diffs),
            "mean_absolute_difference": statistics.mean(dsr_diffs),
        },
    }

    out_path = Path(args.output) if args.output else Path(args.report).with_name(
        Path(args.report).stem + "_purgedcv_cross_check.json"
    )
    out_path.write_text(json.dumps(comparison, indent=2, sort_keys=True) + "\n")

    print(f"self-check (our own recompute vs report): matches_reported={self_check_matches}")
    print(f"PBO: ours={our_pbo.probability:.6f} purgedcv={purgedcv_pbo_result.pbo:.6f} "
          f"diff={comparison['pbo']['absolute_difference']:.6f}")
    print(f"DSR: max_abs_diff={comparison['dsr']['max_absolute_difference']:.6f} "
          f"mean_abs_diff={comparison['dsr']['mean_absolute_difference']:.6f}")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
