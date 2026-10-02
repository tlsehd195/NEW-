#!/usr/bin/env python3
"""Research-window run of the ADR-0235 index overlays (`sma_10m`,
`vol_target_10`) against SPY buy-and-hold: one continuous backtest per
rule through the unmodified BacktestEngine, cash earning the 3-month
T-bill yield. Two trials, parameters fixed in the ADR, so no walk-forward
or PBO. Refuses any range that overlaps a locked TEST window.

    python3 scripts/run_index_overlay_validation.py \\
        --price-db-path ./data/price_catalog --macro-db-path ./data/macro_store \\
        --report-json ./index_overlay_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backtest.engine import BacktestConfig, BacktestEngine  # noqa: E402
from backtest.risk_free import RISK_FREE_SERIES_ID, RiskFreeRates  # noqa: E402
from backtest.total_return import build_total_return_benchmark_points  # noqa: E402
from data_infra.exchange_calendars_adapter import build_xnys_calendar  # noqa: E402
from macro_filter.overlays import OVERLAY_RULES, IndexOverlayStrategy  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.macro_repository import DuckDBMacroRepository  # noqa: E402
from strategy_research.locked_windows import overlaps_any_locked_window  # noqa: E402

EQUITY = "SPY"
BENCHMARK_ID = "SPY_TOTAL_RETURN_REAL"
MAX_DRAWDOWN_GAIN = 0.15
MAX_CAGR_GIVEUP = 0.015


def _utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


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


def pass_rule(mine: dict, base: dict) -> dict:
    checks = {
        "max_drawdown_15pts_shallower": mine["max_drawdown"] - base["max_drawdown"] >= MAX_DRAWDOWN_GAIN,
        "sharpe_not_lower": mine["sharpe_ratio"] >= base["sharpe_ratio"],
        "cagr_within_1_5pts": base["cagr"] - mine["cagr"] <= MAX_CAGR_GIVEUP,
    }
    return {"checks": checks, "grade": "RESEARCH_PASS" if all(checks.values()) else "FAIL"}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--price-db-path", required=True)
    parser.add_argument("--macro-db-path", required=True)
    parser.add_argument("--start", default="2000-01-01")
    parser.add_argument("--end", default="2013-03-20")
    parser.add_argument("--initial-capital", type=float, default=10_000.0)
    parser.add_argument("--report-json", required=True)
    args = parser.parse_args(argv)

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    locked = overlaps_any_locked_window(_utc(start), _utc(end))
    if locked:
        print(f"refusing: {start}..{end} overlaps locked windows {[w.name for w in locked]}", file=sys.stderr)
        return 2

    macro_engine = StorageEngine(StorageConfig(root_dir=args.macro_db_path), read_only=True)
    try:
        records = DuckDBMacroRepository(macro_engine).get_all_vintages(RISK_FREE_SERIES_ID)
    finally:
        macro_engine.close()
    rates = RiskFreeRates.from_macro_records(records, source=f"macro store {args.macro_db_path}")

    price_engine = StorageEngine(StorageConfig(root_dir=args.price_db_path))
    repository = DuckDBDataRepository(price_engine, calendars={"US_EQUITY": build_xnys_calendar()})
    results: dict[str, dict] = {}
    try:
        spy_bars = repository.get_bars(EQUITY, _utc(start), _utc(end), as_of_time=_utc(end))
        if not spy_bars:
            print("no SPY bars in the price catalog", file=sys.stderr)
            return 1
        spy_actions = repository.get_corporate_actions(EQUITY, _utc(start), _utc(end), as_of_time=_utc(end))
        for point in build_total_return_benchmark_points(BENCHMARK_ID, spy_bars, spy_actions, as_of_time=_utc(end)):
            repository.add_benchmark_point(point)
        for rule in OVERLAY_RULES:
            strategy = IndexOverlayStrategy(EQUITY, rule)
            config = BacktestConfig(
                market="US_EQUITY", start_date=start, end_date=end, initial_capital=args.initial_capital,
                security_ids=(EQUITY,), benchmark_id=BENCHMARK_ID, code_version="index_overlay_v1",
                risk_free_rate=rates.average_annual_rate(start, end), cash_interest=rates,
            )
            result = BacktestEngine(repository, config, strategy).run()
            exposures = [e for _, e in strategy.exposure_log]
            results[rule] = {
                **_perf(result),
                "mean_exposure": round(sum(exposures) / len(exposures), 4) if exposures else None,
                "exposure_changes": sum(1 for a, b in zip(exposures, exposures[1:]) if a != b),
            }
            print(f"{rule}: {json.dumps(results[rule])}", flush=True)
    finally:
        price_engine.close()

    base = results["no_filter"]
    report = {
        "start": start.isoformat(), "end": end.isoformat(), "adr": "ADR-0235",
        "results": results,
        "pass_rule": {r: pass_rule(results[r], base) for r in OVERLAY_RULES if r != "no_filter"},
        "caveat": "Two bear markets (2000-02, 2008-09) only; RESEARCH_PASS is not validation.",
    }
    Path(args.report_json).write_text(json.dumps(report, indent=2))
    print(json.dumps(report["pass_rule"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
