"""Category: FundamentalRecord schema validation -- mirrors the style
of tests/data_infra/test_models.py's PriceBar/CorporateAction tests,
applied to the new fundamentals model (Phase 33, ADR-0042)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from helpers import utc

from data_infra.fundamentals_models import FundamentalRecord
from data_infra.models import Provenance


def _provenance() -> Provenance:
    return Provenance(
        source="sec_edgar", source_dataset="sec_edgar_companyfacts_AAPL",
        source_record_id="AAPL:Revenues:0001", retrieved_at=utc(2024, 1, 1), data_version="v1",
    )


def _record(**overrides) -> FundamentalRecord:
    defaults = dict(
        security_id="AAPL",
        concept="Revenues",
        period_end=utc(2023, 12, 31),
        fiscal_year=2023,
        fiscal_period="FY",
        form_type="10-K",
        value=100.0,
        unit="USD",
        available_time=utc(2024, 2, 1),
        ingestion_time=utc(2024, 2, 1),
        provenance=_provenance(),
    )
    defaults.update(overrides)
    return FundamentalRecord(**defaults)


class TestConstruction:
    def test_valid_record_constructs(self) -> None:
        record = _record()
        assert record.value == 100.0
        assert record.period_start is None  # instant concept, no period_start supplied

    def test_period_start_is_optional_and_can_be_set(self) -> None:
        record = _record(period_start=utc(2023, 1, 1))
        assert record.period_start == utc(2023, 1, 1)


class TestValidation:
    def test_empty_security_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(security_id="")

    def test_empty_concept_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(concept="")

    def test_empty_form_type_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(form_type="")

    def test_naive_period_end_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(period_end=datetime(2023, 12, 31))

    def test_naive_available_time_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(available_time=datetime(2024, 2, 1))

    def test_available_time_before_period_end_rejected(self) -> None:
        # A filing cannot report on a period that had not yet ended --
        # the exact leak this field exists to prevent.
        with pytest.raises(ValueError):
            _record(period_end=utc(2024, 3, 31), available_time=utc(2024, 2, 1))

    def test_available_time_equal_to_period_end_is_allowed(self) -> None:
        record = _record(period_end=utc(2024, 2, 1), available_time=utc(2024, 2, 1))
        assert record.available_time == record.period_end
