#!/usr/bin/env python3
"""Long-horizon real-data strategy validation CLI (Phase 25, extended
Phase 26 with `experiment_id`/`data_version` reproducibility fields,
Phase 27 with a required `--data-status` flag).

See docs/decisions/ADR-0031-long-horizon-walk-forward-validation.md and
docs/research/STRATEGY-VALIDATION-REPORT.md.

Phase 27 fix: `--data-status {REAL,SYNTHETIC}` is now a REQUIRED
argument. Before this, `classify_evidence_level`'s `is_real_data`
argument was hardcoded `True` regardless of what the `--db-path`
catalog actually held -- a synthetic dry run (the only kind this
sandboxed session could ever run against, network access has been
BLOCKED since Phase 20) would have silently produced an
`EvidenceAssessment` that looked structurally identical to a real one,
violating this project's own "never let synthetic look like real"
discipline at exactly the layer meant to enforce it. `--data-status`
now gates `is_real_data` directly, is folded into `experiment_id` (so a
REAL and a SYNTHETIC run of an otherwise-identical configuration can
never collide into the same id), and is written into the JSON report's
top-level `data_status` field and its `note`/`benchmark_status` text.

Phase 26 addition: the JSON report now carries `experiment_id` (a
deterministic hash of the run's own configuration -- universe, date
range, split fractions, walk-forward window sizes, initial capital;
never a wall-clock value, so the identical configuration always
produces the identical id) and `data_version` (a hash of what the
repository actually contains for this universe+window at run time --
per-symbol/benchmark bar counts). Both use
`data_infra.versioning.compute_data_version`, the same function
`scripts/ingest_real_market_data.py` already uses for its own content
checksum -- re-running this script against an unchanged catalog
reproduces the identical `data_version`; a real re-ingestion that adds
new content changes it.

This script is the Phase 25 successor to
`scripts/run_first_real_strategy_evaluation.py` (Phase 24's
single-window, no-split real-data run). It adds, without changing a
single line of `backtest/engine.py`, `backtest/strategy.py`, any cost
model, or any of the four existing strategy candidates:

1. A chronological TRAIN / VALIDATION / TEST split of the real ingested
   window (`strategy_research.splits.build_chronological_split`,
   Phase 23, unmodified). TRAIN+VALIDATION is the "developmental" region
   this script is free to look at repeatedly (that is what the
   walk-forward folds below run across); TEST is reserved and evaluated
   here exactly ONCE, as a single held-out window, never re-opened after
   this script has run (instruction section 24 -- "TEST 구간은 마지막에
   딱 한 번만 사용한다").
2. Walk-forward evaluation across the TRAIN+VALIDATION region
   (`strategy_research.walk_forward_evaluation.run_walk_forward_evaluation`,
   Phase 25, unmodified) -- multiple rolling out-of-sample folds, not a
   single lucky window.
3. Evidence-strength grading of the walk-forward results
   (`strategy_research.evidence.classify_evidence_level`, Phase 25,
   unmodified) and a PBO/Deflated-Sharpe applicability check
   (`strategy_research.evidence.assess_pbo_dsr_applicability`) -- this
   script deliberately never computes PBO/DSR itself (that computation
   is still deferred pending an explicit human decision to adopt it,
   per the existing `docs/research/walk-forward-pbo-deflated-sharpe.md`
   DECISION REQUIRED framing) -- it only reports whether this run's own
   real fold counts would already justify doing so.

**RULE 0.8 (parameters fixed before evaluation, never re-tuned
afterward)**: every strategy below uses its existing default
`*Parameters` dataclass, exactly as `run_first_real_strategy_evaluation.py`
already did -- no grid search, no parameter sweep, and nothing in this
script reads its own prior output before choosing what to run next.
`--train-window-months`/`--test-window-months`/`--step-months` default
to values chosen before this script was ever run against real data (see
the argparse defaults below) and are not adjusted based on any result.

**This script still cannot itself declare "validated alpha."** The
highest `EvidenceLevel` `classify_evidence_level` can return is
`CANDIDATE`; `VALIDATED` requires an explicit human review this
automated script does not perform (see `strategy_research.evidence`).

Usage (run in an environment with a real DuckDB catalog already
populated by scripts/ingest_real_market_data.py):
    python3 scripts/run_long_horizon_validation.py \\
        --universe PILOT_UNIVERSE \\
        --start 2023-01-02 --end 2024-12-31 \\
        --db-path ./data/real_market_data \\
        --data-status REAL

Never executed by this repository's own automated test suite (it reads
real, already-ingested data from a path the test suite never has, and
its runtime scales with how much real history has actually been
ingested).
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
from data_infra.calendar import US_EQUITY  # noqa: E402
from data_infra.universe import BENCHMARK_SYMBOL, PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE1  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402

from strategy_research.classification import (  # noqa: E402
    CandidateClassification,
    CandidateEvaluation,
    PromisingCriteria,
)
from strategy_research.evidence import assess_pbo_dsr_applicability, classify_evidence_level  # noqa: E402
from strategy_research.long_term_momentum import LongTermMomentumParameters, LongTermMomentumStrategy  # noqa: E402
from strategy_research.research_log import ResearchLog  # noqa: E402
from strategy_research.risk_controlled_momentum import (  # noqa: E402
    RiskControlledMomentumParameters,
    RiskControlledMomentumStrategy,
)
from strategy_research.runner import run_gross_and_net  # noqa: E402
from strategy_research.splits import build_chronological_split  # noqa: E402
from strategy_research.trend_volatility import TrendVolatilityParameters, TrendVolatilityStrategy  # noqa: E402
from strategy_research.walk_forward_evaluation import run_walk_forward_evaluation  # noqa: E402

from data_infra.versioning import compute_data_version  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE1}
_BENCHMARK_ID = "SPY_TOTAL_RETURN_REAL"


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _perf_dict(perf) -> dict:
    return asdict(perf)


def _fold_dict(fold) -> dict:
    return {
        "fold_index": fold.fold_index,
        "train_start": fold.train_start.isoformat(),
        "train_end": fold.train_end.isoformat(),
        "test_start": fold.test_start.isoformat(),
        "test_end": fold.test_end.isoformat(),
        "regime_trend_state": fold.regime_trend_state,
        "gross": _perf_dict(fold.result.gross.performance),
        "net": _perf_dict(fold.result.net.performance),
        "num_trades_net": len(fold.result.net.fills),
    }


def _aggregate_dict(aggregate) -> dict:
    return {
        "strategy_name": aggregate.strategy_name,
        "train_window_months": aggregate.train_window_months,
        "test_window_months": aggregate.test_window_months,
        "step_months": aggregate.step_months,
        "fold_count": aggregate.fold_count,
        "positive_net_return_folds": aggregate.positive_net_return_folds,
        "median_net_cumulative_return": aggregate.median_net_cumulative_return,
        "median_net_sharpe": aggregate.median_net_sharpe,
        "stdev_net_cumulative_return": aggregate.stdev_net_cumulative_return,
        "worst_max_drawdown": aggregate.worst_max_drawdown,
        "worst_fold_index": aggregate.worst_fold_index,
        "best_net_cumulative_return": aggregate.best_net_cumulative_return,
        "best_fold_index": aggregate.best_fold_index,
        "regime_breakdown": aggregate.regime_breakdown,
        "folds": [_fold_dict(f) for f in aggregate.folds],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="PILOT_UNIVERSE")
    parser.add_argument("--start", required=True, type=_parse_date)
    parser.add_argument("--end", required=True, type=_parse_date)
    parser.add_argument("--db-path", required=True, type=Path, help="Path to the DuckDB catalog scripts/ingest_real_market_data.py already populated")
    parser.add_argument("--initial-capital", type=float, default=10_000.0, help="Matches PAPER_CAPITAL_USD (broker.paper.us_longterm_config), not a currency-converted figure")
    parser.add_argument("--train-fraction", type=float, default=0.6, help="Chronological split: fraction of [start,end] reserved for TRAIN (fixed before this script's first real-data run, never tuned against a result)")
    parser.add_argument("--validation-fraction", type=float, default=0.2, help="Chronological split: fraction reserved for VALIDATION; remaining fraction is the held-out TEST window")
    parser.add_argument("--train-window-months", type=int, default=6, help="Walk-forward fold TRAIN length, run across the TRAIN+VALIDATION region only")
    parser.add_argument("--test-window-months", type=int, default=2, help="Walk-forward fold TEST length")
    parser.add_argument("--step-months", type=int, default=2, help="Walk-forward rolling step")
    parser.add_argument("--report-out", type=Path, default=None)
    parser.add_argument(
        "--data-status", choices=("REAL", "SYNTHETIC"), required=True,
        help=(
            "REAL only if --db-path holds real, provider-ingested data "
            "(scripts/ingest_real_market_data.py). SYNTHETIC for a "
            "pipeline-correctness dry run against fixture data -- caps "
            "every strategy's EvidenceLevel at INSUFFICIENT_EVIDENCE "
            "regardless of how the numbers look (Phase 27 fix: this used "
            "to be hardcoded to REAL-equivalent behavior regardless of "
            "what data the catalog actually held -- see "
            "tests/strategy_research/test_run_long_horizon_validation_wiring.py)."
        ),
    )
    args = parser.parse_args()
    is_real_data = args.data_status == "REAL"

    universe = _UNIVERSES[args.universe]
    security_ids = list(universe.symbol_ids)
    report_path = args.report_out or (args.db_path / "long_horizon_validation.json")

    split = build_chronological_split(
        args.start, args.end, train_fraction=args.train_fraction, validation_fraction=args.validation_fraction,
    )

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBDataRepository(engine, calendars={"US_EQUITY": US_EQUITY})

    try:
        # Real SPY TOTAL_RETURN benchmark, same construction as Phase
        # 24's script -- BENCHMARK_UNAVAILABLE (never fabricated) if SPY
        # was never ingested for this window (ADR-0026, unchanged).
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

        # experiment_id: deterministic from caller-supplied run
        # configuration only (never datetime.now()/utcnow() -- rule
        # 0-11) -- the SAME configuration run twice always yields the
        # SAME experiment_id (Phase 26 section 22/21 -- reproducibility
        # tracking), a different configuration always yields a
        # different one.
        experiment_id = compute_data_version(
            {
                "data_status": args.data_status,  # REAL and SYNTHETIC runs of an
                # otherwise-identical configuration must never collide into the
                # same experiment_id (section 27's namespace-separation requirement).
                "universe_name": universe.name, "universe_version": universe.version,
                "overall_start": args.start.isoformat(), "overall_end": args.end.isoformat(),
                "train_fraction": args.train_fraction, "validation_fraction": args.validation_fraction,
                "train_window_months": args.train_window_months, "test_window_months": args.test_window_months,
                "step_months": args.step_months, "initial_capital": args.initial_capital,
            }
        )[:16]

        # data_version: reflects only what the repository actually
        # contains for this universe+window at run time (per-symbol bar
        # and corporate-action counts, plus SPY's own), same construction
        # as scripts/ingest_real_market_data.py's own content_checksum --
        # a real re-ingestion that adds new content changes this value;
        # an unchanged catalog re-run produces the identical value.
        data_version = compute_data_version(
            {
                "security_ids": sorted(security_ids) + [BENCHMARK_SYMBOL],
                "overall_start": args.start.isoformat(), "overall_end": args.end.isoformat(),
                "per_symbol_bar_counts": {
                    sid: len(repository.get_bars(sid, args.start, args.end, as_of_time=args.end))
                    for sid in sorted(security_ids)
                },
                "benchmark_bar_count": len(spy_bars),
            }
        )

        log = ResearchLog(
            selection_procedure=(
                "Phase 25 long-horizon pass: one default parameter set per "
                "candidate (no grid search, no re-tuning after seeing any "
                "result -- RULE 0.8), walk-forward folds across TRAIN+VALIDATION "
                "only, TEST window evaluated exactly once at the end. "
                "CandidateClassification stays INCONCLUSIVE for every entry here "
                "-- EvidenceLevel (see 'evidence_assessment' per strategy) is "
                "this phase's authoritative strength-of-evidence signal, not "
                "this legacy single-run label."
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
                (
                    "REAL market data (Tiingo primary/Stooq fallback, as actually "
                    "ingested by scripts/ingest_real_market_data.py). This is NOT "
                    "synthetic."
                    if is_real_data else
                    "SYNTHETIC data (--data-status SYNTHETIC was passed explicitly). "
                    "This is a pipeline-correctness dry run, NOT a real-market-data "
                    "validation -- every EvidenceLevel below is capped at "
                    "INSUFFICIENT_EVIDENCE regardless of how the numbers look."
                ) + (
                    " Walk-forward folds run across the TRAIN+VALIDATION "
                    "region only; 'held_out_test' is the TEST region, evaluated "
                    "exactly once. No candidate below is classified "
                    "PROMISING_CANDIDATE/REJECTED, and no EvidenceLevel here is or "
                    "can be VALIDATED -- see 'evidence_assessment' per strategy."
                )
            ),
            "data_status": args.data_status,
            "experiment_id": experiment_id,
            "data_version": data_version,
            "universe": universe.name,
            "universe_version": universe.version,
            "security_ids": security_ids,
            "overall_start": args.start.isoformat(),
            "overall_end": args.end.isoformat(),
            "chronological_split": {
                "train_start": split.train_start.isoformat(), "train_end": split.train_end.isoformat(),
                "validation_start": split.validation_start.isoformat(), "validation_end": split.validation_end.isoformat(),
                "test_start": split.test_start.isoformat(), "test_end": split.test_end.isoformat(),
            },
            "walk_forward_config": {
                "train_window_months": args.train_window_months,
                "test_window_months": args.test_window_months,
                "step_months": args.step_months,
                "region": "TRAIN+VALIDATION only (chronological_split.train_start .. validation_end)",
            },
            "initial_capital": args.initial_capital,
            "benchmark_id": benchmark_id,
            "benchmark_status": (
                ("REAL" if is_real_data else "SYNTHETIC") + "_TOTAL_RETURN"
                if benchmark_id else "BENCHMARK_UNAVAILABLE"
            ),
            "results": {},
        }

        print(f"Data status: {args.data_status}")
        print(f"Experiment ID: {experiment_id}")
        print(f"Data version: {data_version}")
        print(f"Benchmark: {report['benchmark_status']} ({benchmark_id})")
        print(f"Chronological split: TRAIN [{split.train_start.date()} .. {split.train_end.date()}) "
              f"VALIDATION [{split.validation_start.date()} .. {split.validation_end.date()}) "
              f"TEST [{split.test_start.date()} .. {split.test_end.date()}]")
        print()

        fold_counts_by_strategy: dict[str, int] = {}

        for name, hypothesis, factory in strategy_specs:
            aggregate = run_walk_forward_evaluation(
                repository, factory, security_ids,
                overall_start=split.train_start, overall_end=split.validation_end,
                train_window_months=args.train_window_months, test_window_months=args.test_window_months,
                step_months=args.step_months, initial_capital=args.initial_capital, benchmark_id=benchmark_id,
                regime_subject_id=BENCHMARK_SYMBOL,
            )
            fold_counts_by_strategy[name] = aggregate.fold_count

            held_out_test = None
            if split.test_end > split.test_start:
                held_out_result = run_gross_and_net(
                    repository, factory, security_ids,
                    start_date=split.test_start.date(), end_date=split.test_end.date(),
                    initial_capital=args.initial_capital, benchmark_id=benchmark_id,
                )
                held_out_test = {
                    "gross": _perf_dict(held_out_result.gross.performance),
                    "net": _perf_dict(held_out_result.net.performance),
                    "num_trades_net": len(held_out_result.net.fills),
                }

            evidence = classify_evidence_level(aggregate, is_real_data=is_real_data, pbo_dsr_applied=False)

            report["results"][name] = {
                "hypothesis": hypothesis,
                "walk_forward": _aggregate_dict(aggregate),
                "held_out_test": held_out_test,
                "evidence_assessment": {
                    "level": evidence.level.value, "reason": evidence.reason,
                    "fold_count": evidence.fold_count, "positive_fold_ratio": evidence.positive_fold_ratio,
                    "distinct_known_regimes": evidence.distinct_known_regimes,
                },
                "classification": CandidateClassification.INCONCLUSIVE.value,
            }
            log.record(
                CandidateEvaluation(
                    strategy_name=name, strategy_version=getattr(factory(), "version", name),
                    hypothesis=hypothesis, parameters={},
                    train_period=(split.train_start.isoformat(), split.validation_end.isoformat()),
                    validation_period=(), test_period=(split.test_start.isoformat(), split.test_end.isoformat()),
                    criteria=PromisingCriteria(), classification=CandidateClassification.INCONCLUSIVE,
                    notes=(f"walk-forward folds={aggregate.fold_count}, evidence_level={evidence.level.value}",),
                )
            )

            print(f"{name}: evidence={evidence.level.value} folds={aggregate.fold_count}")
            print(f"  {evidence.reason}")
            if aggregate.fold_count:
                print(f"  walk-forward median net cumret={aggregate.median_net_cumulative_return:+.2%} "
                      f"positive_folds={aggregate.positive_net_return_folds}/{aggregate.fold_count} "
                      f"regimes={aggregate.regime_breakdown}")
            if held_out_test is not None:
                hnet = held_out_test["net"]
                print(f"  held-out TEST net cumret={hnet['cumulative_return']:+.2%} sharpe={hnet['sharpe_ratio']:.2f} trades={held_out_test['num_trades_net']}")
            print()

        applicability = assess_pbo_dsr_applicability(log, real_fold_counts_by_candidate=fold_counts_by_strategy)
        report["pbo_dsr_applicability"] = {
            "applicable": applicability.applicable, "reason": applicability.reason,
            "candidate_count": applicability.candidate_count,
            "parameter_combination_count": applicability.parameter_combination_count,
            "min_real_out_of_sample_folds_across_candidates": applicability.min_real_out_of_sample_folds_across_candidates,
        }
        print(f"PBO/DSR applicability: {applicability.applicable} -- {applicability.reason}")

        report["research_log_summary"] = log.summary()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, default=str))
        print(f"\nFull report written to: {report_path}")
        return 0
    finally:
        engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
