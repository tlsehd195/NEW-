"""Category: TEST-1/TEST-2 lock protection (Phase 32, RULE 0.8
no-TEST-reuse).

See strategy_research/locked_windows.py's own docstring for what this
guards against: reusing an already-observed held-out TEST window for
any future strategy or ML model evaluation."""

from __future__ import annotations

from datetime import datetime, timezone

from strategy_research.locked_windows import TEST_1, TEST_2, earliest_locked_window_start, overlaps_any_locked_window


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


class TestTest2Constant:
    """TEST-2: added retroactively (2026-09-26) after a human factor
    review of run_full_validation.yml's 2026-09-25 report noticed this
    range had already been observed by all 51 candidates but was never
    locked -- see locked_windows.py's own docstring on this entry."""

    def test_test_2_matches_the_actually_observed_report_values(self) -> None:
        assert TEST_2.start == _utc(2020, 8, 28)
        assert TEST_2.end == _utc(2023, 4, 28)

    def test_test_2_ends_exactly_where_test_1_starts(self) -> None:
        # Adjacent, not overlapping -- both windows are independently
        # lockable without conflicting with each other.
        assert TEST_2.end < TEST_1.start

    def test_test_2_lists_all_51_candidates_that_observed_it(self) -> None:
        assert len(TEST_2.observed_by) == 51
        assert len(set(TEST_2.observed_by)) == 51  # no duplicates
        for name in ("altman_z", "rank_average_ensemble", "merton_dd", "asset_turnover_change"):
            assert name in TEST_2.observed_by


class TestEarliestLockedWindowStart:
    """Real bug this function fixes (2026-09-26, ADR-0209): five scripts
    hardcoded their default `--end` to `TEST_1.start` directly, which
    silently became unsafe (overlapping TEST_2) the moment TEST_2 was
    added -- caught by their own tests failing. This function is the
    fix, and must itself track whichever window starts earliest."""

    def test_returns_test_2_start_since_it_is_earlier_than_test_1(self) -> None:
        assert TEST_2.start < TEST_1.start
        assert earliest_locked_window_start() == TEST_2.start

    def test_the_earliest_start_itself_does_not_overlap_any_locked_window(self) -> None:
        # The whole point: [anything, earliest_locked_window_start()) must
        # be a safe default for a caller that wants "everything not-yet-
        # observed" without naming a specific window.
        assert overlaps_any_locked_window(_utc(2010, 1, 1), earliest_locked_window_start()) == ()


class TestOverlapDetection:
    def test_a_proposed_test_range_identical_to_test_1_is_flagged(self) -> None:
        overlapping = overlaps_any_locked_window(TEST_1.start, TEST_1.end)
        assert overlapping == (TEST_1,)

    def test_a_proposed_test_range_identical_to_test_2_is_flagged(self) -> None:
        overlapping = overlaps_any_locked_window(TEST_2.start, TEST_2.end)
        assert overlapping == (TEST_2,)

    def test_a_range_fully_inside_test_1_is_flagged(self) -> None:
        overlapping = overlaps_any_locked_window(_utc(2024, 1, 1), _utc(2024, 6, 1))
        assert overlapping == (TEST_1,)

    def test_a_range_fully_inside_test_2_is_flagged(self) -> None:
        overlapping = overlaps_any_locked_window(_utc(2021, 1, 1), _utc(2021, 6, 1))
        assert overlapping == (TEST_2,)

    def test_a_range_spanning_both_locked_windows_flags_both(self) -> None:
        overlapping = overlaps_any_locked_window(_utc(2022, 1, 1), _utc(2024, 1, 1))
        assert overlapping == (TEST_1, TEST_2)

    def test_a_range_partially_overlapping_the_end_is_flagged(self) -> None:
        overlapping = overlaps_any_locked_window(_utc(2026, 1, 1), _utc(2027, 1, 1))
        assert overlapping == (TEST_1,)

    def test_a_range_entirely_before_both_locked_windows_is_not_flagged(self) -> None:
        # e.g. TRAIN+VALIDATION for a future study, or any of this
        # project's existing walk-forward folds strictly before TEST-2
        # starts (2020-08-28).
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

    def test_the_gap_between_test_2_and_test_1_is_not_flagged(self) -> None:
        # TEST-2 ends exactly where TEST-1 starts (both adjacent,
        # zero-width gap) -- a range touching only that boundary point
        # overlaps neither, same half-open semantics as the TEST-1 test above.
        overlapping = overlaps_any_locked_window(TEST_2.end, TEST_1.start)
        assert overlapping == ()
