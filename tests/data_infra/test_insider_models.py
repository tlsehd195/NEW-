"""Category: InsiderTransaction schema validation -- mirrors the style
of tests/data_infra/test_fundamentals_models.py, applied to the new
SEC Form 4 insider-transaction model (Session 36 continued, ADR-0086)."""

from __future__ import annotations

from datetime import datetime

import pytest
from helpers import utc

from data_infra.insider_models import InsiderTransaction
from data_infra.models import Provenance


def _provenance() -> Provenance:
    return Provenance(
        source="sec_edgar", source_dataset="sec_edgar_form4_AAPL",
        source_record_id="0001140361-26-035636:0", retrieved_at=utc(2026, 9, 3), data_version="v1",
    )


def _txn(**overrides) -> InsiderTransaction:
    defaults = dict(
        security_id="AAPL",
        reporting_owner_cik="0001780525",
        reporting_owner_name="Newstead Jennifer",
        is_officer=True,
        is_director=False,
        is_ten_percent_owner=False,
        officer_title="SVP, GC and Government Affairs",
        transaction_date=utc(2026, 9, 1),
        transaction_code="S",
        acquired_disposed_code="D",
        shares=1439.0,
        price_per_share=317.01,
        is_10b5_1_plan=True,
        accession_number="0001140361-26-035636",
        available_time=utc(2026, 9, 3),
        ingestion_time=utc(2026, 9, 3),
        provenance=_provenance(),
    )
    defaults.update(overrides)
    return InsiderTransaction(**defaults)


class TestConstruction:
    def test_valid_transaction_constructs(self) -> None:
        txn = _txn()
        assert txn.shares == 1439.0
        assert txn.is_10b5_1_plan is True

    def test_officer_title_is_optional(self) -> None:
        txn = _txn(officer_title=None, is_officer=False)
        assert txn.officer_title is None

    def test_price_per_share_can_be_none_for_grants(self) -> None:
        txn = _txn(transaction_code="A", acquired_disposed_code="A", price_per_share=None)
        assert txn.price_per_share is None


class TestValidation:
    def test_empty_security_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            _txn(security_id="")

    def test_empty_reporting_owner_cik_rejected(self) -> None:
        with pytest.raises(ValueError):
            _txn(reporting_owner_cik="")

    def test_empty_transaction_code_rejected(self) -> None:
        with pytest.raises(ValueError):
            _txn(transaction_code="")

    def test_invalid_acquired_disposed_code_rejected(self) -> None:
        with pytest.raises(ValueError):
            _txn(acquired_disposed_code="X")

    def test_negative_shares_rejected(self) -> None:
        with pytest.raises(ValueError):
            _txn(shares=-1.0)

    def test_negative_price_per_share_rejected(self) -> None:
        with pytest.raises(ValueError):
            _txn(price_per_share=-1.0)

    def test_naive_transaction_date_rejected(self) -> None:
        with pytest.raises(ValueError):
            _txn(transaction_date=datetime(2026, 9, 1))

    def test_naive_available_time_rejected(self) -> None:
        with pytest.raises(ValueError):
            _txn(available_time=datetime(2026, 9, 3))

    def test_available_time_before_transaction_date_rejected(self) -> None:
        # A filing cannot report a trade that had not yet happened --
        # the exact leak this field exists to prevent (mirrors
        # FundamentalRecord's identical available_time/period_end guard).
        with pytest.raises(ValueError):
            _txn(transaction_date=utc(2026, 9, 5), available_time=utc(2026, 9, 1))

    def test_available_time_equal_to_transaction_date_is_allowed(self) -> None:
        txn = _txn(transaction_date=utc(2026, 9, 1), available_time=utc(2026, 9, 1))
        assert txn.available_time == txn.transaction_date
