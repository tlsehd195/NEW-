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

LOCKED_WINDOWS: tuple[LockedWindow, ...] = (TEST_1,)


def overlaps_any_locked_window(start: datetime, end: datetime) -> tuple[LockedWindow, ...]:
    """Every `LockedWindow` whose range overlaps `[start, end]`
    (half-open interval overlap check). Empty tuple means no conflict.
    Callers should refuse to use `[start, end]` as TRAIN, VALIDATION,
    or TEST data for any new strategy/model evaluation when this
    returns anything non-empty."""
    return tuple(w for w in LOCKED_WINDOWS if start < w.end and end > w.start)
