"""Category: persistence, restart, idempotency, point-in-time
look-ahead guard, and date-range filtering for
`DuckDBInsiderRepository` (Session 36 continued, ADR-0086). Mirrors
`test_fundamentals_repository.py`'s exact pattern, applied to insider
transactions' own point-in-time-critical field (`available_time` =
real SEC filing date, never `transaction_date`)."""

from __future__ import annotations

from helpers import utc

from data_infra.insider_models import InsiderTransaction
from data_infra.models import Provenance

from storage.insider_repository import DuckDBInsiderRepository
from storage_helpers import new_engine


def _provenance(record_id: str, *, retrieved_at=utc(2026, 9, 3)) -> Provenance:
    return Provenance(
        source="sec_edgar", source_dataset="sec_edgar_form4_AAPL",
        source_record_id=record_id, retrieved_at=retrieved_at, data_version="v1",
    )


def _txn(
    *, record_id="0001140361-26-035636:0", security_id="AAPL",
    transaction_date=utc(2026, 9, 1), available_time=utc(2026, 9, 3),
    transaction_code="S", acquired_disposed_code="D", shares=1439.0,
    price_per_share=317.01, is_10b5_1_plan=True,
) -> InsiderTransaction:
    return InsiderTransaction(
        security_id=security_id, reporting_owner_cik="0001780525",
        reporting_owner_name="Newstead Jennifer", is_officer=True, is_director=False,
        is_ten_percent_owner=False, officer_title="SVP, GC and Government Affairs",
        transaction_date=transaction_date, transaction_code=transaction_code,
        acquired_disposed_code=acquired_disposed_code, shares=shares,
        price_per_share=price_per_share, is_10b5_1_plan=is_10b5_1_plan,
        accession_number="0001140361-26-035636", available_time=available_time,
        ingestion_time=available_time, provenance=_provenance(record_id),
    )


class TestPersistenceAndRestart:
    def test_transaction_survives_restart(self, tmp_path) -> None:
        engine1 = new_engine(tmp_path)
        DuckDBInsiderRepository(engine1).add_insider_transaction(_txn())
        engine1.close()

        engine2 = new_engine(tmp_path)
        results = DuckDBInsiderRepository(engine2).get_insider_transactions("AAPL", utc(2026, 12, 31))
        assert len(results) == 1
        assert results[0].shares == 1439.0
        engine2.close()

    def test_none_price_per_share_round_trips_as_none_not_a_fabricated_value(self, tmp_path) -> None:
        engine1 = new_engine(tmp_path)
        DuckDBInsiderRepository(engine1).add_insider_transaction(
            _txn(transaction_code="A", acquired_disposed_code="A", price_per_share=None)
        )
        engine1.close()

        engine2 = new_engine(tmp_path)
        results = DuckDBInsiderRepository(engine2).get_insider_transactions("AAPL", utc(2026, 12, 31))
        assert results[0].price_per_share is None
        engine2.close()

    def test_none_officer_title_round_trips_as_none(self, tmp_path) -> None:
        engine1 = new_engine(tmp_path)
        record = InsiderTransaction(
            security_id="AAPL", reporting_owner_cik="0001999999", reporting_owner_name="Some Director",
            is_officer=False, is_director=True, is_ten_percent_owner=False, officer_title=None,
            transaction_date=utc(2026, 9, 1), transaction_code="S", acquired_disposed_code="D",
            shares=100.0, price_per_share=50.0, is_10b5_1_plan=False,
            accession_number="0000000000-26-000001", available_time=utc(2026, 9, 3),
            ingestion_time=utc(2026, 9, 3), provenance=_provenance("r1"),
        )
        DuckDBInsiderRepository(engine1).add_insider_transaction(record)
        engine1.close()

        engine2 = new_engine(tmp_path)
        results = DuckDBInsiderRepository(engine2).get_insider_transactions("AAPL", utc(2026, 12, 31))
        assert results[0].officer_title is None
        engine2.close()


class TestIdempotency:
    def test_re_adding_the_identical_transaction_does_not_duplicate(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        repo.add_insider_transaction(_txn())
        repo.add_insider_transaction(_txn())  # same provenance_source_record_id
        assert len(repo.get_insider_transactions("AAPL", utc(2026, 12, 31))) == 1

    def test_add_insider_transactions_batch_is_also_idempotent(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        repo.add_insider_transactions([_txn(), _txn()])
        assert len(repo.get_insider_transactions("AAPL", utc(2026, 12, 31))) == 1

    def test_two_distinct_rows_from_the_same_filing_both_survive(self, tmp_path) -> None:
        # A single Form 4 filing routinely reports more than one
        # transaction row -- distinct row_index in source_record_id
        # must not collide onto the same natural key.
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        repo.add_insider_transaction(_txn(record_id="0001140361-26-035636:0", shares=100.0))
        repo.add_insider_transaction(_txn(record_id="0001140361-26-035636:1", shares=200.0))
        assert len(repo.get_insider_transactions("AAPL", utc(2026, 12, 31))) == 2


class TestPointInTimeLookAheadGuard:
    def test_a_transaction_is_invisible_before_its_own_available_time(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        repo.add_insider_transaction(_txn(available_time=utc(2026, 9, 3)))

        before_filing = repo.get_insider_transactions("AAPL", utc(2026, 9, 2))
        after_filing = repo.get_insider_transactions("AAPL", utc(2026, 9, 3))

        assert before_filing == []
        assert len(after_filing) == 1


class TestFiltering:
    def test_filters_by_security_id(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        repo.add_insider_transaction(_txn(record_id="AAPL:0", security_id="AAPL"))
        repo.add_insider_transaction(_txn(record_id="MSFT:0", security_id="MSFT"))

        results = repo.get_insider_transactions("AAPL", utc(2026, 12, 31))
        assert len(results) == 1
        assert results[0].security_id == "AAPL"

    def test_transaction_date_range_filter(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        repo.add_insider_transaction(_txn(record_id="r1", transaction_date=utc(2026, 1, 1), available_time=utc(2026, 1, 3)))
        repo.add_insider_transaction(_txn(record_id="r2", transaction_date=utc(2026, 9, 1), available_time=utc(2026, 9, 3)))

        results = repo.get_insider_transactions(
            "AAPL", utc(2026, 12, 31), start=utc(2026, 6, 1), end=utc(2026, 12, 31),
        )
        assert len(results) == 1
        assert results[0].transaction_date == utc(2026, 9, 1)

    def test_results_sorted_by_transaction_date(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        repo.add_insider_transaction(_txn(record_id="r2", transaction_date=utc(2026, 9, 1), available_time=utc(2026, 9, 3)))
        repo.add_insider_transaction(_txn(record_id="r1", transaction_date=utc(2026, 1, 1), available_time=utc(2026, 1, 3)))

        results = repo.get_insider_transactions("AAPL", utc(2026, 12, 31))
        assert [r.transaction_date for r in results] == [utc(2026, 1, 1), utc(2026, 9, 1)]

    def test_no_matching_transactions_returns_empty_list_not_an_error(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        assert repo.get_insider_transactions("NOPE", utc(2026, 12, 31)) == []


class TestAwareDatetimeRequirement:
    def test_naive_as_of_time_rejected(self, tmp_path) -> None:
        from datetime import datetime as naive_datetime

        engine = new_engine(tmp_path)
        repo = DuckDBInsiderRepository(engine)
        import pytest

        with pytest.raises(ValueError):
            repo.get_insider_transactions("AAPL", naive_datetime(2026, 12, 31))
