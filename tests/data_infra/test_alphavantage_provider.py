"""Category: Alpha Vantage Provider Test -- `AlphaVantageDataProvider.
fetch()` calls `AlphaVantageHttpTransport`, always replaced here with a
fixture-returning stub -- never the real network. Tests Protocol
conformance (`fetch`/`validate`/`normalize`/`metadata`, exactly the
signature `IngestionRunner` calls). Success-shape fixture matches a
real Alpha Vantage response the account owner fetched and pasted back
(2026-09-18, see ADR-0164) -- Tier 1, not invented."""

from __future__ import annotations

import pytest
from helpers import utc

from data_infra.provider import IngestionRunner, PermanentProviderError, TransientProviderError
from data_infra.providers.alphavantage import AlphaVantageDataProvider
from data_infra.providers.alphavantage_config import AlphaVantageConfig
from data_infra.providers.alphavantage_transport import AlphaVantageTransportResponse
from data_infra.repository import InMemoryDataRepository


class _StubTransport:
    def __init__(self, body) -> None:
        self._body = body
        self.calls: list[tuple[str, dict]] = []

    def get(self, path, *, params, timeout):
        self.calls.append((path, params))
        return AlphaVantageTransportResponse(status_code=200, body=self._body, headers={})


_VALID_BODY = {
    "Meta Data": {"1. Information": "Daily Prices", "2. Symbol": "SO"},
    "Time Series (Daily)": {
        "2024-01-03": {"1. open": "86.41", "2. high": "86.83", "3. low": "85.87", "4. close": "86.23", "5. volume": "5924100"},
        "2024-01-02": {"1. open": "86.64", "2. high": "86.79", "3. low": "86.02", "4. close": "86.76", "5. volume": "5314046"},
        "2023-06-01": {"1. open": "70.00", "2. high": "71.00", "3. low": "69.50", "4. close": "70.50", "5. volume": "1000000"},
    },
}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "test-key-123")


class TestFetch:
    def test_fetch_parses_and_filters_to_requested_range(self) -> None:
        transport = _StubTransport(_VALID_BODY)
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        records = provider.fetch("SO", utc(2024, 1, 1), utc(2024, 1, 4))
        # the 2023-06-01 row is present in the fixture (this test's stub
        # transport doesn't care what outputsize is requested, only real
        # Alpha Vantage does) but must be filtered out here -- see module
        # docstring's "No native date-range query parameter"
        assert len(records) == 2
        assert {r["datetime"] for r in records} == {"2024-01-02", "2024-01-03"}
        assert records[0]["security_id"] == "SO"
        # ADR-0164 follow-up correction: "full" is a real, confirmed
        # paid-only feature on this endpoint -- "compact" is the only
        # option the free tier actually serves.
        assert transport.calls[0][1]["outputsize"] == "compact"
        assert transport.calls[0][1]["apikey"] == "test-key-123"

    def test_fetch_raises_permanent_error_on_bad_symbol(self) -> None:
        transport = _StubTransport({"Error Message": "Invalid API call"})
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        with pytest.raises(PermanentProviderError):
            provider.fetch("ZZZZINVALID", utc(2024, 1, 1), utc(2024, 1, 4))

    def test_fetch_raises_transient_error_on_rate_limit_note(self) -> None:
        transport = _StubTransport({"Note": "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day"})
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        with pytest.raises(TransientProviderError):
            provider.fetch("SO", utc(2024, 1, 1), utc(2024, 1, 4))

    def test_fetch_raises_transient_error_on_rate_limit_information(self) -> None:
        transport = _StubTransport({"Information": "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day"})
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        with pytest.raises(TransientProviderError):
            provider.fetch("SO", utc(2024, 1, 1), utc(2024, 1, 4))

    def test_fetch_raises_permanent_error_on_unexpected_shape(self) -> None:
        transport = _StubTransport({"unexpected": "shape"})
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        with pytest.raises(PermanentProviderError):
            provider.fetch("SO", utc(2024, 1, 1), utc(2024, 1, 4))

    def test_fetch_without_api_key_raises_permanent_error(self, monkeypatch) -> None:
        monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
        transport = _StubTransport(_VALID_BODY)
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        with pytest.raises(PermanentProviderError):
            provider.fetch("SO", utc(2024, 1, 1), utc(2024, 1, 4))


class TestValidate:
    def test_complete_record_has_no_issues(self) -> None:
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), _StubTransport({}))
        issues = provider.validate([{"1. open": "1", "2. high": "2", "3. low": "0.5", "4. close": "1.5", "5. volume": "100"}])
        assert issues == []

    def test_missing_field_is_reported(self) -> None:
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), _StubTransport({}))
        issues = provider.validate([{"1. open": "1"}])
        assert len(issues) == 1


class TestNormalize:
    def test_normalize_produces_raw_bars_with_no_adjusted_close(self) -> None:
        transport = _StubTransport(_VALID_BODY)
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        raw = provider.fetch("SO", utc(2024, 1, 1), utc(2024, 1, 4))
        bars = provider.normalize("SO", raw)
        assert len(bars) == 2
        by_date = {b.timestamp: b for b in bars}
        bar = by_date[utc(2024, 1, 2)]
        assert bar.close == 86.76
        assert bar.adjusted_close is None  # never fabricated -- see module docstring
        assert bar.provenance.source == "alphavantage"
        assert bar.available_time == utc(2024, 1, 2, 20)

    def test_data_version_is_stable_across_different_fetched_as_of_values(self) -> None:
        transport = _StubTransport(_VALID_BODY)
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        raw1 = provider.fetch("SO", utc(2024, 1, 1), utc(2024, 1, 4))
        raw2 = provider.fetch("SO", utc(2024, 1, 1), utc(2024, 6, 1))
        v1 = provider.normalize("SO", [r for r in raw1 if r["datetime"] == "2024-01-02"])[0].provenance.data_version
        v2 = provider.normalize("SO", [r for r in raw2 if r["datetime"] == "2024-01-02"])[0].provenance.data_version
        assert v1 == v2

    def test_ingestion_runner_end_to_end_with_stub_transport(self) -> None:
        transport = _StubTransport(_VALID_BODY)
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        repo = InMemoryDataRepository()
        runner = IngestionRunner(provider, repo)
        result = runner.run(["SO"], utc(2024, 1, 1), utc(2024, 1, 4))
        assert result.status.value == "SUCCESS"
        assert len(repo.all_bars()) == 2


class TestMetadata:
    def test_metadata_declares_no_corporate_action_support(self) -> None:
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), _StubTransport({}))
        meta = provider.metadata()
        assert meta["supports_corporate_actions"] is False
        assert meta["provider_id"] == "alphavantage"
