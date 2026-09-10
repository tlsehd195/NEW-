"""Category: Stooq Provider Test -- `StooqDataProvider.fetch()` calls
`StooqHttpTransport`, always replaced here with a fixture-returning
stub -- never the real network. Tests Protocol conformance
(`fetch`/`validate`/`normalize`/`metadata`, exactly the signature
`IngestionRunner` calls)."""

from __future__ import annotations

import pytest
from helpers import utc

from data_infra.provider import IngestionRunner, PermanentProviderError
from data_infra.providers.stooq import StooqDataProvider
from data_infra.providers.stooq_config import StooqConfig
from data_infra.providers.stooq_transport import StooqTransportResponse
from data_infra.repository import InMemoryDataRepository


class _StubTransport:
    def __init__(self, raw_text) -> None:
        self._raw_text = raw_text
        self.calls: list[tuple[str, dict]] = []

    def get(self, path, *, params, timeout):
        self.calls.append((path, params))
        return StooqTransportResponse(status_code=200, raw_text=self._raw_text, headers={})


_VALID_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2024-01-02,185.0,186.5,184.2,185.64,82488700\n"
    "2024-01-03,184.5,185.9,183.6,184.25,58414500\n"
)


class TestFetch:
    def test_fetch_parses_csv_and_stamps_metadata(self) -> None:
        transport = _StubTransport(_VALID_CSV)
        provider = StooqDataProvider(StooqConfig(), transport)
        records = provider.fetch("AAPL", utc(2024, 1, 1), utc(2024, 1, 4))
        assert len(records) == 2
        assert records[0]["security_id"] == "AAPL"
        assert records[0]["_fetched_as_of"] == utc(2024, 1, 4)
        assert transport.calls[0][1]["s"] == "aapl.us"

    def test_fetch_raises_permanent_error_on_unexpected_body(self) -> None:
        transport = _StubTransport("No data found for symbol\n")
        provider = StooqDataProvider(StooqConfig(), transport)
        with pytest.raises(PermanentProviderError):
            provider.fetch("ZZZZINVALID", utc(2024, 1, 1), utc(2024, 1, 4))

    def test_fetch_raises_permanent_error_on_empty_body(self) -> None:
        transport = _StubTransport("")
        provider = StooqDataProvider(StooqConfig(), transport)
        with pytest.raises(PermanentProviderError):
            provider.fetch("AAPL", utc(2024, 1, 1), utc(2024, 1, 4))


class TestValidate:
    def test_complete_record_has_no_issues(self) -> None:
        provider = StooqDataProvider(StooqConfig(), _StubTransport(""))
        issues = provider.validate([{"date": "2024-01-02", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "100"}])
        assert issues == []

    def test_missing_field_is_reported(self) -> None:
        provider = StooqDataProvider(StooqConfig(), _StubTransport(""))
        issues = provider.validate([{"date": "2024-01-02", "open": "1"}])
        assert len(issues) == 1


class TestNormalize:
    def test_normalize_produces_raw_bars_with_no_adjusted_close(self) -> None:
        transport = _StubTransport(_VALID_CSV)
        provider = StooqDataProvider(StooqConfig(), transport)
        raw = provider.fetch("AAPL", utc(2024, 1, 1), utc(2024, 1, 4))
        bars = provider.normalize("AAPL", raw)
        assert len(bars) == 2
        assert bars[0].close == 185.64
        assert bars[0].adjusted_close is None  # never fabricated -- Stooq's adjustment shape is unconfirmed
        assert bars[0].timestamp == utc(2024, 1, 2)
        assert bars[0].provenance.source == "stooq"
        # External review finding (Session 36 continued): matches the
        # identical fix/test in test_tiingo_provider.py -- see
        # data_infra.provider.bar_available_time's own docstring.
        assert bars[0].available_time == utc(2024, 1, 2, 20)

    def test_data_version_is_stable_across_different_fetched_as_of_values(self) -> None:
        transport = _StubTransport(_VALID_CSV)
        provider = StooqDataProvider(StooqConfig(), transport)
        raw1 = provider.fetch("AAPL", utc(2024, 1, 1), utc(2024, 1, 4))
        raw2 = provider.fetch("AAPL", utc(2024, 1, 1), utc(2024, 6, 1))
        v1 = provider.normalize("AAPL", [raw1[0]])[0].provenance.data_version
        v2 = provider.normalize("AAPL", [raw2[0]])[0].provenance.data_version
        assert v1 == v2

    def test_ingestion_runner_end_to_end_with_stub_transport(self) -> None:
        transport = _StubTransport(_VALID_CSV)
        provider = StooqDataProvider(StooqConfig(), transport)
        repo = InMemoryDataRepository()
        runner = IngestionRunner(provider, repo)
        result = runner.run(["AAPL"], utc(2024, 1, 1), utc(2024, 1, 4))
        assert result.status.value == "SUCCESS"
        assert len(repo.all_bars()) == 2


class TestMetadata:
    def test_metadata_declares_no_corporate_action_support(self) -> None:
        provider = StooqDataProvider(StooqConfig(), _StubTransport(""))
        meta = provider.metadata()
        assert meta["supports_corporate_actions"] is False
        assert meta["provider_id"] == "stooq"
