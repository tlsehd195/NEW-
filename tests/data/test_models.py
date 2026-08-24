"""Category 1: Schema validation.
Category 4: Timestamp test.
Category 5: Timezone test.

See docs/specifications/PHASE-1-data-infrastructure.md section 14.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from helpers import make_provenance, utc

from data_infra.enums import InstrumentType, SecurityStatus
from data_infra.models import PriceBar, SecurityMaster


def _bar(**overrides) -> PriceBar:
    fields = dict(
        security_id="SEC-AAA",
        timestamp=utc(2024, 1, 2),
        open=100.0,
        high=105.0,
        low=99.0,
        close=102.0,
        volume=1000.0,
        available_time=utc(2024, 1, 2, 20),
        ingestion_time=utc(2024, 1, 2, 20),
        provenance=make_provenance(),
    )
    fields.update(overrides)
    return PriceBar(**fields)


class TestSchemaValidation:
    def test_valid_bar_constructs(self) -> None:
        bar = _bar()
        assert bar.security_id == "SEC-AAA"
        assert bar.close == 102.0

    def test_missing_security_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            _bar(security_id="")

    def test_security_master_requires_security_id(self) -> None:
        with pytest.raises(ValueError):
            SecurityMaster(
                security_id="",
                ticker="AAA",
                exchange="NASDAQ",
                currency="USD",
                company_id="COMP-1",
                instrument_type=InstrumentType.EQUITY,
                valid_from=utc(2020, 1, 1),
                status=SecurityStatus.ACTIVE,
            )

    def test_security_master_valid_to_must_be_after_valid_from(self) -> None:
        with pytest.raises(ValueError):
            SecurityMaster(
                security_id="SEC-AAA",
                ticker="AAA",
                exchange="NASDAQ",
                currency="USD",
                company_id="COMP-1",
                instrument_type=InstrumentType.EQUITY,
                valid_from=utc(2020, 1, 1),
                valid_to=utc(2019, 1, 1),
                status=SecurityStatus.ACTIVE,
            )


class TestTimestamps:
    def test_naive_timestamp_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            _bar(timestamp=datetime(2024, 1, 2))  # naive, no tzinfo

    def test_naive_available_time_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            _bar(available_time=datetime(2024, 1, 2, 20))

    def test_available_time_before_publication_time_rejected(self) -> None:
        with pytest.raises(ValueError, match="ADR-0004"):
            _bar(
                available_time=utc(2024, 1, 2, 8),
                publication_time=utc(2024, 1, 2, 9),
            )

    def test_available_time_after_publication_time_accepted(self) -> None:
        bar = _bar(
            available_time=utc(2024, 1, 2, 9, 30),
            publication_time=utc(2024, 1, 2, 9),
        )
        assert bar.available_time > bar.publication_time


class TestTimezone:
    def test_naive_datetime_anywhere_is_rejected_not_assumed_utc(self) -> None:
        # A naive datetime must never be silently treated as UTC —
        # it must fail loudly (Phase 1 spec section 10).
        with pytest.raises(ValueError):
            _bar(ingestion_time=datetime(2024, 1, 2, 20))

    def test_security_master_is_valid_at_respects_tz_aware_boundaries(self) -> None:
        sec = SecurityMaster(
            security_id="SEC-AAA",
            ticker="AAA",
            exchange="NASDAQ",
            currency="USD",
            company_id="COMP-1",
            instrument_type=InstrumentType.EQUITY,
            valid_from=utc(2020, 1, 1),
            valid_to=utc(2024, 1, 1),
            status=SecurityStatus.RENAMED,
        )
        assert sec.is_valid_at(utc(2023, 12, 31)) is True
        assert sec.is_valid_at(utc(2024, 1, 1)) is False  # half-open interval
        assert sec.is_valid_at(utc(2019, 12, 31)) is False

    def test_is_valid_at_rejects_naive_query_time(self) -> None:
        sec = SecurityMaster(
            security_id="SEC-AAA",
            ticker="AAA",
            exchange="NASDAQ",
            currency="USD",
            company_id="COMP-1",
            instrument_type=InstrumentType.EQUITY,
            valid_from=utc(2020, 1, 1),
            status=SecurityStatus.ACTIVE,
        )
        with pytest.raises(ValueError):
            sec.is_valid_at(datetime(2021, 1, 1))
