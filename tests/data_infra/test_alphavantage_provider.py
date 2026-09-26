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
    def test_metadata_declares_corporate_action_support(self) -> None:
        # 2026-09-25: confirmed Tier 1 against a real free-tier key --
        # see AlphaVantageDataProvider's own module docstring.
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), _StubTransport({}))
        meta = provider.metadata()
        assert meta["supports_corporate_actions"] is True
        assert meta["provider_id"] == "alphavantage"


class _FunctionRoutedStubTransport:
    """Unlike `_StubTransport` (always the same body), corporate-action
    fetching makes two real calls per symbol (DIVIDENDS then SPLITS)
    with different `function` params -- this stub returns a different
    body per `function` so both branches of a single test are covered
    honestly, not just whichever one a single fixed body happens to
    satisfy."""

    def __init__(self, bodies_by_function: dict) -> None:
        self._bodies_by_function = bodies_by_function
        self.calls: list[tuple[str, dict]] = []

    def get(self, path, *, params, timeout):
        self.calls.append((path, params))
        return AlphaVantageTransportResponse(status_code=200, body=self._bodies_by_function[params["function"]], headers={})


# Real Tier 1 evidence: scripts/recon_corporate_action_providers.py's
# own real workflow_dispatch run against a real free-tier key
# (2026-09-25). GE's real 2021-08-02 reverse split (split_factor
# "0.1250") matches this project's own already-known REVERSE_SPLIT edge
# case, docs/operations/MARKET-DATA-PROVIDER.md.
_REAL_DIVIDENDS_BODY = {
    "symbol": "AAPL",
    "data": [
        {"ex_dividend_date": "2026-08-10", "declaration_date": "2026-07-30", "record_date": "2026-08-10", "payment_date": "2026-08-13", "amount": "0.27"},
        {"ex_dividend_date": "2025-11-10", "declaration_date": "2025-10-30", "record_date": "2025-11-10", "payment_date": "2025-11-13", "amount": "0.26"},
    ],
}
_REAL_SPLITS_BODY = {
    "symbol": "GE",
    "data": [
        {"effective_date": "2024-04-02", "split_factor": "1.2530"},
        {"effective_date": "2021-08-02", "split_factor": "0.1250"},
        {"effective_date": "2000-05-08", "split_factor": "3.0000"},
    ],
}


class TestFetchCorporateActions:
    def test_fetches_both_dividends_and_splits_and_tags_each_records_kind(self) -> None:
        transport = _FunctionRoutedStubTransport({"DIVIDENDS": _REAL_DIVIDENDS_BODY, "SPLITS": _REAL_SPLITS_BODY})
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        records = provider.fetch_corporate_actions("GE", utc(2000, 1, 1), utc(2026, 12, 31))
        assert {"DIVIDENDS", "SPLITS"} == {c[1]["function"] for c in transport.calls}
        kinds = {r["_kind"] for r in records}
        assert kinds == {"dividend", "split"}

    def test_filters_to_the_requested_date_range_client_side(self) -> None:
        transport = _FunctionRoutedStubTransport({"DIVIDENDS": _REAL_DIVIDENDS_BODY, "SPLITS": _REAL_SPLITS_BODY})
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        records = provider.fetch_corporate_actions("GE", utc(2021, 1, 1), utc(2021, 12, 31))
        assert len(records) == 1
        assert records[0]["effective_date"] == "2021-08-02"

    def test_raises_transient_error_on_rate_limit_information(self) -> None:
        transport = _FunctionRoutedStubTransport(
            {"DIVIDENDS": {"Information": "Please consider spreading out your free API requests more sparingly (1 request per second)"}, "SPLITS": _REAL_SPLITS_BODY}
        )
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        with pytest.raises(TransientProviderError):
            provider.fetch_corporate_actions("AAPL", utc(2024, 1, 1), utc(2024, 12, 31))

    def test_raises_permanent_error_on_unexpected_shape(self) -> None:
        transport = _FunctionRoutedStubTransport({"DIVIDENDS": {"unexpected": "shape"}, "SPLITS": _REAL_SPLITS_BODY})
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        with pytest.raises(PermanentProviderError):
            provider.fetch_corporate_actions("AAPL", utc(2024, 1, 1), utc(2024, 12, 31))


class TestNormalizeCorporateActions:
    def test_a_ratio_above_one_is_a_split_a_ratio_below_one_is_a_reverse_split(self) -> None:
        transport = _FunctionRoutedStubTransport({"DIVIDENDS": _REAL_DIVIDENDS_BODY, "SPLITS": _REAL_SPLITS_BODY})
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        raw = provider.fetch_corporate_actions("GE", utc(2000, 1, 1), utc(2026, 12, 31))
        actions = provider.normalize_corporate_actions("GE", raw, retrieved_at=utc(2026, 9, 25), ingestion_time=utc(2026, 9, 25))
        by_date = {a.event_time: a for a in actions if a.action_type.value in ("SPLIT", "REVERSE_SPLIT")}
        assert by_date[utc(2021, 8, 2)].action_type.value == "REVERSE_SPLIT"
        assert by_date[utc(2021, 8, 2)].details["ratio"] == 0.125
        assert by_date[utc(2000, 5, 8)].action_type.value == "SPLIT"
        assert by_date[utc(2000, 5, 8)].details["ratio"] == 3.0

    def test_a_real_dividend_row_becomes_a_dividend_event(self) -> None:
        transport = _FunctionRoutedStubTransport({"DIVIDENDS": _REAL_DIVIDENDS_BODY, "SPLITS": {"symbol": "AAPL", "data": []}})
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        raw = provider.fetch_corporate_actions("AAPL", utc(2026, 1, 1), utc(2026, 12, 31))
        actions = provider.normalize_corporate_actions("AAPL", raw, retrieved_at=utc(2026, 9, 25), ingestion_time=utc(2026, 9, 25))
        assert len(actions) == 1
        assert actions[0].action_type.value == "DIVIDEND"
        assert actions[0].details == {"amount": 0.27, "currency": "USD"}
        # ADR-0216: the earlier of ingestion time and the ex-date close
        assert actions[0].available_time == utc(2026, 8, 10, 20)
        assert actions[0].ingestion_time == utc(2026, 9, 25)
        assert actions[0].provenance.source == "alphavantage"

    def test_real_actions_are_readable_through_the_in_memory_repository(self) -> None:
        transport = _FunctionRoutedStubTransport({"DIVIDENDS": {"symbol": "GE", "data": []}, "SPLITS": _REAL_SPLITS_BODY})
        provider = AlphaVantageDataProvider(AlphaVantageConfig(), transport)
        raw = provider.fetch_corporate_actions("GE", utc(2000, 1, 1), utc(2026, 12, 31))
        actions = provider.normalize_corporate_actions("GE", raw, retrieved_at=utc(2026, 9, 25), ingestion_time=utc(2026, 9, 25))
        assert len(actions) == 3
        repo = InMemoryDataRepository(corporate_actions=actions)
        assert len(repo.get_corporate_actions("GE", utc(2000, 1, 1), utc(2026, 12, 31), as_of_time=utc(2026, 9, 25))) == 3
