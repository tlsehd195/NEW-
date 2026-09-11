#!/usr/bin/env python3
"""First real-data strategy evaluation CLI (Phase 24 follow-up).

This script exists to run the FOUR existing strategy candidates
(`BuyAndHoldStrategy` Phase 2, `LongTermMomentumStrategy`/
`TrendVolatilityStrategy`/`RiskControlledMomentumStrategy` Phase 23)
against REAL market data already ingested by
`scripts/ingest_real_market_data.py` into an on-disk DuckDB catalog --
the first time this project has ever had real performance numbers to
look at, instead of the SYNTHETIC-fixture pipeline-validation results
every prior phase's own test suite produced.

It changes NO strategy code, NO cost/slippage model, NO backtest engine
logic -- it only wires `strategy_research.runner.run_gross_and_net`
(Phase 23, unmodified) against the real `DuckDBDataRepository` a real
ingestion run already populated, plus one new piece: building a REAL
SPY TOTAL_RETURN benchmark (`backtest.total_return.
build_total_return_benchmark_points`, Phase 20, unmodified -- previously
never callable with real data because no real SPY price+dividend
history existed) from whatever real SPY bars and corporate actions
`scripts/ingest_real_market_data.py` already persisted.

**This does NOT produce a "PROMISING_CANDIDATE"/"REJECTED" verdict.**
A single-window run with no train/validation/test split and no
walk-forward re-test cannot itself satisfy instruction section 19's
"단 하나의 좋은 backtest만으로 alpha라고 부르지 않는다" bar -- every
candidate's classification below is recorded as INCONCLUSIVE
regardless of how the numbers look, with `has_real_evaluation_data=True`
so the classification machinery correctly distinguishes "no real data
looked at" (every prior phase) from "real data looked at, but only one
window" (this run).

Usage (run in an environment with the real DuckDB catalog already
populated by scripts/ingest_real_market_data.py):
    python3 scripts/run_first_real_strategy_evaluation.py \\
        --universe PILOT_UNIVERSE \\
        --start 2023-01-02 --end 2024-12-31 \\
        --db-path ./data/real_market_data

Never executed by this repository's own automated test suite (it reads
real, already-ingested data from a path the test suite never has).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backtest.strategy import BuyAndHoldStrategy  # noqa: E402
from backtest.total_return import build_total_return_benchmark_points  # noqa: E402
from data_infra.calendar import US_EQUITY_NYSE  # noqa: E402
from data_infra.universe import BENCHMARK_SYMBOL, PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE4  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402

from strategy_research.classification import (  # noqa: E402
    CandidateClassification,
    CandidateEvaluation,
    PromisingCriteria,
)
from strategy_research.long_term_momentum import LongTermMomentumParameters, LongTermMomentumStrategy  # noqa: E402
from strategy_research.research_log import ResearchLog  # noqa: E402
from strategy_research.risk_controlled_momentum import (  # noqa: E402
    RiskControlledMomentumParameters,
    RiskControlledMomentumStrategy,
)
from strategy_research.runner import run_gross_and_net  # noqa: E402
from strategy_research.trend_volatility import TrendVolatilityParameters, TrendVolatilityStrategy  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4}
_BENCHMARK_ID = "SPY_TOTAL_RETURN_REAL"


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _perf_dict(perf) -> dict:
    return asdict(perf)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="PILOT_UNIVERSE")
    parser.add_argument("--start", required=True, type=_parse_date)
    parser.add_argument("--end", required=True, type=_parse_date)
    parser.add_argument("--db-path", required=True, type=Path, help="Path to the DuckDB catalog scripts/ingest_real_market_data.py already populated")
    parser.add_argument("--initial-capital", type=float, default=10_000.0, help="Matches PAPER_CAPITAL_USD (broker.paper.us_longterm_config), not a currency-converted figure")
    parser.add_argument("--report-out", type=Path, default=None)
    args = parser.parse_args()

    universe = _UNIVERSES[args.universe]
    security_ids = list(universe.symbol_ids)
    report_path = args.report_out or (args.db_path / "first_real_strategy_evaluation.json")

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBDataRepository(engine, calendars={"US_EQUITY": US_EQUITY_NYSE})

    try:
        # -- Build the real SPY TOTAL_RETURN benchmark, for the first
        # time in this project's history, from whatever real SPY bars +
        # corporate actions are already in the catalog. If SPY was
        # never ingested (or has no bars in this window), benchmark_id
        # stays None -- BENCHMARK_UNAVAILABLE, never a fabricated
        # benchmark (ADR-0026, unchanged).
        spy_bars = repository.get_bars(BENCHMARK_SYMBOL, args.start, args.end, as_of_time=args.end)
        spy_actions = repository.get_corporate_actions(BENCHMARK_SYMBOL, args.start, args.end, as_of_time=args.end)
        benchmark_id = None
        if spy_bars:
            benchmark_points = build_total_return_benchmark_points(
                _BENCHMARK_ID, spy_bars, spy_actions, as_of_time=args.end,
            )
            for point in benchmark_points:
                repository.add_benchmark_point(point)
            benchmark_id = _BENCHMARK_ID if benchmark_points else None

        log = ResearchLog(
            selection_procedure=(
                "Phase 24 first-real-data pass: one default parameter set per "
                "candidate (no grid search), run once over the full ingested "
                "window -- a single-window result with no train/validation/test "
                "split or walk-forward re-test, so it cannot itself justify "
                "PROMISING_CANDIDATE (instruction section 19)."
            )
        )

        strategy_specs = [
            ("buy_and_hold", "reference baseline, not alpha (Phase 22)", lambda: BuyAndHoldStrategy(security_ids)),
            ("long_term_momentum", "cross-sectional trailing-return momentum (see src/strategy_research/long_term_momentum.py)", lambda: LongTermMomentumStrategy(security_ids, LongTermMomentumParameters())),
            ("trend_volatility", "trend + realized-volatility filter (see src/strategy_research/trend_volatility.py)", lambda: TrendVolatilityStrategy(security_ids, TrendVolatilityParameters())),
            ("risk_controlled_momentum", "momentum + inverse-vol sizing + position cap (see src/strategy_research/risk_controlled_momentum.py)", lambda: RiskControlledMomentumStrategy(security_ids, RiskControlledMomentumParameters())),
        ]

        report = {
            "note": (
                "REAL market data (Tiingo primary/Stooq fallback, as actually "
                "ingested by scripts/ingest_real_market_data.py). This is NOT "
                "synthetic. A single evaluation window; no walk-forward, no "
                "train/validation/test split applied yet. No candidate below "
                "is classified PROMISING_CANDIDATE or REJECTED -- see "
                "'classification' in each entry."
            ),
            "universe": universe.name,
            "universe_version": universe.version,
            "security_ids": security_ids,
            "start": args.start.isoformat(),
            "end": args.end.isoformat(),
            "initial_capital": args.initial_capital,
            "benchmark_id": benchmark_id,
            "benchmark_status": "REAL_TOTAL_RETURN" if benchmark_id else "BENCHMARK_UNAVAILABLE",
            "results": {},
        }

        print(f"Benchmark: {report['benchmark_status']} ({benchmark_id})")
        print()

        for name, hypothesis, factory in strategy_specs:
            result = run_gross_and_net(
                repository, factory, security_ids,
                start_date=args.start.date(), end_date=args.end.date(),
                initial_capital=args.initial_capital, benchmark_id=benchmark_id,
            )
            gross_perf, net_perf = result.gross.performance, result.net.performance
            report["results"][name] = {
                "hypothesis": hypothesis,
                "gross": _perf_dict(gross_perf),
                "net": _perf_dict(net_perf),
                "num_trades_gross": len(result.gross.fills),
                "num_trades_net": len(result.net.fills),
                "classification": CandidateClassification.INCONCLUSIVE.value,
            }
            log.record(
                CandidateEvaluation(
                    strategy_name=name, strategy_version=getattr(factory(), "version", name),
                    hypothesis=hypothesis, parameters={},
                    train_period=(args.start.isoformat(), args.end.isoformat()),
                    validation_period=(), test_period=None,
                    criteria=PromisingCriteria(), classification=CandidateClassification.INCONCLUSIVE,
                    notes=("single-window real-data run, no train/val/test split or walk-forward yet",),
                )
            )
            print(f"{name}:")
            print(f"  gross: cumret={gross_perf.cumulative_return:+.2%} cagr={gross_perf.cagr:+.2%} sharpe={gross_perf.sharpe_ratio:.2f} maxdd={gross_perf.max_drawdown:+.2%} trades={len(result.gross.fills)}")
            print(f"  net:   cumret={net_perf.cumulative_return:+.2%} cagr={net_perf.cagr:+.2%} sharpe={net_perf.sharpe_ratio:.2f} maxdd={net_perf.max_drawdown:+.2%} trades={len(result.net.fills)} cost={net_perf.total_transaction_cost:.2f}")
            if net_perf.excess_return is not None:
                print(f"  net vs benchmark: excess_return={net_perf.excess_return:+.2%}")
            print()

        report["research_log_summary"] = log.summary()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, default=str))
        print(f"Full report written to: {report_path}")
        return 0
    finally:
        engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
