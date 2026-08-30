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
model, or any of the four original strategy candidates:

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

Add `--fundamentals-db-path ./data/fundamentals_data` (populated by
`scripts/ingest_fundamentals_data.py`, ADR-0042) to additionally
include the `leverage` fundamentals-based candidate
(`src/strategy_research/leverage_strategy.py`) in the run -- omitted
entirely, with every other candidate unaffected, when this flag is not
passed.

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

from backtest.contribution import compute_contribution_report_from_fills  # noqa: E402
from backtest.strategy import BuyAndHoldStrategy  # noqa: E402
from backtest.total_return import build_total_return_benchmark_points  # noqa: E402
from data_infra.calendar import US_EQUITY  # noqa: E402
from data_infra.universe import BENCHMARK_SYMBOL, PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE2  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.fundamentals_repository import DuckDBFundamentalsRepository  # noqa: E402

from strategy_research.classification import (  # noqa: E402
    CandidateClassification,
    CandidateEvaluation,
    PromisingCriteria,
)
from strategy_research.evidence import assess_pbo_dsr_applicability, classify_evidence_level  # noqa: E402
from strategy_research.pbo_dsr import compute_dsr_for_all_candidates, compute_pbo  # noqa: E402
from strategy_research.leverage_strategy import LeverageParameters, LeverageStrategy  # noqa: E402
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

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE2}
# Every real provider this project has ever integrated
# (src/data_infra/providers/tiingo.py, stooq.py) stamps exactly this
# source name onto Provenance.source -- used by the Phase 28
# REAL-provenance-plausibility check below.
_KNOWN_REAL_PROVIDER_SOURCES = {"tiingo", "stooq"}
_BENCHMARK_ID = "SPY_TOTAL_RETURN_REAL"


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _perf_dict(perf) -> dict:
    return asdict(perf)


def _concentration_dict(report) -> dict:
    return asdict(report)


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
    parser.add_argument(
        "--fundamentals-db-path", type=Path, default=None,
        help=(
            "Path to the DuckDB catalog scripts/ingest_fundamentals_data.py already "
            "populated (ADR-0042). Optional -- when omitted, the 'leverage' fundamentals-"
            "based candidate (src/strategy_research/leverage_strategy.py) is skipped "
            "entirely and every other candidate runs exactly as before this flag existed."
        ),
    )
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
    fundamentals_engine = None
    fundamentals_repository = None
    if args.fundamentals_db_path is not None:
        fundamentals_engine = StorageEngine(StorageConfig(root_dir=args.fundamentals_db_path))
        fundamentals_repository = DuckDBFundamentalsRepository(fundamentals_engine)

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
                # A run WITH --fundamentals-db-path adds the leverage
                # candidate and changes the PBO/DSR applicability count --
                # a materially different report from an otherwise-identical
                # configuration without it. Without this field the two
                # would collide on the same experiment_id, violating the
                # "different configuration always yields a different one"
                # contract documented above.
                "fundamentals_included": fundamentals_repository is not None,
            }
        )[:16]

        # data_version: reflects only what the repository actually
        # contains for this universe+window at run time (per-symbol bar
        # and corporate-action counts, plus SPY's own), same construction
        # as scripts/ingest_real_market_data.py's own content_checksum --
        # a real re-ingestion that adds new content changes this value;
        # an unchanged catalog re-run produces the identical value.
        bars_by_symbol = {
            sid: repository.get_bars(sid, args.start, args.end, as_of_time=args.end)
            for sid in sorted(security_ids)
        }
        # Last available close per symbol -- used only as `final_prices`
        # for the held-out TEST's concentration/contribution report
        # below (backtest.contribution), to value any still-open
        # position at the end of that period. Not used anywhere else.
        final_prices = {
            sid: (bars[-1].adjusted_close or bars[-1].close)
            for sid, bars in bars_by_symbol.items() if bars
        }
        # When fundamentals are included, `leverage`'s report content
        # depends on the fundamentals catalog's own contents too (not
        # just price bars) -- a re-ingestion that adds new fundamentals
        # records for this universe must change data_version the same
        # way a price re-ingestion already does, per this block's own
        # "reflects only what the repository actually contains" contract.
        per_symbol_fundamentals_counts = None
        if fundamentals_repository is not None:
            universe_ids = set(security_ids)
            per_symbol_fundamentals_counts = {}
            for record in fundamentals_repository.all_fundamentals():
                if record.security_id in universe_ids:
                    per_symbol_fundamentals_counts[record.security_id] = (
                        per_symbol_fundamentals_counts.get(record.security_id, 0) + 1
                    )
        data_version = compute_data_version(
            {
                "security_ids": sorted(security_ids) + [BENCHMARK_SYMBOL],
                "overall_start": args.start.isoformat(), "overall_end": args.end.isoformat(),
                "per_symbol_bar_counts": {sid: len(bars) for sid, bars in bars_by_symbol.items()},
                "benchmark_bar_count": len(spy_bars),
                "per_symbol_fundamentals_counts": per_symbol_fundamentals_counts,
            }
        )

        # Phase 28 (instruction section 5, items B/C): --data-status REAL
        # is the caller's own claim -- this project's fail-closed
        # discipline (never trust an unverified claim about what data
        # actually is) means that claim must be cross-checked against
        # the data's own recorded provenance, not simply trusted. Every
        # real provider this project has ever integrated stamps a known
        # source name (Tiingo/Stooq); synthetic/test fixtures use a
        # different one (e.g. backtest_helpers' "test_source",
        # MockDataProvider's caller-supplied name). A REAL run whose
        # bars carry an unrecognized source is refused outright rather
        # than silently producing a report that says REAL underneath
        # data that was never actually real.
        if is_real_data:
            all_sources = {
                bar.provenance.source
                for bars in bars_by_symbol.values() for bar in bars
            } | {bar.provenance.source for bar in spy_bars}
            unexpected_sources = all_sources - _KNOWN_REAL_PROVIDER_SOURCES
            if unexpected_sources:
                print(
                    "ERROR: --data-status REAL was passed, but the catalog's bars carry "
                    f"provenance.source value(s) {sorted(unexpected_sources)!r} outside the "
                    f"known real-provider allowlist {sorted(_KNOWN_REAL_PROVIDER_SOURCES)!r}. "
                    "Refusing to proceed rather than silently label non-real data as REAL. "
                    "If this is genuinely real data from a new provider, add its source name "
                    "to _KNOWN_REAL_PROVIDER_SOURCES in this script.",
                    file=sys.stderr,
                )
                return 1

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
        if fundamentals_repository is not None:
            # Only included when --fundamentals-db-path is supplied
            # (ADR-0042 Decision 12/13) -- the first fundamentals-based
            # candidate, added specifically to put leverage_score's real
            # Signal IC lead (mean_ic=+0.0782, the strongest of 7
            # hypotheses tested) through the same walk-forward/PBO/DSR
            # rigor every other candidate here already went through,
            # rather than trusting the raw IC number on its own.
            strategy_specs.append((
                "leverage",
                "low-leverage quality/safety factor, fundamentals-based (see src/strategy_research/leverage_strategy.py)",
                lambda: LeverageStrategy(security_ids, fundamentals_repository, LeverageParameters()),
            ))

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
        aggregates_by_name = {}
        held_out_by_name = {}

        # Pass 1: run every strategy's walk-forward + held-out TEST and
        # record it in the ResearchLog. Evidence classification is
        # deliberately deferred to pass 2 -- it needs to know whether
        # PBO/DSR is applicable ACROSS all candidates first (a bug this
        # fix corrects: `assess_pbo_dsr_applicability` was previously
        # computed only after this loop and its result was never fed
        # back into `classify_evidence_level`, so `pbo_dsr_applied` was
        # always False here regardless of what applicability actually
        # found -- every real run's evidence was silently capped at
        # ROBUSTNESS_PENDING even when the trigger condition had fired).
        for name, hypothesis, factory in strategy_specs:
            aggregate = run_walk_forward_evaluation(
                repository, factory, security_ids,
                overall_start=split.train_start, overall_end=split.validation_end,
                train_window_months=args.train_window_months, test_window_months=args.test_window_months,
                step_months=args.step_months, initial_capital=args.initial_capital, benchmark_id=benchmark_id,
                regime_subject_id=BENCHMARK_SYMBOL,
            )
            fold_counts_by_strategy[name] = aggregate.fold_count
            aggregates_by_name[name] = aggregate

            held_out_test = None
            if split.test_end > split.test_start:
                held_out_result = run_gross_and_net(
                    repository, factory, security_ids,
                    start_date=split.test_start.date(), end_date=split.test_end.date(),
                    initial_capital=args.initial_capital, benchmark_id=benchmark_id,
                )
                concentration = compute_contribution_report_from_fills(
                    held_out_result.net.fills, args.initial_capital, final_prices
                )
                held_out_test = {
                    "gross": _perf_dict(held_out_result.gross.performance),
                    "net": _perf_dict(held_out_result.net.performance),
                    "num_trades_net": len(held_out_result.net.fills),
                    "concentration": _concentration_dict(concentration),
                }
            held_out_by_name[name] = held_out_test

            log.record(
                CandidateEvaluation(
                    strategy_name=name, strategy_version=getattr(factory(), "version", name),
                    hypothesis=hypothesis, parameters={},
                    train_period=(split.train_start.isoformat(), split.validation_end.isoformat()),
                    validation_period=(), test_period=(split.test_start.isoformat(), split.test_end.isoformat()),
                    criteria=PromisingCriteria(), classification=CandidateClassification.INCONCLUSIVE,
                    notes=(f"walk-forward folds={aggregate.fold_count}",),
                )
            )

        applicability = assess_pbo_dsr_applicability(log, real_fold_counts_by_candidate=fold_counts_by_strategy)
        report["pbo_dsr_applicability"] = {
            "applicable": applicability.applicable, "reason": applicability.reason,
            "candidate_count": applicability.candidate_count,
            "parameter_combination_count": applicability.parameter_combination_count,
            "min_real_out_of_sample_folds_across_candidates": applicability.min_real_out_of_sample_folds_across_candidates,
        }
        print(f"PBO/DSR applicability: {applicability.applicable} -- {applicability.reason}")

        # Actual PBO/DSR computation (strategy_research.pbo_dsr), only
        # once the applicability trigger has genuinely fired against
        # REAL data -- never computed against synthetic fixtures (a
        # synthetic PBO/DSR number would answer a question about noise
        # this project never asks; is_real_data already gates every
        # other evidence claim the same way).
        pbo_result = None
        dsr_by_name: dict = {}
        if applicability.applicable and is_real_data:
            fold_returns_by_candidate = {
                name: [fold.result.net.performance.cumulative_return for fold in agg.folds]
                for name, agg in aggregates_by_name.items()
            }
            try:
                pbo_result = compute_pbo(fold_returns_by_candidate)
                dsr_by_name = compute_dsr_for_all_candidates(fold_returns_by_candidate)
                report["pbo_dsr_result"] = {
                    "pbo_probability": pbo_result.probability,
                    "num_combinations": pbo_result.num_combinations,
                    "num_groups": pbo_result.num_groups,
                    "deflated_sharpe_by_candidate": {n: r.deflated_sharpe_ratio for n, r in dsr_by_name.items()},
                }
                print(
                    f"PBO (Probability of Backtest Overfitting): {pbo_result.probability:.2%} "
                    f"across {pbo_result.num_combinations} CSCV splits"
                )
                for n in sorted(dsr_by_name):
                    r = dsr_by_name[n]
                    print(f"  {n}: Deflated Sharpe Ratio={r.deflated_sharpe_ratio:.4f} (observed fold Sharpe={r.observed_sharpe:.3f})")
            except ValueError as exc:
                print(f"PBO/DSR computation skipped: {exc}", file=sys.stderr)
        print()

        # Pass 2: classify evidence (now informed by real PBO/DSR values
        # when they were actually computed above) and print per-strategy
        # results.
        for name, hypothesis, _factory in strategy_specs:
            aggregate = aggregates_by_name[name]
            held_out_test = held_out_by_name[name]
            pbo_probability = pbo_result.probability if pbo_result is not None else None
            deflated_sharpe_ratio = dsr_by_name[name].deflated_sharpe_ratio if name in dsr_by_name else None

            evidence = classify_evidence_level(
                aggregate, is_real_data=is_real_data, pbo_dsr_applied=pbo_result is not None,
                pbo_probability=pbo_probability, deflated_sharpe_ratio=deflated_sharpe_ratio,
            )

            report["results"][name] = {
                "hypothesis": hypothesis,
                "walk_forward": _aggregate_dict(aggregate),
                "held_out_test": held_out_test,
                "evidence_assessment": {
                    "level": evidence.level.value, "reason": evidence.reason,
                    "fold_count": evidence.fold_count, "positive_fold_ratio": evidence.positive_fold_ratio,
                    "distinct_known_regimes": evidence.distinct_known_regimes,
                    "pbo_probability": pbo_probability, "deflated_sharpe_ratio": deflated_sharpe_ratio,
                },
                "classification": CandidateClassification.INCONCLUSIVE.value,
            }

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

        report["research_log_summary"] = log.summary()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, default=str))
        print(f"\nFull report written to: {report_path}")
        return 0
    finally:
        engine.close()
        if fundamentals_engine is not None:
            fundamentals_engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
