"""Category 6: Point-in-Time test.
Category 13: As-of query test.

See docs/specifications/PHASE-1-data-infrastructure.md sections 12, 15, 16
and ADR-0004.
"""

from __future__ import annotations

from helpers import make_provenance, utc

from data_infra.models import PriceBar
from data_infra.repository import InMemoryDataRepository


def _bar(day: int, available_day: int, available_hour: int = 20, **overrides) -> PriceBar:
    fields = dict(
        security_id="SEC-AAA",
        timestamp=utc(2024, 1, day),
        open=100.0,
        high=105.0,
        low=99.0,
        close=102.0,
        volume=1000.0,
        available_time=utc(2024, 1, available_day, available_hour),
        ingestion_time=utc(2024, 1, available_day, available_hour),
        provenance=make_provenance(source_record_id=f"rec-{day}"),
    )
    fields.update(overrides)
    return PriceBar(**fields)


class TestPointInTime:
    def test_bar_available_same_day_is_returned_for_as_of_that_evening(self) -> None:
        bar = _bar(day=2, available_day=2, available_hour=20)
        repo = InMemoryDataRepository(bars=[bar])
        result = repo.get_bars(
            "SEC-AAA", utc(2024, 1, 1), utc(2024, 1, 10), as_of_time=utc(2024, 1, 2, 21)
        )
        assert result == [bar]

    def test_bar_not_yet_available_is_hidden_at_query_time(self) -> None:
        # available_time is the day AFTER the bar's own timestamp (e.g. a
        # restated/late-arriving record) — a query as-of the bar's own day
        # must not see it.
        bar = _bar(day=2, available_day=3, available_hour=8)
        repo = InMemoryDataRepository(bars=[bar])
        result = repo.get_bars(
            "SEC-AAA", utc(2024, 1, 1), utc(2024, 1, 10), as_of_time=utc(2024, 1, 2, 23, 59)
        )
        assert result == []

    def test_same_bar_becomes_visible_once_as_of_time_passes_available_time(self) -> None:
        bar = _bar(day=2, available_day=3, available_hour=8)
        repo = InMemoryDataRepository(bars=[bar])
        result = repo.get_bars(
            "SEC-AAA", utc(2024, 1, 1), utc(2024, 1, 10), as_of_time=utc(2024, 1, 3, 9)
        )
        assert result == [bar]


class TestAsOfQuery:
    def test_as_of_time_at_two_different_moments_can_return_different_results(self) -> None:
        early_bar = _bar(day=2, available_day=2, available_hour=20)
        late_arriving_bar = _bar(day=5, available_day=6, available_hour=10)
        repo = InMemoryDataRepository(bars=[early_bar, late_arriving_bar])

        as_of_jan3 = repo.get_bars(
            "SEC-AAA", utc(2024, 1, 1), utc(2024, 1, 10), as_of_time=utc(2024, 1, 3)
        )
        as_of_jan7 = repo.get_bars(
            "SEC-AAA", utc(2024, 1, 1), utc(2024, 1, 10), as_of_time=utc(2024, 1, 7)
        )

        assert as_of_jan3 == [early_bar]
        assert as_of_jan7 == [early_bar, late_arriving_bar]
        # A backtest re-run "as of" the earlier date reproduces the same,
        # smaller result even after later data has since arrived — the
        # core reproducibility invariant (Phase 1 spec section 16).
        assert as_of_jan3 != as_of_jan7

    def test_get_security_as_of_respects_validity_interval(self) -> None:
        from data_infra.enums import InstrumentType, SecurityStatus
        from data_infra.models import SecurityMaster

        old = SecurityMaster(
            security_id="SEC-AAA",
            ticker="OLD",
            exchange="NASDAQ",
            currency="USD",
            company_id="COMP-1",
            instrument_type=InstrumentType.EQUITY,
            valid_from=utc(2020, 1, 1),
            valid_to=utc(2023, 1, 1),
            status=SecurityStatus.RENAMED,
        )
        new = SecurityMaster(
            security_id="SEC-AAA",
            ticker="NEW",
            exchange="NASDAQ",
            currency="USD",
            company_id="COMP-1",
            instrument_type=InstrumentType.EQUITY,
            valid_from=utc(2023, 1, 1),
            status=SecurityStatus.ACTIVE,
        )
        repo = InMemoryDataRepository(securities=[old, new])
        assert repo.get_security("SEC-AAA", utc(2022, 6, 1)).ticker == "OLD"
        assert repo.get_security("SEC-AAA", utc(2023, 6, 1)).ticker == "NEW"

    def test_as_of_time_must_be_timezone_aware(self) -> None:
        import pytest
        from datetime import datetime

        repo = InMemoryDataRepository()
        with pytest.raises(ValueError):
            repo.get_bars("SEC-AAA", utc(2024, 1, 1), utc(2024, 1, 10), as_of_time=datetime(2024, 1, 5))
