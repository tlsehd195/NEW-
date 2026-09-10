"""Category: ShortInterestRecord schema validation -- mirrors the style
of tests/data_infra/test_insider_models.py, applied to the new FINRA
short-interest model (Session 36 continued, ADR-0099)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from helpers import utc

from data_infra.models import Provenance
from data_infra.short_interest_models import (
    SHORT_INTEREST_DISSEMINATION_LAG_DAYS,
    ShortInterestRecord,
    dissemination_available_time,
)


def _provenance() -> Provenance:
    return Provenance(
        source="finra_manual_export", source_dataset="finra_manual_export_AAA",
        source_record_id="AAA:2026-08-15", retrieved_at=utc(2026, 9, 3), data_version="v1",
    )


def _record(**overrides) -> ShortInterestRecord:
    defaults = dict(
        security_id="AAA",
        settlement_date=utc(2026, 8, 15),
        short_interest_quantity=100_000.0,
        average_daily_volume=50_000.0,
        days_to_cover=2.0,
        available_time=utc(2026, 8, 26),
        ingestion_time=utc(2026, 8, 26),
        provenance=_provenance(),
    )
    defaults.update(overrides)
    return ShortInterestRecord(**defaults)


class TestConstruction:
    def test_valid_record_constructs(self) -> None:
        record = _record()
        assert record.short_interest_quantity == 100_000.0
        assert record.days_to_cover == 2.0

    def test_average_daily_volume_and_days_to_cover_can_both_be_none(self) -> None:
        record = _record(average_daily_volume=None, days_to_cover=None)
        assert record.average_daily_volume is None
        assert record.days_to_cover is None


class TestValidation:
    def test_empty_security_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(security_id="")

    def test_negative_short_interest_quantity_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(short_interest_quantity=-1.0)

    def test_negative_average_daily_volume_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(average_daily_volume=-1.0)

    def test_negative_days_to_cover_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(days_to_cover=-1.0)

    def test_naive_settlement_date_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(settlement_date=datetime(2026, 8, 15))

    def test_naive_available_time_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(available_time=datetime(2026, 8, 26))

    def test_available_time_before_settlement_date_rejected(self) -> None:
        # A report cannot become public before the date its own figures
        # are as of -- the exact leak this field exists to prevent.
        with pytest.raises(ValueError):
            _record(settlement_date=utc(2026, 8, 20), available_time=utc(2026, 8, 15))

    def test_available_time_equal_to_settlement_date_is_allowed(self) -> None:
        record = _record(settlement_date=utc(2026, 8, 15), available_time=utc(2026, 8, 15))
        assert record.available_time == record.settlement_date


class TestDisseminationAvailableTime:
    """FINRA's own published schedule: public dissemination 7 business
    days after settlement date, converted here to a conservative
    calendar-day upper bound (never earlier than the true dissemination
    time -- the only direction of error a point-in-time guard must never
    make)."""

    def test_adds_the_conservative_lag(self) -> None:
        settlement = utc(2026, 8, 15)
        assert dissemination_available_time(settlement) == settlement + timedelta(days=SHORT_INTEREST_DISSEMINATION_LAG_DAYS)

    def test_naive_settlement_date_rejected(self) -> None:
        with pytest.raises(ValueError):
            dissemination_available_time(datetime(2026, 8, 15))
