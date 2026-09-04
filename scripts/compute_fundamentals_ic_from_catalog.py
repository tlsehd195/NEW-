#!/usr/bin/env python3
"""Computes real-data Signal IC for a fundamentals-based factor --
`roe`, `roa`, `net_margin`, `leverage` (all in `strategy_research.
factor_scores`, sharing the same `_fy_ratio` plumbing), `gross_profitability`
(Novy-Marx 2013's gross profitability premium, ADR-0043 Decision 15 --
`(Revenues - CostOfGoodsAndServicesSold) / Assets`), `altman_z`
(Altman 1968's Z-Score distress-risk formula, ADR-0043 Decision 16 --
also needs price for market value of equity, wired through
`compute_hybrid_ic_series`), `book_to_market`/`sales_yield`/
`cashflow_yield` (the 3 of `value_composite`'s 5 legs that were
buildable standalone but never had a CLI option -- ADR-0043 Decision
16 gap fix), `asset_growth`
(a year-over-year change rather than a single-period ratio -- Cooper,
Gulen & Schill 2008's asset growth anomaly, ADR-0043 Decision 8), or
`piotroski` (a 0-9 composite of nine YoY quality-improvement signals --
Piotroski 2000's F-Score, ADR-0043 Decision 9; needs 6 new XBRL
concepts beyond what earlier scores needed), `shareholder_yield`
(dividends + net buybacks over market cap -- ADR-0043 Decision 10; the
first score here that also needs price data, wired through the new
`compute_hybrid_ic_series` instead of `compute_fundamentals_ic_series`),
`sloan_accruals` (Sloan 1996's accruals anomaly -- ADR-0043 Decision
11), `dividend_growth` (a YoY change in dividends paid, ADR-0043
Decision 11), `earnings_yield` (Basu 1977's net-income/market-cap
value anomaly, ADR-0043 Decision 11 -- also wired through
`compute_hybrid_ic_series`, since it needs price too), `quality_minus_junk`
(Asness, Frazzini & Pedersen's quality composite, ADR-0043 Decision 12
-- a CROSS-SECTIONAL score computed for the whole universe at once via
the new `compute_universe_ic_series`, not per-security), `value_composite` (O'Shaughnessy's multi-ratio value composite, ADR-0043
Decision 12 -- also cross-sectional, and also needs price), `size`
(Banz 1981's size effect, ADR-0043 Decision 13 -- negative market cap,
also wired through `compute_hybrid_ic_series` since it needs price), or
`combined_factor` (Session 36 -- a 9-leg rank-averaged combination of
every Session 36 raw-IC-screened candidate whose sign matched
literature, also cross-sectional -- see `factor_scores.combined_
factor_score`'s own docstring for the exact leg list and selection
rule) -- using
`strategy_research.signal_ic.compute_fundamentals_ic_series` (or, for
`shareholder_yield`/`earnings_yield`, `compute_hybrid_ic_series`; or,
for `quality_minus_junk`/`value_composite`/`combined_factor`,
`compute_universe_ic_series`)
against two live DuckDB catalogs: the fundamentals catalog (ADR-0042,
`ingest_fundamentals_data.py`'s output) and the price catalog
(`ingest_real_market_data.py`'s output, needed for forward returns,
and for the price-dependent scores' market-cap calculation too).
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
    altman_z_score,
    asset_growth_score,
    book_to_market_score,
    cashflow_yield_score,
    combined_factor_score,
    dividend_growth_score,
    earnings_yield_score,
    gross_profitability_score,
    leverage_score,
    net_margin_score,
    piotroski_f_score,
    quality_minus_junk_score,
    roa_score,
    roe_score,
    sales_yield_score,
    shareholder_yield_score,
    size_score,
    sloan_accruals_score,
    value_composite_score,
)
from strategy_research.locked_windows import TEST_1, overlaps_any_locked_window  # noqa: E402
from strategy_research.signal_ic import (  # noqa: E402
    compute_fundamentals_ic_series,
    compute_hybrid_ic_series,
    compute_universe_ic_series,
)

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE3}

_SCORES = {
    "roe": roe_score,
    "roa": roa_score,
    "net_margin": net_margin_score,
    "gross_profitability": gross_profitability_score,
    "leverage": leverage_score,
    "asset_growth": asset_growth_score,
    "piotroski": piotroski_f_score,
    "sloan_accruals": sloan_accruals_score,
    "dividend_growth": dividend_growth_score,
}

# Session 36 addition (ADR-0043 Decision 10) -- scores whose score_fn
# needs BOTH repositories (not just fundamentals_repository), wired
# through compute_hybrid_ic_series instead of compute_fundamentals_
# ic_series. Kept as a separate dict rather than merged into _SCORES
# since the two score_fn signatures differ (3 args vs 4) and main()
# needs to know which call path to use.
_HYBRID_SCORES = {
    "shareholder_yield": shareholder_yield_score,
    "earnings_yield": earnings_yield_score,
    "size": size_score,
    "altman_z": altman_z_score,
    # Session 36 gap fix (ADR-0043 Decision 16): book_to_market_score's
    # own docstring already promised it is "independently testable on
    # its own via compute_hybrid_ic_series" (ADR-0043 Decision 12) --
    # but the CLI --score option to actually do that was never added.
    # sales_yield/cashflow_yield are the other 2 of value_composite's 5
    # legs that were similarly buildable standalone but never wired;
    # added here for the same reason, closing the gap for all 3 at once
    # rather than fixing only the one whose docstring explicitly
    # promised it.
    "book_to_market": book_to_market_score,
    "sales_yield": sales_yield_score,
    "cashflow_yield": cashflow_yield_score,
}

# Session 36 addition (ADR-0043 Decision 12) -- scores whose score_fn is
# CROSS-SECTIONAL (computes every security's score for the whole
# universe at once per rebalance date, typically via cross-sectional
# rank-averaging), wired through compute_universe_ic_series instead of
# either function above. A third dict, not merged into _HYBRID_SCORES,
# since the call shape differs again (one call per rebalance date with
# the full security_ids list, returning a dict, vs one call per
# security returning a single score).
_UNIVERSE_SCORES = {
    "quality_minus_junk": quality_minus_junk_score,
    "value_composite": value_composite_score,
    # Session 36 addition: combined_factor_score is UniverseScoreFn-shaped
    # exactly like the two candidates above (see its own docstring in
    # factor_scores.py), so it reuses this same call path with no new
    # plumbing.
    "combined_factor": combined_factor_score,
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
    parser.add_argument("--score", choices=sorted(set(_SCORES) | set(_HYBRID_SCORES) | set(_UNIVERSE_SCORES)), default="roe")
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

    rebalance_dates = _rebalance_dates(start, end, args.step_months)

    if args.score in _UNIVERSE_SCORES:
        summary = compute_universe_ic_series(
            list(universe.symbol_ids), rebalance_dates, _UNIVERSE_SCORES[args.score],
            fundamentals_repository=fundamentals_repository, price_repository=price_repository,
            horizon_days=args.horizon_days,
        )
    elif args.score in _HYBRID_SCORES:
        summary = compute_hybrid_ic_series(
            list(universe.symbol_ids), rebalance_dates, _HYBRID_SCORES[args.score],
            fundamentals_repository=fundamentals_repository, price_repository=price_repository,
            horizon_days=args.horizon_days,
        )
    else:
        summary = compute_fundamentals_ic_series(
            list(universe.symbol_ids), rebalance_dates, _SCORES[args.score],
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
