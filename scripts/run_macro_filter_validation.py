#!/usr/bin/env python3
"""Research-window validation of the macro filter (ADR-0220).

Runs every pre-registered exposure rule (`macro_filter.signals.
pre_registered_rules`: no filter, the combined filter, each signal
alone) as `MacroExposureStrategy` on SPY through the unmodified
`BacktestEngine`, over real point-in-time data:

1. one continuous net-of-cost run per rule over the whole window
   (CAGR, Sharpe, max drawdown, turnover, time de-risked);
2. walk-forward folds per rule (fresh capital each fold), from which
   PBO is computed over all rules and the Deflated Sharpe Ratio over
   each rule's per-fold excess return against the unfiltered baseline
   (trial count = every non-baseline rule).

The pass rule (ADR-0220, fixed before the first run) is applied to the
numbers at the end; this script never grades anything above CANDIDATE.

Never touches the locked TEST windows: the run refuses any range that
overlaps `strategy_research.locked_windows`.

Usage:
    python3 scripts/run_macro_filter_validation.py \\
        --price-db-path ./data/price_catalog --macro-db-path ./data/macro_store \\
        [--start 2000-01-01] [--end 2020-08-27] --report-json report.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backtest.engine import BacktestConfig, BacktestEngine  # noqa: E402
from backtest.total_return import build_total_return_benchmark_points  # noqa: E402
from data_infra.exchange_calendars_adapter import build_xnys_calendar  # noqa: E402
from macro_filter.config import ALL_SIGNALS, DEFAULT_MACRO_FILTER_CONFIG, MacroFilterConfig  # noqa: E402
from macro_filter.series import build_series  # noqa: E402
from macro_filter.signals import (  # noqa: E402
    BASELINE_RULE,
    SIGNAL_SERIES,
    MacroSignalEngine,
    pre_registered_rules,
)
from macro_filter.strategy import MacroExposureStrategy  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.macro_repository import DuckDBMacroRepository  # noqa: E402
from strategy_research.locked_windows import overlaps_any_locked_window  # noqa: E402
from strategy_research.pbo_dsr import compute_dsr_for_all_candidates, compute_pbo  # noqa: E402
from strategy_research.walk_forward_evaluation import run_walk_forward_evaluation  # noqa: E402

EQUITY = "SPY"
BENCHMARK_ID = "SPY_TOTAL_RETURN_REAL"
DSR_PASS = 0.95


def _log(message: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {message}", flush=True)


def _utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def load_signal_engine(macro_db_path: str, config: MacroFilterConfig) -> tuple[MacroSignalEngine, dict]:
    engine = StorageEngine(StorageConfig(root_dir=macro_db_path), read_only=True)
    try:
        repo = DuckDBMacroRepository(engine)
        needed = sorted({s for ids in SIGNAL_SERIES.values() for s in ids})
        series, coverage = {}, {}
        for series_id in needed:
            records = repo.get_all_vintages(series_id)
            built = build_series(series_id, records, config.fallback_lag_days)
            series[series_id] = built
            coverage[series_id] = {
                "vintage_rows": len(records),
                "first_vintage_date": built.first_vintage_date.isoformat() if built.first_vintage_date else None,
                "fallback_lag_days": config.fallback_lag_days.get(series_id),
            }
    finally:
        engine.close()
    return MacroSignalEngine(series, config), coverage


def exposure_stats(log: list[tuple[datetime, float]]) -> dict:
    if not log:
        return {"checkpoints": 0}
    exposures = [e for _, e in log]
    changes = sum(1 for a, b in zip(exposures, exposures[1:]) if a != b)
    return {
        "checkpoints": len(exposures),
        "mean_exposure": round(statistics.fmean(exposures), 4),
        "share_de_risked": round(sum(1 for e in exposures if e < 1.0) / len(exposures), 4),
        "exposure_changes": changes,
    }


def signal_availability(engine: MacroSignalEngine, checkpoints: list[datetime]) -> dict:
    out = {}
    for signal in ALL_SIGNALS:
        flags = [engine.evaluate(t).flags[signal] for t in checkpoints]
        available = [(t, f) for t, f in zip(checkpoints, flags) if f is not None]
        out[signal] = {
            "share_available": round(len(available) / len(flags), 4) if flags else 0.0,
            "first_available": available[0][0].date().isoformat() if available else None,
            "share_active_when_available": (
                round(sum(1 for _, f in available if f) / len(available), 4) if available else None
            ),
        }
    return out


def _perf(result) -> dict:
    p = result.performance
    return {
        "cumulative_return": p.cumulative_return,
        "cagr": p.cagr,
        "sharpe_ratio": p.sharpe_ratio,
        "max_drawdown": p.max_drawdown,
        "annualized_volatility": p.annualized_volatility,
        "turnover": p.turnover,
        "total_transaction_cost": p.total_transaction_cost,
        "benchmark_cumulative_return": p.benchmark_cumulative_return,
        "benchmark_max_drawdown": p.benchmark_max_drawdown,
        "is_valid_performance": result.is_valid_performance,
        "fills": len(result.fills),
    }


def pass_rule(rule: str, continuous: dict, dsr: dict) -> dict:
    """ADR-0220's pre-registered bar for a research-window CANDIDATE:
    DSR of the per-fold excess return over the baseline >= 0.95 (with the
    full trial count), AND a higher Sharpe AND a shallower max drawdown
    than the baseline in the continuous run. Anything else is
    INCONCLUSIVE; nothing here can be VALIDATED."""
    base = continuous[BASELINE_RULE.name]
    mine = continuous[rule]
    checks = {
        "dsr_excess_at_least_0_95": dsr.get(rule) is not None and dsr[rule] >= DSR_PASS,
        "sharpe_above_baseline": mine["sharpe_ratio"] > base["sharpe_ratio"],
        "max_drawdown_shallower": mine["max_drawdown"] > base["max_drawdown"],
    }
    return {"checks": checks, "grade": "CANDIDATE" if all(checks.values()) else "INCONCLUSIVE"}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--price-db-path", required=True)
    parser.add_argument("--macro-db-path", required=True)
    parser.add_argument("--start", default="2000-01-01")
    parser.add_argument("--end", default="2020-08-27")
    parser.add_argument("--initial-capital", type=float, default=10_000.0)
    parser.add_argument("--train-window-months", type=int, default=12)
    parser.add_argument("--test-window-months", type=int, default=6)
    parser.add_argument("--step-months", type=int, default=6)
    parser.add_argument("--pbo-groups", type=int, default=8)
    parser.add_argument("--report-json", required=True)
    args = parser.parse_args(argv)

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    locked = overlaps_any_locked_window(_utc(start), _utc(end))
    if locked:
        print(f"refusing: {start}..{end} overlaps locked windows {[w.name for w in locked]}", file=sys.stderr)
        return 2

    config = DEFAULT_MACRO_FILTER_CONFIG
    signal_engine, macro_coverage = load_signal_engine(args.macro_db_path, config)
    _log(f"macro series loaded: {macro_coverage}")

    price_engine = StorageEngine(StorageConfig(root_dir=args.price_db_path))
    repository = DuckDBDataRepository(price_engine, calendars={"US_EQUITY": build_xnys_calendar()})
    try:
        spy_bars = repository.get_bars(EQUITY, _utc(start), _utc(end), as_of_time=_utc(end))
        gld_bars = repository.get_bars(config.gold_symbol, _utc(start), _utc(end), as_of_time=_utc(end))
        if not spy_bars:
            print("no SPY bars in the price catalog", file=sys.stderr)
            return 1
        spy_actions = repository.get_corporate_actions(EQUITY, _utc(start), _utc(end), as_of_time=_utc(end))
        for point in build_total_return_benchmark_points(BENCHMARK_ID, spy_bars, spy_actions, as_of_time=_utc(end)):
            repository.add_benchmark_point(point)
        _log(f"SPY bars {len(spy_bars)} ({spy_bars[0].timestamp.date()}..{spy_bars[-1].timestamp.date()}), GLD bars {len(gld_bars)}")

        rules = pre_registered_rules()
        continuous: dict[str, dict] = {}
        checkpoints: list[datetime] = []
        for rule in rules:
            t0 = time.monotonic()
            strategy = MacroExposureStrategy(EQUITY, signal_engine, rule)
            bt_config = BacktestConfig(
                market="US_EQUITY", start_date=start, end_date=end, initial_capital=args.initial_capital,
                security_ids=(EQUITY,), benchmark_id=BENCHMARK_ID, code_version="macro_filter_validation_v1",
            )
            result = BacktestEngine(repository, bt_config, strategy).run()
            continuous[rule.name] = {**_perf(result), **exposure_stats(strategy.exposure_log)}
            if not checkpoints:
                checkpoints = [t for t, _ in strategy.exposure_log]
            _log(f"continuous {rule.name}: {json.dumps(continuous[rule.name])} ({time.monotonic() - t0:.0f}s)")

        fold_returns: dict[str, list[Optional[float]]] = {}
        fold_windows: list[dict] = []
        for rule in rules:
            t0 = time.monotonic()
            aggregate = run_walk_forward_evaluation(
                repository, lambda rule=rule: MacroExposureStrategy(EQUITY, signal_engine, rule), (EQUITY,),
                overall_start=_utc(start), overall_end=_utc(end),
                train_window_months=args.train_window_months, test_window_months=args.test_window_months,
                step_months=args.step_months, initial_capital=args.initial_capital, benchmark_id=BENCHMARK_ID,
            )
            fold_returns[rule.name] = [
                f.result.net.performance.cumulative_return if f.result.net.is_valid_performance else None
                for f in aggregate.folds
            ]
            if not fold_windows:
                fold_windows = [
                    {"test_start": f.test_start.date().isoformat(), "test_end": f.test_end.date().isoformat()}
                    for f in aggregate.folds
                ]
            _log(f"walk-forward {rule.name}: {aggregate.fold_count}/{aggregate.total_fold_count} valid folds ({time.monotonic() - t0:.0f}s)")
    finally:
        price_engine.close()

    valid = [i for i in range(len(fold_windows)) if all(fold_returns[r.name][i] is not None for r in rules)]
    by_rule = {r.name: [fold_returns[r.name][i] for i in valid] for r in rules}
    base = by_rule[BASELINE_RULE.name]
    excess = {
        name: [a - b for a, b in zip(values, base)]
        for name, values in by_rule.items() if name != BASELINE_RULE.name
    }
    pbo = compute_pbo(by_rule, num_groups=args.pbo_groups) if len(valid) >= args.pbo_groups else None
    # A rule that never differed from the baseline has an all-zero excess
    # series; it still counts as a trial (Sharpe 0).
    varying = {n: v for n, v in excess.items() if statistics.pstdev(v) > 0}
    dsr_results = compute_dsr_for_all_candidates(
        varying, zero_sharpe_trials=len(excess) - len(varying),
    ) if len(valid) >= 2 and varying else {}
    dsr = {name: r.deflated_sharpe_ratio for name, r in dsr_results.items()}
    walk_forward = {
        name: {
            "folds_beating_baseline": sum(1 for x in values if x > 0),
            "mean_excess_return": statistics.fmean(values) if values else None,
            "dsr_excess": dsr.get(name),
            "observed_excess_sharpe": dsr_results[name].observed_sharpe if name in dsr_results else None,
        }
        for name, values in excess.items()
    }
    grades = {r.name: pass_rule(r.name, continuous, dsr) for r in rules if r.name != BASELINE_RULE.name}

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "config_version": config.configuration_version(),
        "config": {k: v for k, v in config.__dict__.items()},
        "rules": [{"name": r.name, "signals": list(r.signals)} for r in rules],
        "trial_count": len(rules) - 1,
        "macro_coverage": macro_coverage,
        "signal_availability": signal_availability(signal_engine, checkpoints),
        "continuous": continuous,
        "walk_forward": {
            "train_window_months": args.train_window_months,
            "test_window_months": args.test_window_months,
            "step_months": args.step_months,
            "folds": fold_windows,
            "valid_fold_indices": valid,
            "fold_returns": fold_returns,
            "pbo": None if pbo is None else {"probability": pbo.probability, "num_groups": pbo.num_groups, "num_combinations": pbo.num_combinations},
            "by_rule": walk_forward,
        },
        "grades": grades,
        "notes": [
            "Cash earns 0% (risk_free_rate=0.0, ADR-0208): understates any rule that holds cash.",
            "Price catalog is a survivor-selected S&P 500 universe; only SPY and GLD are used here.",
            "Research window only; TEST_1/TEST_2 untouched. The best grade possible here is CANDIDATE.",
        ],
    }
    Path(args.report_json).write_text(json.dumps(report, indent=2, default=str))
    _log(f"grades: {json.dumps({k: v['grade'] for k, v in grades.items()})}")
    _log(f"PBO: {report['walk_forward']['pbo']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
