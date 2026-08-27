"""Category: Train/Validation/Test boundary + Walk-Forward window
generation (instruction sections 24, 25, 35-P). Pure date arithmetic --
no data access needed."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from strategy_research.splits import (
    TrainValidationTestSplit,
    build_chronological_split,
    generate_walk_forward_windows,
)


def utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


class TestChronologicalSplit:
    def test_windows_are_strictly_ordered_and_non_overlapping(self) -> None:
        split = build_chronological_split(utc(2018, 1, 1), utc(2023, 1, 1), train_fraction=0.6, validation_fraction=0.2)
        assert split.train_start < split.train_end <= split.validation_start < split.validation_end <= split.test_start < split.test_end

    def test_rejects_fractions_that_leave_no_test_window(self) -> None:
        with pytest.raises(ValueError):
            build_chronological_split(utc(2018, 1, 1), utc(2023, 1, 1), train_fraction=0.7, validation_fraction=0.3)

    def test_manually_constructed_overlapping_split_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            TrainValidationTestSplit(
                train_start=utc(2020, 1, 1), train_end=utc(2021, 6, 1),
                validation_start=utc(2021, 1, 1),  # overlaps train_end
                validation_end=utc(2022, 1, 1),
                test_start=utc(2022, 1, 1), test_end=utc(2023, 1, 1),
            )

    def test_deterministic_given_same_inputs(self) -> None:
        a = build_chronological_split(utc(2018, 1, 1), utc(2023, 1, 1))
        b = build_chronological_split(utc(2018, 1, 1), utc(2023, 1, 1))
        assert a == b


class TestWalkForwardWindows:
    def test_generates_non_overlapping_train_test_pairs(self) -> None:
        windows = generate_walk_forward_windows(
            utc(2018, 1, 1), utc(2023, 1, 1), train_window_months=12, test_window_months=3, step_months=3
        )
        assert len(windows) > 0
        for w in windows:
            assert w.train_start < w.train_end == w.test_start < w.test_end

    def test_every_test_window_ends_at_or_before_end(self) -> None:
        end = utc(2023, 1, 1)
        windows = generate_walk_forward_windows(utc(2018, 1, 1), end, train_window_months=12, test_window_months=3, step_months=3)
        assert all(w.test_end <= end for w in windows)

    def test_insufficient_history_returns_empty_list_not_an_error(self) -> None:
        """Instruction section 25: when data is not sufficient for even
        one train+test window, the honest answer is an empty list, not
        a forced/degenerate window."""
        windows = generate_walk_forward_windows(
            utc(2022, 1, 1), utc(2022, 6, 1), train_window_months=12, test_window_months=3, step_months=3
        )
        assert windows == []

    def test_deterministic_given_same_inputs(self) -> None:
        a = generate_walk_forward_windows(utc(2018, 1, 1), utc(2023, 1, 1), train_window_months=12, test_window_months=3, step_months=3)
        b = generate_walk_forward_windows(utc(2018, 1, 1), utc(2023, 1, 1), train_window_months=12, test_window_months=3, step_months=3)
        assert a == b

    def test_rejects_non_positive_window_sizes(self) -> None:
        with pytest.raises(ValueError):
            generate_walk_forward_windows(utc(2018, 1, 1), utc(2023, 1, 1), train_window_months=0, test_window_months=3, step_months=3)
