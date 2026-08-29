"""Category: TEST-1 lock protection (Phase 32, RULE 0.8 no-TEST-reuse).

See strategy_research/locked_windows.py's own docstring for what this
guards against: reusing an already-observed held-out TEST window for
any future strategy or ML model evaluation."""

from __future__ import annotations

from datetime import datetime, timezone

from strategy_research.locked_windows import TEST_1, overlaps_any_locked_window


def _utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


class TestTest1Constant:
    def test_test_1_matches_the_actually_observed_report_values(self) -> None:
        # Recorded verbatim from the real report's chronological_split --
        # a regression guard against this constant silently drifting.
        assert TEST_1.start == _utc(2023, 4, 28, 14, 24)
        assert TEST_1.end == _utc(2026, 8, 27, 0, 0)

    def test_test_1_lists_all_4_strategies_that_observed_it(self) -> None:
        assert set(TEST_1.observed_by) == {
            "buy_and_hold", "long_term_momentum", "trend_volatility", "risk_controlled_momentum",
        }


class TestOverlapDetection:
    def test_a_proposed_test_range_identical_to_test_1_is_flagged(self) -> None:
        overlapping = overlaps_any_locked_window(TEST_1.start, TEST_1.end)
        assert overlapping == (TEST_1,)

    def test_a_range_fully_inside_test_1_is_flagged(self) -> None:
        overlapping = overlaps_any_locked_window(_utc(2024, 1, 1), _utc(2024, 6, 1))
        assert overlapping == (TEST_1,)

    def test_a_range_partially_overlapping_the_start_is_flagged(self) -> None:
        overlapping = overlaps_any_locked_window(_utc(2022, 1, 1), _utc(2023, 6, 1))
        assert overlapping == (TEST_1,)

    def test_a_range_partially_overlapping_the_end_is_flagged(self) -> None:
        overlapping = overlaps_any_locked_window(_utc(2026, 1, 1), _utc(2027, 1, 1))
        assert overlapping == (TEST_1,)

    def test_a_range_entirely_before_test_1_is_not_flagged(self) -> None:
        # e.g. TRAIN+VALIDATION for a future study, or any of this
        # project's existing walk-forward folds (all inside
        # 2010-2023-04-28, strictly before TEST-1 starts).
        overlapping = overlaps_any_locked_window(_utc(2010, 1, 1), _utc(2020, 1, 1))
        assert overlapping == ()

    def test_a_range_entirely_after_test_1_is_not_flagged(self) -> None:
        # Once real time passes 2026-08-27, genuinely new unseen data.
        overlapping = overlaps_any_locked_window(_utc(2027, 1, 1), _utc(2028, 1, 1))
        assert overlapping == ()

    def test_touching_boundary_exactly_is_not_flagged(self) -> None:
        # [end, end+1y) starts exactly where TEST-1 ends -- no overlap,
        # half-open interval semantics.
        overlapping = overlaps_any_locked_window(TEST_1.end, _utc(2027, 8, 27))
        assert overlapping == ()
