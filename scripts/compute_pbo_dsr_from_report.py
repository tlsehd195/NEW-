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
from strategy_research.pbo_dsr import compute_dsr_for_all_candidates, compute_pbo  # noqa: E402
from strategy_research.walk_forward_evaluation import WalkForwardAggregate  # noqa: E402

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

    fold_returns_by_candidate = {}
    for name, result in report.get("results", {}).items():
        folds = result["walk_forward"]["folds"]
        if len(folds) < _MIN_FOLDS_FOR_PBO_DSR:
            print(f"Skipping {name!r}: only {len(folds)} fold(s), need >= {_MIN_FOLDS_FOR_PBO_DSR}")
            continue
        fold_returns_by_candidate[name] = [f["net"]["cumulative_return"] for f in folds]

    if len(fold_returns_by_candidate) < 2:
        print(
            f"ERROR: only {len(fold_returns_by_candidate)} candidate(s) with >= {_MIN_FOLDS_FOR_PBO_DSR} "
            "real folds -- PBO/DSR requires at least 2 to compare.",
            file=sys.stderr,
        )
        return 1

    pbo_result = compute_pbo(fold_returns_by_candidate)
    dsr_by_name = compute_dsr_for_all_candidates(fold_returns_by_candidate)

    print(
        f"PBO (Probability of Backtest Overfitting): {pbo_result.probability:.2%} "
        f"across {pbo_result.num_combinations} CSCV splits ({pbo_result.num_candidates} candidates, "
        f"{pbo_result.num_groups} groups)"
    )
    print(f"CANDIDATE requires PBO < {MAX_PBO_FOR_CANDIDATE:.0%} and Deflated Sharpe Ratio >= {MIN_DSR_FOR_CANDIDATE:.0%}")
    print()

    report["pbo_dsr_result"] = {
        "pbo_probability": pbo_result.probability,
        "num_combinations": pbo_result.num_combinations,
        "num_groups": pbo_result.num_groups,
        "deflated_sharpe_by_candidate": {n: r.deflated_sharpe_ratio for n, r in dsr_by_name.items()},
    }

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
