#!/usr/bin/env python3
"""Computes PBO (Probability of Backtest Overfitting) and Deflated
Sharpe Ratio from an EXISTING `run_long_horizon_validation.py` report
JSON, without re-running any walk-forward backtest.

Why this exists: `run_long_horizon_validation.py` already computes
PBO/DSR internally when applicable (see that script's own docstring
and `strategy_research.pbo_dsr`) -- but that requires re-running the
full walk-forward evaluation, which for a long real-data run can take
a long time. Every per-fold NET return this needs is already persisted
in a prior run's report JSON (`report["results"][name]["walk_forward"]["folds"]`,
each carrying `net.cumulative_return`), so PBO/DSR can be computed
directly from an already-existing report -- a pure, fast statistics
computation with no network access and no backtest re-run.

This script makes NO network call and re-runs NO backtest, so (like
`scripts/import_external_market_data.py`) it is safe to exercise
directly in the automated test suite.

Usage:
    python3 scripts/compute_pbo_dsr_from_report.py \\
        --report ./data/real_2010_latest/long_horizon_validation.json

Refuses to compute anything if the report's own `data_status` is not
`"REAL"` -- PBO/DSR answers a question about real-market noise vs.
skill; running it against a synthetic pipeline-correctness dry run
would produce a real-looking number about a question nobody is
asking (the same discipline `classify_evidence_level`'s `is_real_data`
gate already enforces).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from strategy_research.evidence import (  # noqa: E402
    MAX_PBO_FOR_CANDIDATE,
    MIN_DSR_FOR_CANDIDATE,
    classify_evidence_level,
)
from strategy_research.pbo_dsr import (  # noqa: E402
    compute_dsr_for_all_candidates,
    compute_pbo,
    effective_trial_count,
)
from strategy_research.reality_check_spa import (  # noqa: E402
    excess_returns_vs_benchmark,
    hansen_spa,
    white_reality_check,
)
from strategy_research.walk_forward_evaluation import WalkForwardAggregate  # noqa: E402

_BENCHMARK_CANDIDATE_NAME = "buy_and_hold"

_MIN_FOLDS_FOR_PBO_DSR = 6


def _reconstruct_aggregate(name: str, wf: dict) -> WalkForwardAggregate:
    """Rebuilds just enough of a `WalkForwardAggregate` from the report
    JSON's `walk_forward` dict to re-run `classify_evidence_level` --
    `folds=()` is safe because that function never reads `.folds`
    itself, only the aggregate scalar/dict fields (the same pattern
    `tests/strategy_research/test_evidence.py`'s own `_agg()` helper
    already relies on)."""
    return WalkForwardAggregate(
        strategy_name=name,
        train_window_months=wf["train_window_months"],
        test_window_months=wf["test_window_months"],
        step_months=wf["step_months"],
        fold_count=wf["fold_count"],
        # .get() with a fold_count fallback: a report written before
        # this field existed (pre integrity-fold-exclusion fix) has no
        # total_fold_count/excluded_integrity_invalid_fold_count keys
        # at all -- fold_count==total_fold_count, 0 excluded, is the
        # correct backward-compatible reading for such a report (it
        # never excluded anything, which is exactly the bug this fix
        # addresses, but reconstructing it here must not crash on an
        # older file).
        total_fold_count=wf.get("total_fold_count", wf["fold_count"]),
        excluded_integrity_invalid_fold_count=wf.get("excluded_integrity_invalid_fold_count", 0),
        positive_net_return_folds=wf["positive_net_return_folds"],
        median_net_cumulative_return=wf["median_net_cumulative_return"],
        median_net_sharpe=wf["median_net_sharpe"],
        stdev_net_cumulative_return=wf["stdev_net_cumulative_return"],
        worst_max_drawdown=wf["worst_max_drawdown"],
        worst_fold_index=wf["worst_fold_index"],
        best_net_cumulative_return=wf["best_net_cumulative_return"],
        best_fold_index=wf["best_fold_index"],
        regime_breakdown=wf["regime_breakdown"],
        folds=(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", required=True, type=Path, help="Path to an existing long_horizon_validation.json")
    parser.add_argument("--out", type=Path, default=None, help="Where to write the updated report (default: overwrite --report in place)")
    args = parser.parse_args(argv)

    report = json.loads(args.report.read_text())

    if report.get("data_status") != "REAL":
        print(
            f"ERROR: report data_status={report.get('data_status')!r} -- refusing to compute PBO/DSR "
            "on anything but REAL data (see this script's own module docstring).",
            file=sys.stderr,
        )
        return 1

    # External audit finding (2026-09-24): "folds" is EVERY fold a
    # candidate produced, including ones with an ERROR/CRITICAL
    # integrity issue -- a fold's own is_valid_performance flag (added
    # alongside this fix) must be checked before its return counts
    # toward PBO/DSR. A report written before this field existed has no
    # "is_valid_performance" key at all; treated as valid (matches that
    # older report's own un-filtered fold_count, since it never excluded
    # anything either).
    #
    # NOT a simple per-candidate filter: compute_pbo's own CSCV
    # algorithm requires every candidate's fold-return list to have the
    # SAME LENGTH, in the SAME fold order -- position i must mean the
    # SAME time window across every candidate being compared. Candidates
    # first prequalify on their OWN valid-fold count (unchanged
    # threshold check), then the folds actually used are the
    # intersection of valid fold_index values across every prequalified
    # candidate, so every survivor's list stays the same length and
    # still refers to the same underlying windows.
    prequalified: dict[str, dict] = {}
    for name, result in report.get("results", {}).items():
        folds_by_index = {f["fold_index"]: f for f in result["walk_forward"]["folds"]}
        valid_indices = {idx for idx, f in folds_by_index.items() if f.get("is_valid_performance", True)}
        if len(valid_indices) < _MIN_FOLDS_FOR_PBO_DSR:
            print(f"Skipping {name!r}: only {len(valid_indices)} valid fold(s), need >= {_MIN_FOLDS_FOR_PBO_DSR}")
            continue
        prequalified[name] = folds_by_index

    common_valid_fold_indices = sorted(
        set.intersection(*[
            {idx for idx, f in folds_by_index.items() if f.get("is_valid_performance", True)}
            for folds_by_index in prequalified.values()
        ])
    ) if prequalified else []

    fold_returns_by_candidate = {
        name: [folds_by_index[idx]["net"]["cumulative_return"] for idx in common_valid_fold_indices]
        for name, folds_by_index in prequalified.items()
        if len(common_valid_fold_indices) >= _MIN_FOLDS_FOR_PBO_DSR
    }

    if len(fold_returns_by_candidate) < 2:
        print(
            f"ERROR: only {len(fold_returns_by_candidate)} candidate(s) with >= {_MIN_FOLDS_FOR_PBO_DSR} "
            "real folds -- PBO/DSR requires at least 2 to compare.",
            file=sys.stderr,
        )
        return 1

    pbo_result = compute_pbo(fold_returns_by_candidate)
    dsr_by_name = compute_dsr_for_all_candidates(fold_returns_by_candidate)

    # Supplementary diagnostic only (relayed thread's ask, ADR -- see
    # module docstring of reality_check_spa.py): does the apparent best
    # candidate's edge over the same-names buy_and_hold benchmark
    # survive White's Reality Check / Hansen's SPA bootstrap, once the
    # fact that several candidates were compared is accounted for?
    # Never changes `evidence_assessment` or any existing verdict --
    # recorded alongside PBO/DSR as an additional field. Skipped
    # entirely when the benchmark itself isn't among the prequalified
    # candidates (e.g. too few valid folds), or when excluding it would
    # leave fewer than 2 other candidates to compare.
    reality_check_spa_result: dict | None = None
    non_benchmark_candidates = {
        name: returns
        for name, returns in fold_returns_by_candidate.items()
        if name != _BENCHMARK_CANDIDATE_NAME
    }
    if _BENCHMARK_CANDIDATE_NAME in fold_returns_by_candidate and len(non_benchmark_candidates) >= 2:
        excess_returns = excess_returns_vs_benchmark(
            non_benchmark_candidates, fold_returns_by_candidate[_BENCHMARK_CANDIDATE_NAME]
        )
        rc_result = white_reality_check(excess_returns)
        spa_result = hansen_spa(excess_returns)
        reality_check_spa_result = {
            "benchmark": _BENCHMARK_CANDIDATE_NAME,
            "reality_check_p_value": rc_result.p_value,
            "reality_check_best_candidate": rc_result.best_candidate,
            "spa_p_value": spa_result.p_value,
            "spa_best_candidate": spa_result.best_candidate,
            "num_bootstrap_samples": rc_result.num_bootstrap_samples,
            "num_folds": rc_result.num_folds,
            "candidate_names": list(rc_result.candidate_names),
        }
        print(
            f"White Reality Check p-value: {rc_result.p_value:.3f} (best: {rc_result.best_candidate}); "
            f"Hansen SPA p-value: {spa_result.p_value:.3f} (best: {spa_result.best_candidate}) "
            f"-- vs {_BENCHMARK_CANDIDATE_NAME} benchmark, supplementary only"
        )
        print()

    print(
        f"PBO (Probability of Backtest Overfitting): {pbo_result.probability:.2%} "
        f"across {pbo_result.num_combinations} CSCV splits ({pbo_result.num_candidates} candidates, "
        f"{pbo_result.num_groups} groups)"
    )
    # ADR-0238, supplementary only: never changes the verdict above.
    try:
        n_eff: float | None = effective_trial_count(fold_returns_by_candidate)
    except ValueError:
        n_eff = None
    if n_eff is not None:
        print(f"Effective independent trials (ADR-0238, supplementary): {n_eff:.1f} of {len(fold_returns_by_candidate)} candidates")
    print(f"CANDIDATE requires PBO < {MAX_PBO_FOR_CANDIDATE:.0%} and Deflated Sharpe Ratio >= {MIN_DSR_FOR_CANDIDATE:.0%}")
    print()

    report["pbo_dsr_result"] = {
        "pbo_probability": pbo_result.probability,
        "num_combinations": pbo_result.num_combinations,
        "num_groups": pbo_result.num_groups,
        "deflated_sharpe_by_candidate": {n: r.deflated_sharpe_ratio for n, r in dsr_by_name.items()},
        "effective_trial_count": n_eff,
    }
    if reality_check_spa_result is not None:
        report["reality_check_spa_result"] = reality_check_spa_result

    for name in sorted(report.get("results", {})):
        result = report["results"][name]
        wf = result["walk_forward"]
        dsr = dsr_by_name.get(name)
        pbo_probability = pbo_result.probability if name in fold_returns_by_candidate else None
        deflated_sharpe_ratio = dsr.deflated_sharpe_ratio if dsr is not None else None

        if name in fold_returns_by_candidate:
            aggregate = _reconstruct_aggregate(name, wf)
            evidence = classify_evidence_level(
                aggregate, is_real_data=True, pbo_dsr_applied=True,
                pbo_probability=pbo_probability, deflated_sharpe_ratio=deflated_sharpe_ratio,
            )
            result["evidence_assessment"] = {
                "level": evidence.level.value, "reason": evidence.reason,
                "fold_count": evidence.fold_count, "positive_fold_ratio": evidence.positive_fold_ratio,
                "distinct_known_regimes": evidence.distinct_known_regimes,
                "pbo_probability": pbo_probability, "deflated_sharpe_ratio": deflated_sharpe_ratio,
            }
            print(f"{name}: evidence={evidence.level.value}")
            print(f"  {evidence.reason}")
            print(f"  observed fold Sharpe={dsr.observed_sharpe:.3f}")
        else:
            print(f"{name}: evidence unchanged (insufficient folds for PBO/DSR)")
        print()

    out_path = args.out or args.report
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"Updated report written to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
