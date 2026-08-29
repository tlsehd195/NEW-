"""Category: persistence, restart, idempotency, point-in-time
look-ahead guard for `DuckDBFundamentalsRepository` (Phase 33,
ADR-0042). Mirrors `test_regime_repository.py`'s restart-survival
pattern and `DuckDBDataRepository`'s existing look-ahead-guard test
style, applied to fundamentals data's own point-in-time-critical field
(`available_time` = actual filing date, never `period_end`)."""

from __future__ import annotations

from helpers import utc

from data_infra.fundamentals_models import FundamentalRecord
from data_infra.models import Provenance

from storage.engine import StorageEngine
from storage.fundamentals_repository import DuckDBFundamentalsRepository
from storage_helpers import new_engine


def _provenance(record_id: str, *, retrieved_at=utc(2024, 1, 1)) -> Provenance:
    return Provenance(
        source="sec_edgar", source_dataset="sec_edgar_companyfacts_AAPL",
        source_record_id=record_id, retrieved_at=retrieved_at, data_version="v1",
    )


def _record(
    *, record_id="AAPL:Revenues:0001", period_end=utc(2023, 12, 31),
    available_time=utc(2024, 2, 15), value=100.0, concept="Revenues", security_id="AAPL",
) -> FundamentalRecord:
    return FundamentalRecord(
        security_id=security_id, concept=concept, period_end=period_end, fiscal_year=2023,
        fiscal_period="FY", form_type="10-K", value=value, unit="USD",
        available_time=available_time, ingestion_time=available_time,
        provenance=_provenance(record_id),
    )


class TestPersistenceAndRestart:
    def test_record_survives_restart(self, tmp_path) -> None:
        engine1 = new_engine(tmp_path)
        DuckDBFundamentalsRepository(engine1).add_fundamental(_record())
        engine1.close()

        engine2 = new_engine(tmp_path)
        records = DuckDBFundamentalsRepository(engine2).all_fundamentals()
        assert len(records) == 1
        assert records[0].value == 100.0
        engine2.close()

    def test_none_period_start_round_trips_as_none_not_a_fabricated_date(self, tmp_path) -> None:
        # An instant concept (e.g. Assets) legitimately has no
        # period_start -- DuckDB NULL must come back as None, not 1970
        # epoch or some other silently-fabricated placeholder.
        engine1 = new_engine(tmp_path)
        DuckDBFundamentalsRepository(engine1).add_fundamental(_record(concept="Assets"))
        engine1.close()

        engine2 = new_engine(tmp_path)
        records = DuckDBFundamentalsRepository(engine2).all_fundamentals()
        assert records[0].period_start is None
        engine2.close()

    def test_set_period_start_round_trips_correctly(self, tmp_path) -> None:
        engine1 = new_engine(tmp_path)
        record = FundamentalRecord(
            security_id="AAPL", concept="Revenues", period_start=utc(2023, 1, 1),
            period_end=utc(2023, 12, 31), fiscal_year=2023, fiscal_period="FY",
            form_type="10-K", value=100.0, unit="USD", available_time=utc(2024, 2, 15),
            ingestion_time=utc(2024, 2, 15), provenance=_provenance("r1"),
        )
        DuckDBFundamentalsRepository(engine1).add_fundamental(record)
        engine1.close()

        engine2 = new_engine(tmp_path)
        records = DuckDBFundamentalsRepository(engine2).all_fundamentals()
        assert records[0].period_start == utc(2023, 1, 1)
        engine2.close()


class TestIdempotency:
    def test_re_adding_the_identical_record_does_not_duplicate(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_record())
        repo.add_fundamental(_record())  # same provenance_source_record_id
        assert len(repo.all_fundamentals()) == 1

    def test_add_fundamentals_batch_is_also_idempotent(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamentals([_record(), _record()])
        assert len(repo.all_fundamentals()) == 1


class TestPointInTimeLookAheadGuard:
    def test_a_record_is_invisible_before_its_own_available_time(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_record(available_time=utc(2024, 2, 15)))

        before_filing = repo.get_fundamentals("AAPL", "Revenues", as_of_time=utc(2024, 2, 1))
        after_filing = repo.get_fundamentals("AAPL", "Revenues", as_of_time=utc(2024, 2, 15))

        assert before_filing == []
        assert len(after_filing) == 1

    def test_latest_known_value_also_respects_the_guard(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_record(available_time=utc(2024, 2, 15), value=100.0))

        assert repo.latest_known_value("AAPL", "Revenues", as_of_time=utc(2024, 2, 1)) is None
        result = repo.latest_known_value("AAPL", "Revenues", as_of_time=utc(2024, 2, 15))
        assert result is not None and result.value == 100.0


class TestGetFundamentalsFiltering:
    def test_filters_by_security_and_concept(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_record(record_id="AAPL:Revenues:1", security_id="AAPL", concept="Revenues"))
        repo.add_fundamental(_record(record_id="AAPL:Assets:1", security_id="AAPL", concept="Assets"))
        repo.add_fundamental(_record(record_id="MSFT:Revenues:1", security_id="MSFT", concept="Revenues"))

        results = repo.get_fundamentals("AAPL", "Revenues", as_of_time=utc(2025, 1, 1))
        assert len(results) == 1
        assert results[0].security_id == "AAPL" and results[0].concept == "Revenues"

    def test_period_end_range_filter(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_record(record_id="r1", period_end=utc(2022, 12, 31), available_time=utc(2023, 2, 1)))
        repo.add_fundamental(_record(record_id="r2", period_end=utc(2023, 12, 31), available_time=utc(2024, 2, 1)))

        results = repo.get_fundamentals(
            "AAPL", "Revenues", as_of_time=utc(2025, 1, 1), start=utc(2023, 1, 1), end=utc(2023, 12, 31),
        )
        assert len(results) == 1
        assert results[0].period_end == utc(2023, 12, 31)

    def test_results_sorted_by_period_end(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_record(record_id="r2", period_end=utc(2023, 12, 31), available_time=utc(2024, 2, 1)))
        repo.add_fundamental(_record(record_id="r1", period_end=utc(2022, 12, 31), available_time=utc(2023, 2, 1)))

        results = repo.get_fundamentals("AAPL", "Revenues", as_of_time=utc(2025, 1, 1))
        assert [r.period_end for r in results] == [utc(2022, 12, 31), utc(2023, 12, 31)]

    def test_no_matching_records_returns_empty_list_not_an_error(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        assert repo.get_fundamentals("NOPE", "Revenues", as_of_time=utc(2025, 1, 1)) == []


class TestLatestKnownValue:
    def test_picks_the_highest_period_end_among_visible_records(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_record(record_id="r1", period_end=utc(2022, 12, 31), available_time=utc(2023, 2, 1), value=90.0))
        repo.add_fundamental(_record(record_id="r2", period_end=utc(2023, 12, 31), available_time=utc(2024, 2, 1), value=100.0))

        result = repo.latest_known_value("AAPL", "Revenues", as_of_time=utc(2025, 1, 1))
        assert result is not None and result.value == 100.0

    def test_a_not_yet_filed_later_period_never_wins_even_though_its_period_end_is_higher(self, tmp_path) -> None:
        # The whole point of this method: "latest known", not "latest
        # period" -- a not-yet-filed FY2024 figure must never surface
        # just because FY2024 > FY2023 chronologically.
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_record(record_id="r1", period_end=utc(2023, 12, 31), available_time=utc(2024, 2, 1), value=100.0))
        repo.add_fundamental(_record(record_id="r2", period_end=utc(2024, 12, 31), available_time=utc(2025, 2, 1), value=110.0))

        result = repo.latest_known_value("AAPL", "Revenues", as_of_time=utc(2024, 6, 1))
        assert result is not None and result.value == 100.0  # the 2024 figure isn't filed yet as of this as_of_time

    def test_restated_figure_for_the_same_period_wins_by_later_filing_date(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_record(record_id="r1", period_end=utc(2023, 12, 31), available_time=utc(2024, 2, 1), value=100.0))
        # A later 10-K/A restating the same period -- higher available_time, same period_end.
        repo.add_fundamental(_record(record_id="r1_restated", period_end=utc(2023, 12, 31), available_time=utc(2024, 6, 1), value=105.0))

        result = repo.latest_known_value("AAPL", "Revenues", as_of_time=utc(2025, 1, 1))
        assert result is not None and result.value == 105.0

    def test_no_matching_records_returns_none_not_a_fabricated_value(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        assert repo.latest_known_value("NOPE", "Revenues", as_of_time=utc(2025, 1, 1)) is None
