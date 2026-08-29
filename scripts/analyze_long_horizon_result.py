#!/usr/bin/env python3
"""Track A (Phase 32): decomposes an EXISTING
`run_long_horizon_validation.py` report JSON into per-strategy
breakdowns explaining WHY a result looks the way it does -- fold
return distribution, regime-conditional performance (over the
walk-forward TRAIN+VALIDATION region), gross-to-net cost drag, and
(when the report has these fields -- older reports predate them)
drawdown duration and per-security concentration.

Why this exists as its own script rather than being folded into
`compute_pbo_dsr_from_report.py`: this performs no statistical test
and touches no `evidence_assessment` field -- it is a pure descriptive
decomposition of numbers the report already contains, run separately
from (and safely repeatable after) PBO/DSR computation. Like that
script, it makes no network call, re-runs no backtest, and needs no
DuckDB catalog -- only the report JSON file -- so it is safe to
exercise directly in the automated test suite and safe to run
against a report from any machine that produced one.

Does NOT compute Signal IC (needs a live `DataRepository` to re-score
securities, which this script does not have) or upside/downside
capture ratios (needs the full portfolio value time series, which
this report's schema does not persist). Both print as explicitly
NOT_COMPUTABLE_FROM_REPORT rather than being silently skipped.

Usage:
    python3 scripts/analyze_long_horizon_result.py \\
        --report ./data/real_2010_latest/long_horizon_validation.json \\
        [--out ./data/real_2010_latest/track_a_analysis.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from strategy_research.result_analysis import analyze_report  # noqa: E402


def _print_strategy(a) -> None:
    print(f"=== {a.strategy_name} ===")
    fd = a.fold_distribution
    print(
        f"  Walk-forward folds: n={fd.fold_count} win_rate={_pct(fd.win_rate)} "
        f"mean_return={_pct(fd.mean_return)} median_return={_pct(fd.median_return)} "
        f"stdev={_pct(fd.stdev_return)} worst={_pct(fd.worst_return)} best={_pct(fd.best_return)} "
        f"mean_sharpe={_num(fd.mean_sharpe)}"
    )
    if a.regime_conditional:
        print("  Regime-conditional (walk-forward TRAIN+VALIDATION only, NOT held-out TEST):")
        for bucket in a.regime_conditional:
            print(
                f"    {bucket.regime}: n={bucket.fold_count} win_rate={_pct(bucket.win_rate)} "
                f"mean_return={_pct(bucket.mean_return)}"
            )
    if a.walk_forward_cost_drag:
        cd = a.walk_forward_cost_drag
        print(
            f"  Walk-forward cost drag (fold-average, NOT a compounded multi-fold return): "
            f"gross={_pct(cd.gross_cumulative_return)} net={_pct(cd.net_cumulative_return)} "
            f"drag={_pct(cd.cost_drag)} turnover={_num(cd.turnover)}"
        )
    if a.held_out_cost_drag:
        cd = a.held_out_cost_drag
        print(
            f"  Held-out TEST cost drag: gross={_pct(cd.gross_cumulative_return)} "
            f"net={_pct(cd.net_cumulative_return)} drag={_pct(cd.cost_drag)} "
            f"turnover={_num(cd.turnover)} total_cost=${cd.total_transaction_cost:,.2f}"
        )
    if a.held_out_benchmark_comparison:
        bc = a.held_out_benchmark_comparison
        print(
            f"  Held-out TEST vs benchmark: strategy_net={_pct(bc.strategy_net_cumulative_return)} "
            f"benchmark={_pct(bc.benchmark_cumulative_return)} excess={_pct(bc.excess_return)} "
            f"strategy_maxdd={_pct(bc.strategy_max_drawdown)} benchmark_maxdd={_pct(bc.benchmark_max_drawdown)}"
        )
        print("    upside/downside capture: NOT_COMPUTABLE_FROM_REPORT (needs full return time series)")
    if not a.held_out_drawdown_field_present:
        print("  Held-out drawdown duration: FIELD_NOT_IN_REPORT (predates ADR's drawdown-duration addition; re-run to get it)")
    else:
        print(f"  Held-out max drawdown duration (days): {a.held_out_drawdown_duration_days}")
    if not a.held_out_concentration_present:
        print("  Per-security concentration: FIELD_NOT_IN_REPORT (predates concentration analysis addition; re-run to get it)")
    print(
        f"  Evidence: level={a.evidence_level} pbo={_num(a.pbo_probability)} "
        f"dsr={_num(a.deflated_sharpe_ratio)} positive_fold_ratio={_pct(a.positive_fold_ratio)}"
    )
    if a.evidence_reason:
        print(f"    {a.evidence_reason}")
    print("  Signal IC (rank correlation of score vs forward return): NOT_COMPUTABLE_FROM_REPORT "
          "(needs a live DataRepository -- see strategy_research.signal_ic.compute_ic_series, "
          "run separately with catalog access)")
    print()


def _pct(x) -> str:
    return f"{x:.2%}" if x is not None else "N/A"


def _num(x) -> str:
    return f"{x:.4f}" if x is not None else "N/A"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", required=True, type=Path, help="Path to an existing long_horizon_validation.json")
    parser.add_argument("--out", type=Path, default=None, help="Optional path to also write the analysis as JSON")
    args = parser.parse_args(argv)

    report = json.loads(args.report.read_text())
    analyses = analyze_report(report)

    print(f"Track A analysis of: {args.report}")
    print(f"data_status={report.get('data_status')} universe={report.get('universe')} "
          f"universe_version={report.get('universe_version')}")
    print()
    for a in analyses:
        _print_strategy(a)

    if args.out is not None:
        args.out.write_text(json.dumps([asdict(a) for a in analyses], indent=2, default=str))
        print(f"Analysis written to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
