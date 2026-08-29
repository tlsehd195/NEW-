"""Category: SEC EDGAR Provider Test -- `SecEdgarFundamentalsProvider`
calls `SecEdgarHttpTransport`, always replaced here with a
fixture-returning stub -- never the real network (Phase 33, ADR-0042,
mirrors test_tiingo_provider.py's identical discipline). Fixture
bodies below are shaped like SEC EDGAR's real, publicly documented
XBRL company-facts response (Tier 2 documentation -- see sec_edgar.py's
own "Honesty about evidence tier" docstring), not arbitrary test data."""

from __future__ import annotations

import pytest
from helpers import utc

from data_infra.provider import PermanentProviderError
from data_infra.providers.sec_edgar import SecEdgarFundamentalsProvider, resolve_cik
from data_infra.providers.sec_edgar_config import SecEdgarConfig
from data_infra.providers.sec_edgar_transport import SecEdgarTransportResponse

_SAMPLE_COMPANY_FACTS = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "us-gaap": {
            "Revenues": {
                "label": "Revenues",
                "units": {
                    "USD": [
                        {
                            "start": "2022-01-01", "end": "2022-12-31", "val": 394328000000,
                            "accn": "0000320193-23-000001", "fy": 2022, "fp": "FY", "form": "10-K", "filed": "2023-02-15",
                        },
                        {
                            "start": "2023-01-01", "end": "2023-03-31", "val": 94836000000,
                            "accn": "0000320193-23-000002", "fy": 2023, "fp": "Q2", "form": "10-Q", "filed": "2023-05-04",
                        },
                        {
                            # Same period, but an 8-K -- must be excluded (only 10-K/10-Q accepted).
                            "start": "2023-01-01", "end": "2023-03-31", "val": 94836000000,
                            "accn": "0000320193-23-000099", "fy": 2023, "fp": "Q2", "form": "8-K", "filed": "2023-05-01",
                        },
                    ]
                },
            },
            "Assets": {
                # Instant concept (balance-sheet item) -- no "start" field, matching real EDGAR shape.
                "label": "Assets",
                "units": {
                    "USD": [
                        {
                            "end": "2022-12-31", "val": 352755000000, "accn": "0000320193-23-000001",
                            "fy": 2022, "fp": "FY", "form": "10-K", "filed": "2023-02-15",
                        },
                    ]
                },
            },
        }
    },
}


def _provider() -> SecEdgarFundamentalsProvider:
    return SecEdgarFundamentalsProvider(SecEdgarConfig(), transport=None)  # transport unused by normalize_company_facts


class TestNormalizeCompanyFacts:
    def test_extracts_records_for_requested_concepts(self) -> None:
        provider = _provider()
        records = provider.normalize_company_facts(
            "AAPL", _SAMPLE_COMPANY_FACTS, ["Revenues", "Assets"],
            retrieved_at=utc(2024, 1, 1), ingestion_time=utc(2024, 1, 1),
        )
        concepts_seen = {r.concept for r in records}
        assert concepts_seen == {"Revenues", "Assets"}

    def test_excludes_non_10k_10q_forms(self) -> None:
        provider = _provider()
        records = provider.normalize_company_facts(
            "AAPL", _SAMPLE_COMPANY_FACTS, ["Revenues"],
            retrieved_at=utc(2024, 1, 1), ingestion_time=utc(2024, 1, 1),
        )
        assert all(r.form_type in ("10-K", "10-Q") for r in records)
        assert len(records) == 2  # the 8-K entry excluded

    def test_available_time_is_the_filed_date_not_the_period_end(self) -> None:
        # The point-in-time-critical property this whole module exists
        # to get right (fundamentals_models.py's own docstring).
        provider = _provider()
        records = provider.normalize_company_facts(
            "AAPL", _SAMPLE_COMPANY_FACTS, ["Revenues"],
            retrieved_at=utc(2024, 1, 1), ingestion_time=utc(2024, 1, 1),
        )
        fy_record = next(r for r in records if r.fiscal_period == "FY")
        assert fy_record.period_end == utc(2022, 12, 31)
        assert fy_record.available_time == utc(2023, 2, 15)  # filed date, weeks after period_end
        assert fy_record.available_time != fy_record.period_end

    def test_instant_concept_has_no_period_start(self) -> None:
        provider = _provider()
        records = provider.normalize_company_facts(
            "AAPL", _SAMPLE_COMPANY_FACTS, ["Assets"],
            retrieved_at=utc(2024, 1, 1), ingestion_time=utc(2024, 1, 1),
        )
        assert records[0].period_start is None

    def test_duration_concept_has_period_start(self) -> None:
        provider = _provider()
        records = provider.normalize_company_facts(
            "AAPL", _SAMPLE_COMPANY_FACTS, ["Revenues"],
            retrieved_at=utc(2024, 1, 1), ingestion_time=utc(2024, 1, 1),
        )
        fy_record = next(r for r in records if r.fiscal_period == "FY")
        assert fy_record.period_start == utc(2022, 1, 1)

    def test_concept_absent_from_filings_yields_no_records_not_an_error(self) -> None:
        provider = _provider()
        records = provider.normalize_company_facts(
            "AAPL", _SAMPLE_COMPANY_FACTS, ["NetIncomeLoss"],  # never reported in this fixture
            retrieved_at=utc(2024, 1, 1), ingestion_time=utc(2024, 1, 1),
        )
        assert records == []

    def test_entry_missing_a_required_field_is_skipped_not_fabricated(self) -> None:
        incomplete = {
            "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
                {"end": "2022-12-31", "fy": 2022, "fp": "FY", "form": "10-K"},  # no "filed", no "val"
            ]}}}}
        }
        provider = _provider()
        records = provider.normalize_company_facts(
            "AAPL", incomplete, ["Revenues"], retrieved_at=utc(2024, 1, 1), ingestion_time=utc(2024, 1, 1),
        )
        assert records == []

    def test_no_facts_key_yields_no_records_not_an_error(self) -> None:
        provider = _provider()
        records = provider.normalize_company_facts(
            "AAPL", {}, ["Revenues"], retrieved_at=utc(2024, 1, 1), ingestion_time=utc(2024, 1, 1),
        )
        assert records == []


class TestFetchCompanyFacts:
    def test_builds_the_correct_zero_padded_cik_path(self) -> None:
        calls = []

        class _StubTransport:
            def get(self, path, *, timeout):
                calls.append(path)
                return SecEdgarTransportResponse(status_code=200, body=_SAMPLE_COMPANY_FACTS, raw_text=None, headers={})

        provider = SecEdgarFundamentalsProvider(SecEdgarConfig(), _StubTransport())
        provider.fetch_company_facts("0000320193")
        assert calls == ["/api/xbrl/companyfacts/CIK0000320193.json"]

    def test_unexpected_shape_raises_permanent_provider_error(self) -> None:
        class _StubTransport:
            def get(self, path, *, timeout):
                return SecEdgarTransportResponse(status_code=200, body=["not", "a", "dict"], raw_text=None, headers={})

        provider = SecEdgarFundamentalsProvider(SecEdgarConfig(), _StubTransport())
        with pytest.raises(PermanentProviderError):
            provider.fetch_company_facts("0000320193")


class TestFetchTickerMap:
    def test_returns_the_parsed_map(self) -> None:
        class _StubTransport:
            def get(self, path, *, timeout):
                return SecEdgarTransportResponse(
                    status_code=200,
                    body={"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}},
                    raw_text=None, headers={},
                )

        provider = SecEdgarFundamentalsProvider(SecEdgarConfig(), transport=None)
        result = provider.fetch_ticker_map(_StubTransport())
        assert result["0"]["ticker"] == "AAPL"

    def test_unexpected_shape_raises_permanent_provider_error(self) -> None:
        class _StubTransport:
            def get(self, path, *, timeout):
                return SecEdgarTransportResponse(status_code=200, body=["not", "a", "dict"], raw_text=None, headers={})

        provider = SecEdgarFundamentalsProvider(SecEdgarConfig(), transport=None)
        with pytest.raises(PermanentProviderError):
            provider.fetch_ticker_map(_StubTransport())


class TestResolveCik:
    _MAP = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
    }

    def test_finds_ticker_and_pads_to_ten_digits(self) -> None:
        assert resolve_cik("AAPL", self._MAP) == "0000320193"

    def test_is_case_insensitive(self) -> None:
        assert resolve_cik("aapl", self._MAP) == "0000320193"

    def test_unknown_ticker_returns_none(self) -> None:
        assert resolve_cik("NOPE", self._MAP) is None


class TestMetadata:
    def test_declares_no_api_key_required(self) -> None:
        provider = SecEdgarFundamentalsProvider(SecEdgarConfig(), transport=None)
        assert provider.metadata()["requires_api_key"] is False
        assert provider.metadata()["is_real_external_provider"] is True
