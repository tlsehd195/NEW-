#!/usr/bin/env python3
"""Track A (Phase 32): does `TrendVolatilityStrategy._passes_filter`
(price > trailing moving average AND realized volatility <=
threshold) actually pick securities with better forward returns than
the ones it rejects?

`_passes_filter` is a boolean gate, not a continuous rank score, so
Spearman IC (`compute_signal_ic_from_catalog.py`) does not apply to
it -- this uses `strategy_research.signal_ic.bucket_return_analysis`
instead: at each rebalance date, split the universe into
filter-passing/filter-failing groups and compare their mean forward
returns. A positive, consistently-positive spread means the filter is
selecting real signal; a spread near zero (the same shape of finding
`compute_signal_ic_from_catalog.py --strategy long_term_momentum`
already produced for the shared momentum score) means it likely is not.

**TEST-1 protection**: identical guard to
`compute_signal_ic_from_catalog.py` -- same reasoning applies
verbatim (`_passes_filter`'s moving-average/volatility windows were
also corrected by ADR-0038), same default `--end`, same hard refusal
with no override flag.

Usage:
    python3 scripts/compute_filter_bucket_returns_from_catalog.py \\
        --db-path ./data/real_2010_latest \\
        --universe RESEARCH_UNIVERSE \\
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
from strategy_research.locked_windows import TEST_1, overlaps_any_locked_window  # noqa: E402
from strategy_research.signal_ic import bucket_return_analysis  # noqa: E402
from strategy_research.trend_volatility import TrendVolatilityParameters, TrendVolatilityStrategy  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE2}


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
    parser.add_argument("--start", required=True, type=str, help="YYYY-MM-DD")
    parser.add_argument(
        "--end", type=str, default=None,
        help="YYYY-MM-DD. Defaults to TEST_1.start; the script refuses to run past that (see module docstring).",
    )
    parser.add_argument("--step-months", type=int, default=1, help="Rebalance interval, matches TrendVolatilityStrategy's default")
    parser.add_argument("--horizon-days", type=int, default=30)
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
            "Refusing to compute filter bucket returns against an already-observed held-out TEST window "
            "with today's (possibly since-corrected) filter logic -- see this script's own module "
            "docstring. No override flag exists for this.",
            file=sys.stderr,
        )
        return 1

    universe = _UNIVERSES[args.universe]
    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBDataRepository(engine)

    strategy = TrendVolatilityStrategy(list(universe.symbol_ids), TrendVolatilityParameters())
    rebalance_dates = _rebalance_dates(start, end, args.step_months)

    summary = bucket_return_analysis(
        list(universe.symbol_ids), rebalance_dates, strategy._passes_filter, repository,
        horizon_days=args.horizon_days,
    )

    print(f"Filter bucket returns: trend_volatility over [{start.date()}, {end.date()}) ({len(rebalance_dates)} rebalance dates)")
    print(f"  dates_with_both_groups={summary.dates_with_both_groups}")
    if summary.mean_spread is None:
        print("  mean_spread=N/A (no date had both a passing and a failing security with a computable forward return)")
    else:
        print(f"  mean_passing_return={summary.mean_passing_return:.4f}")
        print(f"  mean_failing_return={summary.mean_failing_return:.4f}")
        print(f"  mean_spread={summary.mean_spread:.4f}")
        print(f"  positive_spread_ratio={summary.positive_spread_ratio:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
