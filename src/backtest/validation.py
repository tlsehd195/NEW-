"""Validation split utilities.

See docs/specifications/PHASE-2-backtesting.md section 14 and ADR-0008.

Only chronological splitting exists here — random train/test splitting
is never used for this project's time-series data (PROJECT_MASTER_PLAN.md
section 48). Purged K-Fold / Embargo are reserved via ValidationSplitter
but not implemented (ADR-0008).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterator, Protocol


@dataclass(frozen=True)
class DateRange:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("DateRange.end must be after start")


def chronological_train_test_split(
    start: datetime, end: datetime, split_date: datetime
) -> tuple[DateRange, DateRange]:
    if not start < split_date < end:
        raise ValueError("split_date must lie strictly between start and end")
    return DateRange(start, split_date), DateRange(split_date, end)


@dataclass(frozen=True)
class WalkForwardWindow:
    train: DateRange
    test: DateRange


class ValidationSplitter(Protocol):
    """The shape any future splitter (including Purged K-Fold / Embargo,
    ADR-0008) must satisfy so consumers do not need to change when a more
    sophisticated splitter is added."""

    def split(self) -> Iterator[WalkForwardWindow]: ...


@dataclass(frozen=True)
class WalkForwardSplitter:
    start: datetime
    end: datetime
    train_period: timedelta
    test_period: timedelta
    step: timedelta

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        for name, value in (
            ("train_period", self.train_period),
            ("test_period", self.test_period),
            ("step", self.step),
        ):
            if value <= timedelta(0):
                raise ValueError(f"{name} must be positive")

    def split(self) -> Iterator[WalkForwardWindow]:
        train_start = self.start
        while True:
            train_end = train_start + self.train_period
            test_end = train_end + self.test_period
            if test_end > self.end:
                break
            yield WalkForwardWindow(
                train=DateRange(train_start, train_end),
                test=DateRange(train_end, test_end),
            )
            train_start = train_start + self.step
