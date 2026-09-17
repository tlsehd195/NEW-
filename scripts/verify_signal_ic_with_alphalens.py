#!/usr/bin/env python3
"""Cross-verifies this project's own `strategy_research.signal_ic.
compute_ic_series` (Spearman rank IC, `RULE 0.8`: raw IC is screening-
only, never the final judgment) against `alphalens-reloaded`'s own,
independently-implemented IC computation, for the same price-only
factor/universe/rebalance schedule/horizon over a real DuckDB catalog
(Session 38, ADR-0139 -- one of the account owner's own uploaded
external-resource reports recommended `alphalens-reloaded` for exactly
this: "factor IC/quantile diagnostics, zero conflict with the existing
pipeline"). This is a diagnostic cross-check, never a replacement --
this project's own `compute_ic_series` output remains the one this
project's walk-forward/PBO/DSR pipeline actually consumes; a real
disagreement between the two is something to investigate, not
something either number automatically overrides.

**Optional dependency, never imported by src/.** Install with
`pip install -e '.[research]'` (adds `alphalens-reloaded`, which itself
pulls in `pandas`/`numpy`/`matplotlib` -- the same "opt-in only, src/
stays dependency-free" boundary `pyproject.toml`'s own `reporting`
extra already established for `quantstats`, ADR-0138).

**Locked-window guard, no override flag** -- identical to
`scripts/compute_signal_ic_from_catalog.py`'s own: refuses to run if
`[--start, --end)` overlaps `strategy_research.locked_windows.TEST_1`.

**Scope, disclosed, not hidden:** only price-only factors from
`strategy_research.factor_scores` are wired in here (the momentum-
strategy-class-based ones `compute_signal_ic_from_catalog.py` also
supports need constructing a stateful strategy instance first, a
separate small extension left for later, not done here).

Usage (against a real DuckDB catalog scripts/ingest_real_market_data.py
already populated):
    pip install -e '.[research]'
    python3 scripts/verify_signal_ic_with_alphalens.py \\
        --db-path ./data/real_market_data --universe RESEARCH_UNIVERSE \\
        --strategy low_volatility --start 2020-01-02 --horizon-days 60
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE4  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from strategy_research._dates import add_months  # noqa: E402
from strategy_research.factor_scores import (  # noqa: E402
    bid_ask_spread_score,
    coskewness_score,
    downside_beta_score,
    fifty_two_week_high_score,
    high_volume_return_premium_score,
    idiosyncratic_skewness_score,
    idiosyncratic_volatility_score,
    illiquidity_score,
    long_term_reversal_score,
    low_beta_score,
    low_volatility_score,
    max_effect_score,
    residual_momentum_score,
    return_seasonality_score,
    rs_rating_score,
    short_term_reversal_score,
)
from strategy_research.locked_windows import TEST_1, overlaps_any_locked_window  # noqa: E402
from strategy_research.signal_ic import ScoreFn, compute_ic_series  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4}

_PRICE_ONLY_SCORES: dict[str, ScoreFn] = {
    "low_volatility": low_volatility_score,
    "long_term_reversal": long_term_reversal_score,
    "short_term_reversal": short_term_reversal_score,
    "low_beta": low_beta_score,
    "illiquidity": illiquidity_score,
    "fifty_two_week_high": fifty_two_week_high_score,
    "max_effect": max_effect_score,
    "idiosyncratic_volatility": idiosyncratic_volatility_score,
    "rs_rating": rs_rating_score,
    "residual_momentum": residual_momentum_score,
    "return_seasonality": return_seasonality_score,
    "bid_ask_spread": bid_ask_spread_score,
    "idiosyncratic_skewness": idiosyncratic_skewness_score,
    "downside_beta": downside_beta_score,
    "high_volume_return_premium": high_volume_return_premium_score,
    "coskewness": coskewness_score,
}


def _rebalance_dates(start: datetime, end: datetime, step_months: int) -> list[datetime]:
    dates = []
    current = start
    while current < end:
        dates.append(current)
        current = add_months(current, step_months)
    return dates


def build_factor_and_prices(
    security_ids: list[str],
    start: datetime,
    end: datetime,
    score_fn: ScoreFn,
    repository,
    *,
    horizon_days: int,
):
    """Pure w.r.t. side effects other than `repository` reads. Returns
    `(factor, prices)` shaped exactly as `alphalens.utils.get_clean_
    factor_and_forward_returns` requires: `factor` a pandas Series with
    a `(date, asset)` MultiIndex, `prices` a wide DataFrame indexed by
    real bar dates with one column per security. A security/date with
    no real score is simply absent from `factor` -- never a fabricated
    0.0 standing in for "the score function returned None".

    **The factor is evaluated on EVERY real trading date in
    `[start, end)`, not at this project's own `--step-months` rebalance
    cadence `compute_ic_series` uses.** Confirmed directly (ADR-0139):
    `alphalens.utils.get_clean_factor_and_forward_returns` infers ONE
    shared trading calendar from the union of the factor's own dates
    and the price index, and raises a real `ValueError` ("Inferred
    frequency ... does not conform...") the moment the factor's dates
    are a sparse, irregular subset (like a monthly rebalance schedule)
    of that dense daily calendar -- confirmed reproducible even after
    snapping each sparse date to a real trading day, so this is a
    genuine density mismatch, not a date-alignment bug. This is
    therefore a disclosed, deliberate difference from `compute_ic_
    series`'s own comparison basis, not a hidden discrepancy: this
    script's own printed output says so, and the two mean_ic values it
    reports are a directional cross-check (same real scores, same real
    forward-return horizon, different rebalance density), never claimed
    to be numerically identical."""
    import pandas as pd

    from backtest.asof import AsOfDataView
    from backtest.clock import BacktestClock

    # Real bars, one column per security -- fetched through the buffer
    # `horizon_days` past `end`, the same "calendar days, not trading
    # days" convention strategy_research.signal_ic.forward_return
    # already uses, so alphalens has real forward price data to
    # compute a `horizon_days`-period forward return from even the
    # last real trading date before `end`.
    price_range_end = end + timedelta(days=horizon_days)
    price_series_by_security: dict[str, "pd.Series"] = {}
    for security_id in security_ids:
        bars = repository.get_bars(security_id, start, price_range_end, as_of_time=price_range_end)
        if not bars:
            continue
        price_series_by_security[security_id] = pd.Series(
            {b.timestamp: (b.adjusted_close or b.close) for b in bars}
        )
    prices = pd.DataFrame(price_series_by_security).sort_index()

    factor_dates = [d for d in prices.index if start <= d < end]
    factor_index: list[tuple[datetime, str]] = []
    factor_values: list[float] = []
    for as_of_time in factor_dates:
        data_view = AsOfDataView(repository, BacktestClock(checkpoints=(as_of_time,)))
        for security_id in security_ids:
            score = score_fn(security_id, as_of_time, data_view)
            if score is not None:
                factor_index.append((as_of_time, security_id))
                factor_values.append(score)
    factor = pd.Series(
        factor_values, index=pd.MultiIndex.from_tuples(factor_index, names=["date", "asset"]), name="factor",
    )

    return factor, prices


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="RESEARCH_UNIVERSE")
    parser.add_argument("--strategy", choices=sorted(_PRICE_ONLY_SCORES), required=True)
    parser.add_argument("--start", required=True, type=str, help="YYYY-MM-DD")
    parser.add_argument(
        "--end", type=str, default=None,
        help="YYYY-MM-DD. Defaults to TEST_1.start, same locked-window precedent as "
        "scripts/compute_signal_ic_from_catalog.py -- no override flag exists for this.",
    )
    parser.add_argument("--step-months", type=int, default=2)
    parser.add_argument("--horizon-days", type=int, default=60)
    parser.add_argument("--quantiles", type=int, default=5)
    parser.add_argument("--max-loss", type=float, default=0.35, help="alphalens.utils.get_clean_factor_and_forward_returns's own default -- raises MaxLossExceededError above this")
    args = parser.parse_args(argv)

    try:
        import alphalens  # noqa: F401
    except ImportError:
        print("FATAL: alphalens-reloaded is required -- install with: pip install -e '.[research]'", file=sys.stderr)
        return 1

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
            "no override flag exists for this.",
            file=sys.stderr,
        )
        return 1

    universe = _UNIVERSES[args.universe]
    security_ids = list(universe.symbol_ids)
    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBDataRepository(engine)

    score_fn = _PRICE_ONLY_SCORES[args.strategy]
    rebalance_dates = _rebalance_dates(start, end, args.step_months)
    if not rebalance_dates:
        print("FATAL: no rebalance dates in the requested [--start, --end) range", file=sys.stderr)
        return 1

    this_project_summary = compute_ic_series(
        security_ids, rebalance_dates, score_fn, repository, horizon_days=args.horizon_days,
    )

    factor, prices = build_factor_and_prices(
        security_ids, start, end, score_fn, repository, horizon_days=args.horizon_days,
    )
    if factor.empty or prices.empty:
        print("FATAL: no real factor scores or no real price data over this range -- nothing to cross-verify", file=sys.stderr)
        return 1

    import alphalens as al

    factor_data = al.utils.get_clean_factor_and_forward_returns(
        factor, prices, quantiles=args.quantiles, periods=(args.horizon_days,), max_loss=args.max_loss,
    )
    period_col = factor_data.columns[0]  # alphalens names it "<horizon_days>D"
    alphalens_ic_series = al.performance.factor_information_coefficient(factor_data)[period_col]
    alphalens_mean_ic = alphalens_ic_series.mean()

    print(f"Signal IC cross-verification: {args.strategy} over [{start.date()}, {end.date()})")
    print(f"  this project's own compute_ic_series ({len(rebalance_dates)} rebalance dates, --step-months {args.step_months}): "
          f"observations={len(this_project_summary.observations)}, mean_ic={this_project_summary.mean_ic}")
    print(f"  alphalens-reloaded, independent implementation (every real trading date, NOT --step-months -- see this "
          f"script's own module docstring for why): observations={len(alphalens_ic_series)}, mean_ic={alphalens_mean_ic}")
    print("  (diagnostic cross-check only, at deliberately different rebalance densities -- this project's own "
          "mean_ic above is what the walk-forward/PBO/DSR pipeline actually consumes, per RULE 0.8; expect the "
          "same real sign/direction, not numerically identical values)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
