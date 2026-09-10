"""Category: persistence, restart, idempotency, point-in-time
look-ahead guard, and date-range filtering for
`DuckDBShortInterestRepository` (Session 36 continued, ADR-0099).
Mirrors `test_insider_repository.py`'s exact pattern, applied to short
interest reports' own point-in-time-critical field (`available_time` =
conservative post-dissemination-lag time, never `settlement_date`)."""

from __future__ import annotations

from datetime import datetime

import pytest
from helpers import utc

from data_infra.models import Provenance
from data_infra.short_interest_models import ShortInterestRecord

from storage.short_interest_repository import DuckDBShortInterestRepository
from storage_helpers import new_engine


def _provenance(record_id: str, *, retrieved_at=utc(2026, 9, 3)) -> Provenance:
    return Provenance(
        source="finra_manual_export", source_dataset="finra_manual_export_AAA",
        source_record_id=record_id, retrieved_at=retrieved_at, data_version="v1",
    )


def _record(
    *, record_id="AAA:2026-08-15", security_id="AAA",
    settlement_date=utc(2026, 8, 15), available_time=utc(2026, 8, 26),
    short_interest_quantity=100_000.0, average_daily_volume=50_000.0, days_to_cover=2.0,
) -> ShortInterestRecord:
    return ShortInterestRecord(
        security_id=security_id, settlement_date=settlement_date,
        short_interest_quantity=short_interest_quantity, average_daily_volume=average_daily_volume,
        days_to_cover=days_to_cover, available_time=available_time, ingestion_time=available_time,
        provenance=_provenance(record_id),
    )


class TestPersistenceAndRestart:
    def test_record_survives_restart(self, tmp_path) -> None:
        engine1 = new_engine(tmp_path)
        DuckDBShortInterestRepository(engine1).add_short_interest(_record())
        engine1.close()

        engine2 = new_engine(tmp_path)
        result = DuckDBShortInterestRepository(engine2).get_latest_short_interest("AAA", utc(2026, 12, 31))
        assert result is not None
        assert result.short_interest_quantity == 100_000.0
        engine2.close()

    def test_none_average_daily_volume_and_days_to_cover_round_trip_as_none(self, tmp_path) -> None:
        engine1 = new_engine(tmp_path)
        DuckDBShortInterestRepository(engine1).add_short_interest(
            _record(average_daily_volume=None, days_to_cover=None)
        )
        engine1.close()

        engine2 = new_engine(tmp_path)
        result = DuckDBShortInterestRepository(engine2).get_latest_short_interest("AAA", utc(2026, 12, 31))
        assert result.average_daily_volume is None
        assert result.days_to_cover is None
        engine2.close()


class TestIdempotency:
    def test_re_adding_the_identical_record_does_not_duplicate(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        repo.add_short_interest(_record())
        repo.add_short_interest(_record())  # same provenance_source_record_id
        assert len(repo.get_short_interest_history("AAA", utc(2026, 12, 31))) == 1

    def test_add_short_interest_records_batch_is_also_idempotent(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        repo.add_short_interest_records([_record(), _record()])
        assert len(repo.get_short_interest_history("AAA", utc(2026, 12, 31))) == 1

    def test_two_distinct_settlement_dates_both_survive(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        repo.add_short_interest(_record(record_id="AAA:2026-07-31", settlement_date=utc(2026, 7, 31), available_time=utc(2026, 8, 11), short_interest_quantity=80_000.0))
        repo.add_short_interest(_record(record_id="AAA:2026-08-15", settlement_date=utc(2026, 8, 15), available_time=utc(2026, 8, 26), short_interest_quantity=100_000.0))
        assert len(repo.get_short_interest_history("AAA", utc(2026, 12, 31))) == 2


class TestPointInTimeLookAheadGuard:
    def test_a_report_is_invisible_before_its_own_available_time(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        repo.add_short_interest(_record(available_time=utc(2026, 8, 26)))

        before_dissemination = repo.get_latest_short_interest("AAA", utc(2026, 8, 25))
        after_dissemination = repo.get_latest_short_interest("AAA", utc(2026, 8, 26))

        assert before_dissemination is None
        assert after_dissemination is not None

    def test_get_latest_returns_the_most_recent_available_settlement(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        repo.add_short_interest(_record(record_id="AAA:2026-07-31", settlement_date=utc(2026, 7, 31), available_time=utc(2026, 8, 11), short_interest_quantity=80_000.0))
        repo.add_short_interest(_record(record_id="AAA:2026-08-15", settlement_date=utc(2026, 8, 15), available_time=utc(2026, 8, 26), short_interest_quantity=100_000.0))

        latest = repo.get_latest_short_interest("AAA", utc(2026, 12, 31))
        assert latest.short_interest_quantity == 100_000.0

        # Before the later report's own available_time, only the earlier one is visible.
        earlier_only = repo.get_latest_short_interest("AAA", utc(2026, 8, 20))
        assert earlier_only.short_interest_quantity == 80_000.0


class TestFiltering:
    def test_filters_by_security_id(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        repo.add_short_interest(_record(record_id="AAA:0", security_id="AAA"))
        repo.add_short_interest(_record(record_id="BBB:0", security_id="BBB"))

        results = repo.get_short_interest_history("AAA", utc(2026, 12, 31))
        assert len(results) == 1
        assert results[0].security_id == "AAA"

    def test_settlement_date_range_filter(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        repo.add_short_interest(_record(record_id="r1", settlement_date=utc(2026, 1, 15), available_time=utc(2026, 1, 26)))
        repo.add_short_interest(_record(record_id="r2", settlement_date=utc(2026, 8, 15), available_time=utc(2026, 8, 26)))

        results = repo.get_short_interest_history(
            "AAA", utc(2026, 12, 31), start=utc(2026, 6, 1), end=utc(2026, 12, 31),
        )
        assert len(results) == 1
        assert results[0].settlement_date == utc(2026, 8, 15)

    def test_results_sorted_by_settlement_date(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        repo.add_short_interest(_record(record_id="r2", settlement_date=utc(2026, 8, 15), available_time=utc(2026, 8, 26)))
        repo.add_short_interest(_record(record_id="r1", settlement_date=utc(2026, 1, 15), available_time=utc(2026, 1, 26)))

        results = repo.get_short_interest_history("AAA", utc(2026, 12, 31))
        assert [r.settlement_date for r in results] == [utc(2026, 1, 15), utc(2026, 8, 15)]

    def test_no_matching_records_returns_none_and_empty_list_not_an_error(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        assert repo.get_latest_short_interest("NOPE", utc(2026, 12, 31)) is None
        assert repo.get_short_interest_history("NOPE", utc(2026, 12, 31)) == []


class TestAwareDatetimeRequirement:
    def test_naive_as_of_time_rejected(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBShortInterestRepository(engine)
        with pytest.raises(ValueError):
            repo.get_latest_short_interest("AAA", datetime(2026, 12, 31))
        with pytest.raises(ValueError):
            repo.get_short_interest_history("AAA", datetime(2026, 12, 31))
