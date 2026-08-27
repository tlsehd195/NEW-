"""Train / Validation / Test temporal splitting + a Walk-Forward window
generator (instruction sections 24/25).

Pure date-range arithmetic -- no data access, no wall-clock reads, no
`random`. This module can be (and is, in tests) fully exercised without
any real or fixture market data at all, since it only computes date
boundaries.

**TEST data discipline (instruction section 24)**: `TrainValidationTestSplit`
exists specifically so a caller has one place to define the TEST window
*before* looking at any result -- nothing in this module, or anywhere
else in this package, re-opens or widens a TEST window after the fact.
Enforcing "never touch TEST until the very end" is a research-process
discipline this code cannot itself guarantee (a human or an orchestrating
script could still misuse it) -- it is enforced by `ResearchLog`
recording each candidate's parameters BEFORE evaluation, so a
change-after-seeing-the-result would show up as a second, distinct log
entry rather than silently overwriting the first (see
`strategy_research.research_log`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from strategy_research._dates import add_months


@dataclass(frozen=True)
class TrainValidationTestSplit:
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    test_start: datetime
    test_end: datetime

    def __post_init__(self) -> None:
        ordered = (
            self.train_start, self.train_end,
            self.validation_start, self.validation_end,
            self.test_start, self.test_end,
        )
        if list(ordered) != sorted(ordered):
            raise ValueError("train/validation/test windows must be non-overlapping and strictly ordered")
        if not (self.train_end <= self.validation_start):
            raise ValueError("train window must end at or before validation window starts")
        if not (self.validation_end <= self.test_start):
            raise ValueError("validation window must end at or before test window starts")


def build_chronological_split(
    start: datetime, end: datetime, *, train_fraction: float = 0.6, validation_fraction: float = 0.2
) -> TrainValidationTestSplit:
    """Splits `[start, end]` chronologically (never randomly -- a
    randomized split would leak future information into "train" for a
    time series) into TRAIN / VALIDATION / TEST, in that calendar order.
    `test_fraction` is whatever remains after `train_fraction` +
    `validation_fraction` (must be < 1.0, leaving a strictly positive
    TEST window)."""
    if not (0.0 < train_fraction < 1.0):
        raise ValueError("train_fraction must be in (0, 1)")
    if not (0.0 < validation_fraction < 1.0):
        raise ValueError("validation_fraction must be in (0, 1)")
    if train_fraction + validation_fraction >= 1.0:
        raise ValueError("train_fraction + validation_fraction must leave a positive test window")
    if end <= start:
        raise ValueError("end must be after start")

    train_end = start + (end - start) * train_fraction
    validation_end = start + (end - start) * (train_fraction + validation_fraction)

    return TrainValidationTestSplit(
        train_start=start, train_end=train_end,
        validation_start=train_end, validation_end=validation_end,
        test_start=validation_end, test_end=end,
    )


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


def generate_walk_forward_windows(
    start: datetime, end: datetime, *, train_window_months: int, test_window_months: int, step_months: int
) -> list[WalkForwardWindow]:
    """Rolling walk-forward windows: `[start, start+train_window_months)`
    trains, the immediately following `test_window_months` tests, then
    the whole window slides forward by `step_months` and repeats until
    the next test window would run past `end`.

    Deterministic and pure -- given the same `(start, end,
    train_window_months, test_window_months, step_months)` it always
    returns the identical list of windows (instruction section 34
    reproducibility). Returns an empty list if not even one full
    train+test window fits in `[start, end]` -- callers must not treat
    an empty list as an error condition on its own; it is the correct,
    honest answer for insufficient history (instruction section 25:
    "데이터가 충분하지 않으면 억지로 구현하지 않는다")."""
    if train_window_months < 1 or test_window_months < 1 or step_months < 1:
        raise ValueError("train_window_months, test_window_months, and step_months must all be >= 1")
    if end <= start:
        raise ValueError("end must be after start")

    windows: list[WalkForwardWindow] = []
    window_start = start
    while True:
        train_end = add_months(window_start, train_window_months)
        test_end = add_months(train_end, test_window_months)
        if test_end > end:
            break
        windows.append(WalkForwardWindow(train_start=window_start, train_end=train_end, test_start=train_end, test_end=test_end))
        window_start = add_months(window_start, step_months)
    return windows
