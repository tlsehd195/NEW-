"""Category: persistence, restart, idempotency, point-in-time
look-ahead guard, and date-range filtering for
`DuckDBInstitutionalHoldingRepository` (Session 36 continued, ADR-0104).
Mirrors `test_short_interest_repository.py`'s exact pattern, applied to
aggregate Form 13F institutional holdings' own point-in-time-critical
field (`available_time` = SEC Rule 13f-1's 45-day filing deadline,
never `quarter_end`)."""

from __future__ import annotations

from datetime import datetime

import pytest
from helpers import utc

from data_infra.institutional_holding_models import InstitutionalHoldingRecord
from data_infra.models import Provenance

from storage.institutional_holding_repository import DuckDBInstitutionalHoldingRepository
from storage_helpers import new_engine


def _provenance(record_id: str, *, retrieved_at=utc(2026, 9, 3)) -> Provenance:
    return Provenance(
        source="sec_13f_manual_aggregation", source_dataset="sec_13f_manual_aggregation_AAA",
        source_record_id=record_id, retrieved_at=retrieved_at, data_version="v1",
    )


def _record(
    *, record_id="AAA:2026-06-30", security_id="AAA",
    quarter_end=utc(2026, 6, 30), available_time=utc(2026, 8, 14),
    institutional_shares=1_000_000.0, num_institutions=42,
) -> InstitutionalHoldingRecord:
    return InstitutionalHoldingRecord(
        security_id=security_id, quarter_end=quarter_end,
        institutional_shares=institutional_shares, num_institutions=num_institutions,
        available_time=available_time, ingestion_time=available_time,
        provenance=_provenance(record_id),
    )


class TestPersistenceAndRestart:
    def test_record_survives_restart(self, tmp_path) -> None:
        engine1 = new_engine(tmp_path)
        DuckDBInstitutionalHoldingRepository(engine1).add_institutional_holding(_record())
        engine1.close()

        engine2 = new_engine(tmp_path)
        result = DuckDBInstitutionalHoldingRepository(engine2).get_latest_institutional_holding("AAA", utc(2026, 12, 31))
        assert result is not None
        assert result.institutional_shares == 1_000_000.0
        engine2.close()

    def test_none_num_institutions_round_trips_as_none(self, tmp_path) -> None:
        engine1 = new_engine(tmp_path)
        DuckDBInstitutionalHoldingRepository(engine1).add_institutional_holding(_record(num_institutions=None))
        engine1.close()

        engine2 = new_engine(tmp_path)
        result = DuckDBInstitutionalHoldingRepository(engine2).get_latest_institutional_holding("AAA", utc(2026, 12, 31))
        assert result.num_institutions is None
        engine2.close()


class TestIdempotency:
    def test_re_adding_the_identical_record_does_not_duplicate(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        repo.add_institutional_holding(_record())
        repo.add_institutional_holding(_record())  # same provenance_source_record_id
        assert len(repo.get_institutional_holding_history("AAA", utc(2026, 12, 31))) == 1

    def test_add_institutional_holdings_batch_is_also_idempotent(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        repo.add_institutional_holdings([_record(), _record()])
        assert len(repo.get_institutional_holding_history("AAA", utc(2026, 12, 31))) == 1

    def test_two_distinct_quarters_both_survive(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        repo.add_institutional_holding(_record(record_id="AAA:2026-03-31", quarter_end=utc(2026, 3, 31), available_time=utc(2026, 5, 15), institutional_shares=800_000.0))
        repo.add_institutional_holding(_record(record_id="AAA:2026-06-30", quarter_end=utc(2026, 6, 30), available_time=utc(2026, 8, 14), institutional_shares=1_000_000.0))
        assert len(repo.get_institutional_holding_history("AAA", utc(2026, 12, 31))) == 2


class TestPointInTimeLookAheadGuard:
    def test_a_report_is_invisible_before_its_own_available_time(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        repo.add_institutional_holding(_record(available_time=utc(2026, 8, 14)))

        before_filing_deadline = repo.get_latest_institutional_holding("AAA", utc(2026, 8, 13))
        after_filing_deadline = repo.get_latest_institutional_holding("AAA", utc(2026, 8, 14))

        assert before_filing_deadline is None
        assert after_filing_deadline is not None

    def test_get_latest_returns_the_most_recent_available_quarter(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        repo.add_institutional_holding(_record(record_id="AAA:2026-03-31", quarter_end=utc(2026, 3, 31), available_time=utc(2026, 5, 15), institutional_shares=800_000.0))
        repo.add_institutional_holding(_record(record_id="AAA:2026-06-30", quarter_end=utc(2026, 6, 30), available_time=utc(2026, 8, 14), institutional_shares=1_000_000.0))

        latest = repo.get_latest_institutional_holding("AAA", utc(2026, 12, 31))
        assert latest.institutional_shares == 1_000_000.0

        # Before the later report's own available_time, only the earlier one is visible.
        earlier_only = repo.get_latest_institutional_holding("AAA", utc(2026, 6, 1))
        assert earlier_only.institutional_shares == 800_000.0


class TestFiltering:
    def test_filters_by_security_id(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        repo.add_institutional_holding(_record(record_id="AAA:0", security_id="AAA"))
        repo.add_institutional_holding(_record(record_id="BBB:0", security_id="BBB"))

        results = repo.get_institutional_holding_history("AAA", utc(2026, 12, 31))
        assert len(results) == 1
        assert results[0].security_id == "AAA"

    def test_quarter_end_range_filter(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        repo.add_institutional_holding(_record(record_id="r1", quarter_end=utc(2026, 3, 31), available_time=utc(2026, 5, 15)))
        repo.add_institutional_holding(_record(record_id="r2", quarter_end=utc(2026, 6, 30), available_time=utc(2026, 8, 14)))

        results = repo.get_institutional_holding_history(
            "AAA", utc(2026, 12, 31), start=utc(2026, 5, 1), end=utc(2026, 12, 31),
        )
        assert len(results) == 1
        assert results[0].quarter_end == utc(2026, 6, 30)

    def test_results_sorted_by_quarter_end(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        repo.add_institutional_holding(_record(record_id="r2", quarter_end=utc(2026, 6, 30), available_time=utc(2026, 8, 14)))
        repo.add_institutional_holding(_record(record_id="r1", quarter_end=utc(2026, 3, 31), available_time=utc(2026, 5, 15)))

        results = repo.get_institutional_holding_history("AAA", utc(2026, 12, 31))
        assert [r.quarter_end for r in results] == [utc(2026, 3, 31), utc(2026, 6, 30)]

    def test_no_matching_records_returns_none_and_empty_list_not_an_error(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        assert repo.get_latest_institutional_holding("NOPE", utc(2026, 12, 31)) is None
        assert repo.get_institutional_holding_history("NOPE", utc(2026, 12, 31)) == []


class TestAwareDatetimeRequirement:
    def test_naive_as_of_time_rejected(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalHoldingRepository(engine)
        with pytest.raises(ValueError):
            repo.get_latest_institutional_holding("AAA", datetime(2026, 12, 31))
        with pytest.raises(ValueError):
            repo.get_institutional_holding_history("AAA", datetime(2026, 12, 31))
