"""Tests for `data_infra.security_master_backfill` (Session 37
continued: wiring ADR-0126/ADR-0128's 59 recovered delisted tickers'
real bars into actual SecurityMaster records)."""

from __future__ import annotations

from datetime import datetime, timezone

from data_infra.enums import SecurityStatus
from data_infra.security_master_backfill import build_delisted_security_masters_from_bars


def utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


class _FakeBar:
    def __init__(self, timestamp):
        self.timestamp = timestamp


class _FakeRepository:
    def __init__(self, bars_by_security: dict) -> None:
        self._bars_by_security = bars_by_security

    def get_bars(self, security_id, start, end, as_of_time):
        return self._bars_by_security.get(security_id, [])


class TestBuildDelistedSecurityMastersFromBars:
    def test_a_security_with_bars_gets_a_delisted_record(self) -> None:
        repo = _FakeRepository({"DELL": [_FakeBar(utc(1988, 8, 17)), _FakeBar(utc(2013, 10, 29))]})
        records = build_delisted_security_masters_from_bars(
            repo, ["DELL"], price_history_start=utc(1900, 1, 1), as_of_time=utc(2026, 1, 1)
        )
        assert len(records) == 1
        record = records[0]
        assert record.security_id == "DELL"
        assert record.status == SecurityStatus.DELISTED
        assert record.valid_from == utc(1988, 8, 17)

    def test_valid_to_is_one_day_past_the_last_real_bar_so_that_day_is_still_valid(self) -> None:
        repo = _FakeRepository({"DELL": [_FakeBar(utc(2013, 10, 29))]})
        records = build_delisted_security_masters_from_bars(
            repo, ["DELL"], price_history_start=utc(1900, 1, 1), as_of_time=utc(2026, 1, 1)
        )
        record = records[0]
        assert record.valid_to == utc(2013, 10, 30)
        assert record.is_valid_at(utc(2013, 10, 29)) is True

    def test_a_security_with_no_bars_is_silently_skipped(self) -> None:
        repo = _FakeRepository({})
        records = build_delisted_security_masters_from_bars(
            repo, ["NOSUCHTICKER"], price_history_start=utc(1900, 1, 1), as_of_time=utc(2026, 1, 1)
        )
        assert records == []

    def test_only_the_requested_symbols_are_backfilled(self) -> None:
        repo = _FakeRepository(
            {"DELL": [_FakeBar(utc(2013, 10, 29))], "ATVI": [_FakeBar(utc(2023, 10, 12))]}
        )
        records = build_delisted_security_masters_from_bars(
            repo, ["DELL"], price_history_start=utc(1900, 1, 1), as_of_time=utc(2026, 1, 1)
        )
        assert {r.security_id for r in records} == {"DELL"}

    def test_exchange_and_company_id_use_the_same_honest_sentinel_convention(self) -> None:
        """Matches data_infra.universe.build_security_masters exactly --
        never a guessed exchange name."""
        repo = _FakeRepository({"DELL": [_FakeBar(utc(2013, 10, 29))]})
        record = build_delisted_security_masters_from_bars(
            repo, ["DELL"], price_history_start=utc(1900, 1, 1), as_of_time=utc(2026, 1, 1)
        )[0]
        assert record.exchange == "UNKNOWN"
        assert record.company_id == "COMPANY-DELL"
        assert record.currency == "USD"

    def test_a_single_bar_still_produces_a_valid_record(self) -> None:
        """valid_to must be strictly after valid_from even with exactly
        one real bar (SecurityMaster.__post_init__ enforces this)."""
        repo = _FakeRepository({"VIAC": [_FakeBar(utc(2022, 2, 16))]})
        records = build_delisted_security_masters_from_bars(
            repo, ["VIAC"], price_history_start=utc(1900, 1, 1), as_of_time=utc(2026, 1, 1)
        )
        assert len(records) == 1
        assert records[0].valid_to > records[0].valid_from
