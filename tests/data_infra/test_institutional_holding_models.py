"""Category: InstitutionalHoldingRecord schema validation -- mirrors
the style of tests/data_infra/test_short_interest_models.py, applied to
the new SEC Form 13F aggregate institutional holdings model (Session 36
continued, ADR-0104)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from helpers import utc

from data_infra.institutional_holding_models import (
    THIRTEEN_F_FILING_DEADLINE_DAYS,
    InstitutionalHoldingRecord,
    thirteen_f_available_time,
)
from data_infra.models import Provenance


def _provenance() -> Provenance:
    return Provenance(
        source="sec_13f_manual_aggregation", source_dataset="sec_13f_manual_aggregation_AAA",
        source_record_id="AAA:2026-06-30", retrieved_at=utc(2026, 9, 3), data_version="v1",
    )


def _record(**overrides) -> InstitutionalHoldingRecord:
    defaults = dict(
        security_id="AAA",
        quarter_end=utc(2026, 6, 30),
        institutional_shares=1_000_000.0,
        num_institutions=42,
        available_time=utc(2026, 8, 14),
        ingestion_time=utc(2026, 8, 14),
        provenance=_provenance(),
    )
    defaults.update(overrides)
    return InstitutionalHoldingRecord(**defaults)


class TestConstruction:
    def test_valid_record_constructs(self) -> None:
        record = _record()
        assert record.institutional_shares == 1_000_000.0
        assert record.num_institutions == 42

    def test_num_institutions_can_be_none(self) -> None:
        record = _record(num_institutions=None)
        assert record.num_institutions is None


class TestValidation:
    def test_empty_security_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(security_id="")

    def test_negative_institutional_shares_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(institutional_shares=-1.0)

    def test_negative_num_institutions_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(num_institutions=-1)

    def test_naive_quarter_end_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(quarter_end=datetime(2026, 6, 30))

    def test_naive_available_time_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(available_time=datetime(2026, 8, 14))

    def test_available_time_before_quarter_end_rejected(self) -> None:
        # A quarter's aggregate position cannot become public before the
        # date it is as of -- the exact leak this field exists to prevent.
        with pytest.raises(ValueError):
            _record(quarter_end=utc(2026, 6, 30), available_time=utc(2026, 6, 1))

    def test_available_time_equal_to_quarter_end_is_allowed(self) -> None:
        record = _record(quarter_end=utc(2026, 6, 30), available_time=utc(2026, 6, 30))
        assert record.available_time == record.quarter_end


class TestThirteenFAvailableTime:
    """SEC Rule 13f-1's own hard 45-calendar-day filing deadline after
    each quarter's end -- a real regulatory deadline, not an estimated
    dissemination schedule."""

    def test_adds_the_filing_deadline(self) -> None:
        quarter_end = utc(2026, 6, 30)
        assert thirteen_f_available_time(quarter_end) == quarter_end + timedelta(days=THIRTEEN_F_FILING_DEADLINE_DAYS)

    def test_naive_quarter_end_rejected(self) -> None:
        with pytest.raises(ValueError):
            thirteen_f_available_time(datetime(2026, 6, 30))
