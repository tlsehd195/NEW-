#!/usr/bin/env python3
"""Computes real-data Signal IC for a fundamentals-based factor --
`roe`, `roa`, `net_margin`, `leverage` (all in `strategy_research.
factor_scores`, sharing the same `_fy_ratio` plumbing), or
`asset_growth` (a year-over-year change rather than a single-period
ratio -- Cooper, Gulen & Schill 2008's asset growth anomaly, ADR-0043
Decision 8) -- using
`strategy_research.signal_ic.compute_fundamentals_ic_series` against
two live DuckDB catalogs: the fundamentals catalog (ADR-0042,
`ingest_fundamentals_data.py`'s output) and the price catalog
(`ingest_real_market_data.py`'s output, needed for forward returns).
Mirrors `compute_signal_ic_from_catalog.py`'s structure and TEST-1
guard exactly, adapted for two repositories instead of one -- see that
script's own module docstring for the full "why a live catalog, why
TEST-1 is refused with no override" reasoning, which applies here
unchanged.

**TEST-1 protection, not a suggestion**: identical to
`compute_signal_ic_from_catalog.py` -- this script REFUSES to run if
`[--start, --end]` overlaps `strategy_research.locked_windows.TEST_1`,
with no override flag. Default `--end` is `TEST_1.start`.

Usage:
    python3 scripts/compute_fundamentals_ic_from_catalog.py \\
        --price-db-path ./data/real_2010_latest \\
        --fundamentals-db-path ./data/fundamentals_data \\
        --universe RESEARCH_UNIVERSE \\
        --score roe \\
        --start 2010-01-01 \\
        [--end 2023-04-28]  # defaults to TEST_1.start; anything later is refused
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE3  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.fundamentals_repository import DuckDBFundamentalsRepository  # noqa: E402
from strategy_research._dates import add_months  # noqa: E402
from strategy_research.factor_scores import (  # noqa: E402
    asset_growth_score,
    leverage_score,
    net_margin_score,
    roa_score,
    roe_score,
)
from strategy_research.locked_windows import TEST_1, overlaps_any_locked_window  # noqa: E402
from strategy_research.signal_ic import compute_fundamentals_ic_series  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE3}

_SCORES = {
    "roe": roe_score,
    "roa": roa_score,
    "net_margin": net_margin_score,
    "leverage": leverage_score,
    "asset_growth": asset_growth_score,
}


def _rebalance_dates(start: datetime, end: datetime, step_months: int) -> list[datetime]:
    dates = []
    current = start
    while current < end:
        dates.append(current)
        current = add_months(current, step_months)
    return dates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--price-db-path", required=True, type=Path, help="DuckDB catalog from ingest_real_market_data.py (forward returns)")
    parser.add_argument("--fundamentals-db-path", required=True, type=Path, help="DuckDB catalog from ingest_fundamentals_data.py (scores)")
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="RESEARCH_UNIVERSE")
    parser.add_argument("--score", choices=sorted(_SCORES), default="roe")
    parser.add_argument("--start", required=True, type=str, help="YYYY-MM-DD")
    parser.add_argument(
        "--end", type=str, default=None,
        help="YYYY-MM-DD. Defaults to TEST_1.start -- the script refuses to run past that "
        "(see module docstring, no override flag).",
    )
    parser.add_argument("--step-months", type=int, default=2)
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
            "Refusing to compute Signal IC against an already-observed held-out TEST window -- "
            "see this script's own module docstring. No override flag exists for this.",
            file=sys.stderr,
        )
        return 1

    universe = _UNIVERSES[args.universe]
    price_engine = StorageEngine(StorageConfig(root_dir=args.price_db_path))
    fundamentals_engine = StorageEngine(StorageConfig(root_dir=args.fundamentals_db_path))
    price_repository = DuckDBDataRepository(price_engine)
    fundamentals_repository = DuckDBFundamentalsRepository(fundamentals_engine)

    score_fn = _SCORES[args.score]
    rebalance_dates = _rebalance_dates(start, end, args.step_months)

    summary = compute_fundamentals_ic_series(
        list(universe.symbol_ids), rebalance_dates, score_fn,
        fundamentals_repository=fundamentals_repository, price_repository=price_repository,
        horizon_days=args.horizon_days,
    )

    print(f"Fundamentals Signal IC: {args.score} over [{start.date()}, {end.date()}) ({len(rebalance_dates)} rebalance dates)")
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
