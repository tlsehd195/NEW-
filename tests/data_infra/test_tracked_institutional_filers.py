"""Category: data_infra.tracked_institutional_filers -- the curated,
point-in-time-aware "guru investor" registry backing
strategy_research.factor_scores.guru_consensus_score (ADR-0194).

The core property under test is the one the account owner explicitly
asked for: editing a filer's tracked_until (e.g. because that investor
retired or the fund closed) must never change what a backtest computes
for an as_of_time BEFORE that edit -- a look-ahead-style guard on the
REGISTRY itself, not just on the underlying 13F data."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from helpers import utc

from data_infra.tracked_institutional_filers import TRACKED_FILERS, TrackedFiler, active_tracked_filers


class TestTrackedFilerConstruction:
    def test_empty_cik_rejected(self) -> None:
        with pytest.raises(ValueError):
            TrackedFiler(cik="", name="X", tracked_from=utc(2010, 1, 1), tracked_until=None, note="")

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            TrackedFiler(cik="0001", name="", tracked_from=utc(2010, 1, 1), tracked_until=None, note="")

    def test_naive_tracked_from_rejected(self) -> None:
        with pytest.raises(ValueError):
            TrackedFiler(cik="0001", name="X", tracked_from=datetime(2010, 1, 1), tracked_until=None, note="")

    def test_naive_tracked_until_rejected(self) -> None:
        with pytest.raises(ValueError):
            TrackedFiler(cik="0001", name="X", tracked_from=utc(2010, 1, 1), tracked_until=datetime(2020, 1, 1), note="")

    def test_tracked_until_before_tracked_from_rejected(self) -> None:
        with pytest.raises(ValueError):
            TrackedFiler(cik="0001", name="X", tracked_from=utc(2020, 1, 1), tracked_until=utc(2010, 1, 1), note="")

    def test_tracked_until_equal_to_tracked_from_is_allowed(self) -> None:
        filer = TrackedFiler(cik="0001", name="X", tracked_from=utc(2020, 1, 1), tracked_until=utc(2020, 1, 1), note="")
        assert filer.tracked_until == filer.tracked_from


class TestIsTrackedAt:
    def test_before_tracked_from_is_not_tracked(self) -> None:
        filer = TrackedFiler(cik="0001", name="X", tracked_from=utc(2015, 1, 1), tracked_until=None, note="")
        assert filer.is_tracked_at(utc(2014, 12, 31)) is False

    def test_at_or_after_tracked_from_with_no_tracked_until_is_tracked(self) -> None:
        filer = TrackedFiler(cik="0001", name="X", tracked_from=utc(2015, 1, 1), tracked_until=None, note="")
        assert filer.is_tracked_at(utc(2015, 1, 1)) is True
        assert filer.is_tracked_at(utc(2030, 1, 1)) is True

    def test_after_tracked_until_is_not_tracked(self) -> None:
        filer = TrackedFiler(cik="0001", name="X", tracked_from=utc(2015, 1, 1), tracked_until=utc(2020, 1, 1), note="")
        assert filer.is_tracked_at(utc(2020, 1, 2)) is False

    def test_at_tracked_until_is_still_tracked(self) -> None:
        filer = TrackedFiler(cik="0001", name="X", tracked_from=utc(2015, 1, 1), tracked_until=utc(2020, 1, 1), note="")
        assert filer.is_tracked_at(utc(2020, 1, 1)) is True

    def test_editing_tracked_until_does_not_change_a_past_as_of_time(self) -> None:
        """The exact scenario the account owner raised: retiring a
        tracked investor TODAY must not retroactively change a
        backtest's result for an as_of_time before the retirement."""
        as_of_before_retirement = utc(2018, 6, 1)
        still_active = TrackedFiler(cik="0001", name="X", tracked_from=utc(2015, 1, 1), tracked_until=None, note="")
        retired_later = TrackedFiler(cik="0001", name="X", tracked_from=utc(2015, 1, 1), tracked_until=utc(2025, 1, 1), note="")
        assert still_active.is_tracked_at(as_of_before_retirement) == retired_later.is_tracked_at(as_of_before_retirement) is True


class TestActiveTrackedFilers:
    def test_naive_as_of_time_rejected(self) -> None:
        with pytest.raises(ValueError):
            active_tracked_filers(datetime(2020, 1, 1))

    def test_returns_only_filers_tracked_at_that_time(self) -> None:
        as_of = utc(2020, 1, 1)
        result = active_tracked_filers(as_of)
        assert all(filer.is_tracked_at(as_of) for filer in result)
        assert set(result) == {filer for filer in TRACKED_FILERS if filer.is_tracked_at(as_of)}

    def test_far_future_as_of_time_excludes_scion_which_deregistered_2025_11_10(self) -> None:
        # Real, verified event (see TRACKED_FILERS' own note): Michael
        # Burry's Scion Asset Management deregistered with the SEC on
        # 2025-11-10 -- a genuine instance of the "tracked investor
        # retires" scenario, not a hypothetical test fixture.
        result = active_tracked_filers(utc(2026, 1, 1))
        names = {filer.name for filer in result}
        assert "Scion Asset Management, LLC" not in names

    def test_before_scion_deregistration_scion_is_still_tracked(self) -> None:
        result = active_tracked_filers(utc(2020, 1, 1))
        names = {filer.name for filer in result}
        assert "Scion Asset Management, LLC" in names


class TestRegistryContents:
    def test_every_cik_is_unique(self) -> None:
        ciks = [filer.cik for filer in TRACKED_FILERS]
        assert len(ciks) == len(set(ciks))

    def test_registry_is_non_empty(self) -> None:
        assert len(TRACKED_FILERS) > 0
