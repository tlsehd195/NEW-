#!/usr/bin/env python3
"""Track A (Phase 32): computes real-data Signal IC (rank correlation
of a score against realized forward returns) for one of --
`long_term_momentum`/`risk_controlled_momentum`'s shared
`_momentum_score`, or the standalone `low_volatility_score` factor
(`strategy_research.factor_scores` -- a genuinely different,
independently pre-existing hypothesis, not a momentum variant, picked
specifically to avoid re-testing the same failed idea with cosmetic
changes) -- using `strategy_research.signal_ic.compute_ic_series`
against a live DuckDB catalog.

Why this needs a live catalog (unlike `analyze_long_horizon_result.py`,
which only reads a report JSON): IC requires re-scoring securities at
each rebalance date and reading their realized forward returns, which
means querying the actual price history, not just the report's summary
statistics.

**TEST-1 protection, not a suggestion**: this script REFUSES to run
(exit code 1, no partial output) if the requested `[--start, --end]`
range overlaps `strategy_research.locked_windows.TEST_1`. This is
deliberate and has no override flag. Signal IC computed with today's
(post-ADR-0038-fix) `_momentum_score` against the TEST-1 window would
answer "does the CORRECTED signal predict returns in the window we
already observed the UNCORRECTED strategies fail on" -- exactly the
post-hoc-tuning-via-TEST-reuse RULE 0.8 forbids, even though this
script computes a read-only diagnostic rather than changing anything.
Default `--end` is `TEST_1.start` for this reason -- the safe range is
the path of least resistance, not an opt-in.

Usage:
    python3 scripts/compute_signal_ic_from_catalog.py \\
        --db-path ./data/real_2010_latest \\
        --universe RESEARCH_UNIVERSE \\
        --strategy long_term_momentum \\
        --start 2010-01-01 \\
        [--end 2023-04-28]  # defaults to TEST_1.start; anything later is refused
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE2  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from strategy_research._dates import add_months  # noqa: E402
from strategy_research.factor_scores import low_volatility_score  # noqa: E402
from strategy_research.locked_windows import TEST_1, overlaps_any_locked_window  # noqa: E402
from strategy_research.long_term_momentum import LongTermMomentumParameters, LongTermMomentumStrategy  # noqa: E402
from strategy_research.risk_controlled_momentum import (  # noqa: E402
    RiskControlledMomentumParameters,
    RiskControlledMomentumStrategy,
)
from strategy_research.signal_ic import ScoreFn, compute_ic_series  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE2}

_MOMENTUM_STRATEGIES = {
    "long_term_momentum": (LongTermMomentumStrategy, LongTermMomentumParameters),
    "risk_controlled_momentum": (RiskControlledMomentumStrategy, RiskControlledMomentumParameters),
}
_SCORE_CHOICES = tuple(sorted(_MOMENTUM_STRATEGIES) + ["low_volatility"])


def _build_score_fn(name: str, symbol_ids: list[str]) -> ScoreFn:
    if name == "low_volatility":
        return low_volatility_score
    strategy_cls, params_cls = _MOMENTUM_STRATEGIES[name]
    return strategy_cls(symbol_ids, params_cls())._momentum_score


def _rebalance_dates(start: datetime, end: datetime, step_months: int) -> list[datetime]:
    dates = []
    current = start
    while current < end:
        dates.append(current)
        current = add_months(current, step_months)
    return dates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="RESEARCH_UNIVERSE")
    parser.add_argument("--strategy", choices=_SCORE_CHOICES, required=True)
    parser.add_argument("--start", required=True, type=str, help="YYYY-MM-DD")
    parser.add_argument(
        "--end", type=str, default=None,
        help="YYYY-MM-DD. Defaults to TEST_1.start (the walk-forward TRAIN+VALIDATION boundary) -- "
        "the script refuses to run past that unless you are certain you want to (see module docstring).",
    )
    parser.add_argument("--step-months", type=int, default=2, help="Rebalance interval, matches walk-forward test_window_months by default")
    parser.add_argument("--horizon-days", type=int, default=60)
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
            "Refusing to compute Signal IC against an already-observed held-out TEST window with today's "
            "(possibly since-corrected) signal logic -- see this script's own module docstring. "
            "No override flag exists for this.",
            file=sys.stderr,
        )
        return 1

    universe = _UNIVERSES[args.universe]
    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBDataRepository(engine)

    score_fn = _build_score_fn(args.strategy, list(universe.symbol_ids))
    rebalance_dates = _rebalance_dates(start, end, args.step_months)

    summary = compute_ic_series(
        list(universe.symbol_ids), rebalance_dates, score_fn, repository,
        horizon_days=args.horizon_days,
    )

    print(f"Signal IC: {args.strategy} over [{start.date()}, {end.date()}) ({len(rebalance_dates)} rebalance dates)")
    print(f"  observations={len(summary.observations)}")
    if summary.mean_ic is None:
        print("  mean_ic=N/A (no observations had >= 2 securities with both a score and a forward return)")
    else:
        print(f"  mean_ic={summary.mean_ic:.4f}")
        print(f"  ic_information_ratio={summary.ic_information_ratio}")
        print(f"  positive_ic_ratio={summary.positive_ic_ratio:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
