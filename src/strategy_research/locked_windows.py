"""Registry of permanently LOCKED held-out TEST windows (Phase 32,
"PHASE 32 -- 40종목 결과 심층분석 + ML RESEARCH TRACK 설계", RULE 0.8's
no-TEST-reuse discipline).

Once a date range has been used as the held-out TEST for ANY strategy
or model evaluation whose result informed a decision -- including "we
fixed a bug and want to know whether it helped" -- that range is
retired from ever being used again as TRAIN, VALIDATION, or TEST data,
for that strategy family AND for any future one (rule-based or ML).
Reusing it, even for a genuinely different model, is evaluating against
an already-seen answer key; RULE 0.8 treats this as strictly worse than
ordinary post-hoc parameter tuning, not equivalent to it.

This module is a lookup/guard utility, not an enforcement mechanism
threaded automatically through every future pipeline -- any script
that builds a new TRAIN/VALIDATION/TEST split (rule-based or ML) is
expected to call `overlaps_any_locked_window` on its own proposed TEST
range and refuse (or loudly flag) an overlap, the same way this
project's other point-in-time guards are opt-in library calls rather
than a runtime that can't be bypassed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class LockedWindow:
    name: str
    start: datetime
    end: datetime
    observed_by: tuple[str, ...]
    note: str


# TEST-1: the chronological_split.test_start/test_end this project's
# first (and, as of Phase 32, only) real 40-symbol walk-forward run
# actually produced (RESEARCH_UNIVERSE_STAGE2, 2010-01-01..2026-08-27
# overall range, default 60/20/20 train/validation/test split) --
# recorded verbatim from that run's own report, not re-derived, so this
# constant can never silently drift if the split-fraction defaults
# elsewhere in this codebase ever change. See
# docs/research/STRATEGY-VALIDATION-REPORT.md's "40-Symbol
# (RESEARCH_UNIVERSE Stage 2) Re-Validation" section and
# docs/decisions/ADR-0041-test-1-lock-and-ml-research-track.md.
TEST_1 = LockedWindow(
    name="TEST-1",
    start=datetime(2023, 4, 28, 14, 24, tzinfo=timezone.utc),
    end=datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc),
    observed_by=(
        "buy_and_hold",
        "long_term_momentum",
        "trend_volatility",
        "risk_controlled_momentum",
    ),
    note=(
        "Observed once, real data, RESEARCH_UNIVERSE_STAGE2 (40 symbols). "
        "All 4 strategies substantially underperformed SPY here. Two of "
        "those 4 strategies' signal-window computation was subsequently "
        "corrected (ADR-0038) AFTER this window was observed -- the "
        "corrected strategies have deliberately NOT been re-evaluated "
        "against this window, and must not be."
    ),
)

# TEST-2: the chronological_split.test_start/test_end from
# run_full_validation.yml's 2026-09-25 real 87-symbol walk-forward run
# (RESEARCH_UNIVERSE stage4, overall range 2010-01-01..2023-04-28,
# default 60/20/20 split), recorded verbatim from that run's own report
# (docs/research/reports/full-validation-20260925T160732Z.json,
# experiment_id 3b7e82ffa9bf47f3) -- same "record what the report
# actually said, don't re-derive" discipline as TEST_1. Ends exactly at
# TEST_1's own start (2023-04-28), so the two are adjacent, not
# overlapping -- both can be locked independently. Added retroactively
# (2026-09-26, human factor review of that run's 51 INCONCLUSIVE
# results) -- this window was already observed by all 51 candidates
# below before this entry existed; adding it now closes that gap so no
# FUTURE strategy (including a newly-added one) can be evaluated
# against it, per RULE 0.8.
TEST_2 = LockedWindow(
    name="TEST-2",
    start=datetime(2020, 8, 28, tzinfo=timezone.utc),
    end=datetime(2023, 4, 28, tzinfo=timezone.utc),
    observed_by=(
        "abnormal_investment", "altman_z", "asset_growth", "asset_turnover_change",
        "bid_ask_spread", "book_to_market", "buy_and_hold", "cash_holdings",
        "cashflow_yield", "combined_factor", "coskewness", "dividend_growth",
        "downside_beta", "earnings_yield", "fifty_two_week_high", "gross_profitability",
        "high_volume_return_premium", "idiosyncratic_skewness", "idiosyncratic_volatility",
        "illiquidity", "industry_momentum", "leverage", "long_term_momentum",
        "long_term_reversal", "low_beta", "max_effect", "merton_dd", "ml_ols",
        "ml_ridge", "ml_tree", "net_operating_assets", "net_stock_issuance", "ohlson_o",
        "operating_leverage", "piotroski", "quality_minus_junk", "rank_average_ensemble",
        "rd_expenditure", "residual_momentum", "return_seasonality",
        "risk_controlled_momentum", "rs_rating", "sales_yield", "share_turnover",
        "shareholder_yield", "short_term_reversal", "size", "sloan_accruals", "sue",
        "trend_volatility", "value_composite",
    ),
    note=(
        "Observed once, real data, RESEARCH_UNIVERSE stage4 (87 symbols). "
        "All 51 candidates classified INCONCLUSIVE (PBO=0.19); 4 reached "
        "this project's CANDIDATE evidence level on the walk-forward folds "
        "(altman_z, rank_average_ensemble, merton_dd, asset_turnover_change) "
        "but all 4 substantially underperformed SPY on this exact held-out "
        "TEST window regardless (altman_z: -44.5pp excess return, -52.9% "
        "max drawdown) -- the same CANDIDATE-level-is-not-validated pattern "
        "ADR-0045 already documented for `leverage` against a different "
        "window. See docs/research/reports/"
        "full-validation-20260925T160732Z.json for the full per-candidate "
        "results this note summarizes."
    ),
)

LOCKED_WINDOWS: tuple[LockedWindow, ...] = (TEST_1, TEST_2)


def overlaps_any_locked_window(start: datetime, end: datetime) -> tuple[LockedWindow, ...]:
    """Every `LockedWindow` whose range overlaps `[start, end]`
    (half-open interval overlap check). Empty tuple means no conflict.
    Callers should refuse to use `[start, end]` as TRAIN, VALIDATION,
    or TEST data for any new strategy/model evaluation when this
    returns anything non-empty."""
    return tuple(w for w in LOCKED_WINDOWS if start < w.end and end > w.start)


def earliest_locked_window_start() -> datetime:
    """The earliest `start` across every registered `LockedWindow` --
    the one universally-safe default `--end` for any script that wants
    "everything not-yet-observed" without naming a specific window.

    **Real bug this fixes (2026-09-26, adding `TEST_2`)**: five scripts
    (`compute_signal_ic_from_catalog.py`, `compute_fundamentals_ic_
    from_catalog.py`, `compute_filter_bucket_returns_from_catalog.py`,
    `train_ml_model_from_catalog.py`, `verify_signal_ic_with_
    alphalens.py`) each hardcoded their own default `--end` to `TEST_1.
    start` directly -- correct while `TEST_1` was the only locked
    window, but `TEST_2.start` (2020-08-28) is earlier than `TEST_1.
    start` (2023-04-28), so that hardcoded default silently became
    unsafe (overlapping `TEST_2`) the moment `TEST_2` was added, caught
    only because those scripts' own tests asserted the default was
    safe and started failing. Calling this function instead of naming
    a window directly means adding a future `TEST_3` starting earlier
    than both cannot silently reintroduce the same bug a third time.

    Never returns `None`/raises on an empty registry -- at least one
    `LockedWindow` (`TEST_1`) always exists once this module has ever
    been imported, so this is a plain `min()` over a guaranteed
    non-empty sequence, not a fallible lookup a caller needs to guard."""
    return min(w.start for w in LOCKED_WINDOWS)
