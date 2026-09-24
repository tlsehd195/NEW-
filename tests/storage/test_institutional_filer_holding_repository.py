"""Category: persistence, restart, idempotency, point-in-time
look-ahead guard, and multi-filer lookup for
`DuckDBInstitutionalFilerHoldingRepository` (ADR-0194) -- the per-filer
counterpart to `test_institutional_holding_repository.py`. The one
method that file's counterpart doesn't need,
`get_latest_holdings_for_security`, is `guru_consensus_score`'s own
primary read path (one query per security across several tracked
filers at once), so it gets its own dedicated test class below."""

from __future__ import annotations

from datetime import datetime

import pytest
from helpers import utc

from data_infra.institutional_holding_models import InstitutionalFilerHoldingRecord
from data_infra.models import Provenance

from storage.institutional_filer_holding_repository import DuckDBInstitutionalFilerHoldingRepository
from storage_helpers import new_engine


def _provenance(record_id: str, *, retrieved_at=utc(2026, 9, 3)) -> Provenance:
    return Provenance(
        source="sec_13f_tracked_filer_positions", source_dataset="sec_13f_tracked_filer_positions_AAA",
        source_record_id=record_id, retrieved_at=retrieved_at, data_version="v1",
    )


def _record(
    *, record_id="AAA:CIK1:2026-06-30", security_id="AAA", filer_cik="CIK1",
    quarter_end=utc(2026, 6, 30), available_time=utc(2026, 8, 14), shares_held=500_000.0,
) -> InstitutionalFilerHoldingRecord:
    return InstitutionalFilerHoldingRecord(
        security_id=security_id, filer_cik=filer_cik, quarter_end=quarter_end,
        shares_held=shares_held, available_time=available_time, ingestion_time=available_time,
        provenance=_provenance(record_id),
    )


class TestPersistenceAndRestart:
    def test_record_survives_restart(self, tmp_path) -> None:
        engine1 = new_engine(tmp_path)
        DuckDBInstitutionalFilerHoldingRepository(engine1).add_institutional_filer_holding(_record())
        engine1.close()

        engine2 = new_engine(tmp_path)
        result = DuckDBInstitutionalFilerHoldingRepository(engine2).get_latest_institutional_filer_holding("AAA", "CIK1", utc(2026, 12, 31))
        assert result is not None
        assert result.shares_held == 500_000.0
        engine2.close()


class TestIdempotency:
    def test_re_adding_the_identical_record_does_not_duplicate(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        repo.add_institutional_filer_holding(_record())
        repo.add_institutional_filer_holding(_record())
        result = repo.get_latest_holdings_for_security("AAA", ["CIK1"], utc(2026, 12, 31))
        assert len(result) == 1

    def test_add_institutional_filer_holdings_batch_is_also_idempotent(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        repo.add_institutional_filer_holdings([_record(), _record()])
        result = repo.get_latest_holdings_for_security("AAA", ["CIK1"], utc(2026, 12, 31))
        assert len(result) == 1


class TestPointInTimeLookAheadGuard:
    def test_a_report_is_invisible_before_its_own_available_time(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        repo.add_institutional_filer_holding(_record(available_time=utc(2026, 8, 14)))

        before = repo.get_latest_institutional_filer_holding("AAA", "CIK1", utc(2026, 8, 13))
        after = repo.get_latest_institutional_filer_holding("AAA", "CIK1", utc(2026, 8, 14))

        assert before is None
        assert after is not None

    def test_get_latest_holdings_for_security_excludes_not_yet_filed_reports(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        repo.add_institutional_filer_holding(_record(filer_cik="CIK1", available_time=utc(2026, 8, 14)))
        repo.add_institutional_filer_holding(_record(record_id="AAA:CIK2:2026-06-30", filer_cik="CIK2", available_time=utc(2026, 9, 15)))

        result = repo.get_latest_holdings_for_security("AAA", ["CIK1", "CIK2"], utc(2026, 9, 1))
        assert set(result) == {"CIK1"}


class TestGetLatestHoldingsForSecurity:
    def test_one_row_per_filer_at_its_own_most_recent_known_quarter(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        repo.add_institutional_filer_holding(_record(record_id="AAA:CIK1:q1", filer_cik="CIK1", quarter_end=utc(2026, 3, 31), available_time=utc(2026, 5, 15), shares_held=100.0))
        repo.add_institutional_filer_holding(_record(record_id="AAA:CIK1:q2", filer_cik="CIK1", quarter_end=utc(2026, 6, 30), available_time=utc(2026, 8, 14), shares_held=150.0))
        repo.add_institutional_filer_holding(_record(record_id="AAA:CIK2:q1", filer_cik="CIK2", quarter_end=utc(2026, 3, 31), available_time=utc(2026, 5, 15), shares_held=200.0))

        result = repo.get_latest_holdings_for_security("AAA", ["CIK1", "CIK2"], utc(2026, 12, 31))

        assert result["CIK1"].shares_held == 150.0
        assert result["CIK2"].shares_held == 200.0

    def test_a_filer_with_no_report_is_simply_absent(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        repo.add_institutional_filer_holding(_record(filer_cik="CIK1"))

        result = repo.get_latest_holdings_for_security("AAA", ["CIK1", "CIK_UNKNOWN"], utc(2026, 12, 31))
        assert set(result) == {"CIK1"}

    def test_a_different_security_id_is_isolated(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        repo.add_institutional_filer_holding(_record(record_id="AAA:CIK1:q", security_id="AAA", filer_cik="CIK1", shares_held=100.0))
        repo.add_institutional_filer_holding(_record(record_id="BBB:CIK1:q", security_id="BBB", filer_cik="CIK1", shares_held=999.0))

        result = repo.get_latest_holdings_for_security("AAA", ["CIK1"], utc(2026, 12, 31))
        assert result["CIK1"].shares_held == 100.0

    def test_empty_filer_list_returns_empty_dict(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        assert repo.get_latest_holdings_for_security("AAA", [], utc(2026, 12, 31)) == {}


class TestAwareDatetimeRequirement:
    def test_naive_as_of_time_rejected(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInstitutionalFilerHoldingRepository(engine)
        with pytest.raises(ValueError):
            repo.get_latest_institutional_filer_holding("AAA", "CIK1", datetime(2026, 12, 31))
        with pytest.raises(ValueError):
            repo.get_latest_holdings_for_security("AAA", ["CIK1"], datetime(2026, 12, 31))
