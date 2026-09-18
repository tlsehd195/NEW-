"""Category: Twelve Data Provider Test -- `TwelveDataDataProvider.fetch()`
calls `TwelveDataHttpTransport`, always replaced here with a fixture-
returning stub -- never the real network. Tests Protocol conformance
(`fetch`/`validate`/`normalize`/`metadata`, exactly the signature
`IngestionRunner` calls). Success-shape fixture matches a real Twelve
Data response the account owner fetched and pasted back (2026-09-18,
see ADR-0164) -- Tier 1, not invented."""

from __future__ import annotations

import pytest
from helpers import utc

from data_infra.provider import IngestionRunner, PermanentProviderError, TransientProviderError
from data_infra.providers.twelvedata import TwelveDataDataProvider
from data_infra.providers.twelvedata_config import TwelveDataConfig
from data_infra.providers.twelvedata_transport import TwelveDataTransportResponse
from data_infra.repository import InMemoryDataRepository


class _StubTransport:
    def __init__(self, body) -> None:
        self._body = body
        self.calls: list[tuple[str, dict]] = []

    def get(self, path, *, params, timeout):
        self.calls.append((path, params))
        return TwelveDataTransportResponse(status_code=200, body=self._body, headers={})


_VALID_BODY = {
    "meta": {"symbol": "SO", "interval": "1day", "currency": "USD", "exchange": "NYSE"},
    "values": [
        {"datetime": "2024-01-03", "open": "86.41", "high": "86.83", "low": "85.87", "close": "86.23", "volume": "5924100"},
        {"datetime": "2024-01-02", "open": "86.64", "high": "86.79", "low": "86.02", "close": "86.76", "volume": "5314046"},
    ],
}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "test-key-123")


class TestFetch:
    def test_fetch_parses_values_and_stamps_metadata(self) -> None:
        transport = _StubTransport(_VALID_BODY)
        provider = TwelveDataDataProvider(TwelveDataConfig(), transport)
        records = provider.fetch("SO", utc(2024, 1, 1), utc(2024, 1, 4))
        assert len(records) == 2
        assert records[0]["security_id"] == "SO"
        assert records[0]["_fetched_as_of"] == utc(2024, 1, 4)
        assert transport.calls[0][1]["symbol"] == "SO"
        assert transport.calls[0][1]["apikey"] == "test-key-123"

    def test_fetch_raises_permanent_error_on_bad_symbol(self) -> None:
        body = {"code": 400, "message": "**symbol** not found", "status": "error"}
        transport = _StubTransport(body)
        provider = TwelveDataDataProvider(TwelveDataConfig(), transport)
        with pytest.raises(PermanentProviderError):
            provider.fetch("ZZZZINVALID", utc(2024, 1, 1), utc(2024, 1, 4))

    def test_fetch_raises_transient_error_on_rate_limit_body(self) -> None:
        body = {"code": 429, "message": "You have run out of API credits", "status": "error"}
        transport = _StubTransport(body)
        provider = TwelveDataDataProvider(TwelveDataConfig(), transport)
        with pytest.raises(TransientProviderError):
            provider.fetch("SO", utc(2024, 1, 1), utc(2024, 1, 4))

    def test_fetch_raises_permanent_error_on_unexpected_shape(self) -> None:
        transport = _StubTransport({"unexpected": "shape"})
        provider = TwelveDataDataProvider(TwelveDataConfig(), transport)
        with pytest.raises(PermanentProviderError):
            provider.fetch("SO", utc(2024, 1, 1), utc(2024, 1, 4))

    def test_fetch_without_api_key_raises_permanent_error(self, monkeypatch) -> None:
        monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
        transport = _StubTransport(_VALID_BODY)
        provider = TwelveDataDataProvider(TwelveDataConfig(), transport)
        with pytest.raises(PermanentProviderError):
            provider.fetch("SO", utc(2024, 1, 1), utc(2024, 1, 4))


class TestValidate:
    def test_complete_record_has_no_issues(self) -> None:
        provider = TwelveDataDataProvider(TwelveDataConfig(), _StubTransport({}))
        issues = provider.validate([{"datetime": "2024-01-02", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "100"}])
        assert issues == []

    def test_missing_field_is_reported(self) -> None:
        provider = TwelveDataDataProvider(TwelveDataConfig(), _StubTransport({}))
        issues = provider.validate([{"datetime": "2024-01-02", "open": "1"}])
        assert len(issues) == 1


class TestNormalize:
    def test_normalize_produces_raw_bars_with_no_adjusted_close(self) -> None:
        transport = _StubTransport(_VALID_BODY)
        provider = TwelveDataDataProvider(TwelveDataConfig(), transport)
        raw = provider.fetch("SO", utc(2024, 1, 1), utc(2024, 1, 4))
        bars = provider.normalize("SO", raw)
        assert len(bars) == 2
        by_date = {b.timestamp: b for b in bars}
        bar = by_date[utc(2024, 1, 2)]
        assert bar.close == 86.76
        assert bar.adjusted_close is None  # never fabricated -- see module docstring
        assert bar.provenance.source == "twelvedata"
        assert bar.available_time == utc(2024, 1, 2, 20)

    def test_data_version_is_stable_across_different_fetched_as_of_values(self) -> None:
        transport = _StubTransport(_VALID_BODY)
        provider = TwelveDataDataProvider(TwelveDataConfig(), transport)
        raw1 = provider.fetch("SO", utc(2024, 1, 1), utc(2024, 1, 4))
        raw2 = provider.fetch("SO", utc(2024, 1, 1), utc(2024, 6, 1))
        v1 = provider.normalize("SO", [raw1[0]])[0].provenance.data_version
        v2 = provider.normalize("SO", [raw2[0]])[0].provenance.data_version
        assert v1 == v2

    def test_ingestion_runner_end_to_end_with_stub_transport(self) -> None:
        transport = _StubTransport(_VALID_BODY)
        provider = TwelveDataDataProvider(TwelveDataConfig(), transport)
        repo = InMemoryDataRepository()
        runner = IngestionRunner(provider, repo)
        result = runner.run(["SO"], utc(2024, 1, 1), utc(2024, 1, 4))
        assert result.status.value == "SUCCESS"
        assert len(repo.all_bars()) == 2


class TestMetadata:
    def test_metadata_declares_no_corporate_action_support(self) -> None:
        provider = TwelveDataDataProvider(TwelveDataConfig(), _StubTransport({}))
        meta = provider.metadata()
        assert meta["supports_corporate_actions"] is False
        assert meta["provider_id"] == "twelvedata"
