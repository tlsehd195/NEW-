"""Category: Tiingo Provider Test -- `TiingoDataProvider.fetch()` calls
`TiingoHttpTransport`, always replaced here with a fixture-returning
stub -- never the real network (ADR-0025). Tests the Protocol
conformance (`fetch`/`validate`/`normalize`/`metadata`, exactly the
signature `IngestionRunner` calls) plus the corporate-action extraction
this module adds beyond that Protocol."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from helpers import utc

from data_infra.enums import CorporateActionType
from data_infra.provider import IngestionRunner, PermanentProviderError
from data_infra.providers.tiingo import TiingoDataProvider
from data_infra.providers.tiingo_config import TiingoConfig
from data_infra.providers.tiingo_transport import TiingoTransportResponse
from data_infra.repository import InMemoryDataRepository


class _StubTransport:
    def __init__(self, body) -> None:
        self._body = body
        self.calls: list[tuple[str, dict]] = []

    def get(self, path, *, params, timeout):
        self.calls.append((path, params))
        return TiingoTransportResponse(status_code=200, body=self._body, raw_text=None, headers={})


def _provider(body, monkeypatch) -> tuple[TiingoDataProvider, _StubTransport]:
    monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")
    transport = _StubTransport(body)
    return TiingoDataProvider(TiingoConfig(), transport), transport


class TestFetch:
    def test_fetch_stamps_security_id_and_as_of(self, monkeypatch) -> None:
        provider, transport = _provider(
            [{"date": "2024-01-02T00:00:00.000Z", "open": "185.0", "high": "186.0", "low": "184.0", "close": "185.5", "volume": "1000000", "adjClose": "185.5"}],
            monkeypatch,
        )
        records = provider.fetch("AAPL", utc(2024, 1, 1), utc(2024, 1, 3))
        assert records[0]["security_id"] == "AAPL"
        assert records[0]["_fetched_as_of"] == utc(2024, 1, 3)
        assert transport.calls[0][1]["token"] == "test-key"

    def test_fetch_raises_permanent_error_on_unexpected_shape(self, monkeypatch) -> None:
        provider, _ = _provider({"not": "a list"}, monkeypatch)
        with pytest.raises(PermanentProviderError):
            provider.fetch("AAPL", utc(2024, 1, 1), utc(2024, 1, 3))

    def test_fetch_without_credentials_raises_before_transport_call(self, monkeypatch) -> None:
        monkeypatch.delenv("MARKET_DATA_API_KEY", raising=False)
        transport = _StubTransport([])
        provider = TiingoDataProvider(TiingoConfig(), transport)
        with pytest.raises(PermanentProviderError):
            provider.fetch("AAPL", utc(2024, 1, 1), utc(2024, 1, 3))
        assert transport.calls == []


class TestValidate:
    def test_missing_required_field_is_reported(self, monkeypatch) -> None:
        provider, _ = _provider([], monkeypatch)
        issues = provider.validate([{"date": "2024-01-02", "open": "1"}])  # missing high/low/close/volume
        assert len(issues) == 1
        assert "missing fields" in issues[0]

    def test_complete_record_has_no_issues(self, monkeypatch) -> None:
        provider, _ = _provider([], monkeypatch)
        issues = provider.validate([{"date": "2024-01-02", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "100"}])
        assert issues == []


class TestNormalize:
    def test_normalize_produces_a_price_bar_with_raw_and_adjusted_close_kept_separate(self, monkeypatch) -> None:
        provider, _ = _provider([], monkeypatch)
        raw = [{
            "date": "2024-01-02T00:00:00.000Z", "security_id": "AAPL", "_fetched_as_of": utc(2024, 1, 3),
            "open": "185.0", "high": "186.0", "low": "184.0", "close": "185.5", "volume": "1000000",
            "adjClose": "92.75",  # simulating a 2:1 split-adjusted value, deliberately different from raw close
        }]
        bars = provider.normalize("AAPL", raw)
        assert len(bars) == 1
        bar = bars[0]
        assert bar.close == 185.5  # raw, unadjusted -- never overwritten by the adjusted figure
        assert bar.adjusted_close == 92.75  # kept as the separate, optional field
        assert bar.timestamp == utc(2024, 1, 2)
        assert bar.ingestion_time == utc(2024, 1, 3)
        assert bar.provenance.retrieved_at == utc(2024, 1, 3)

    def test_data_version_is_stable_across_different_fetched_as_of_values(self, monkeypatch) -> None:
        """The same real-world bar, re-ingested on a later run (a
        different `_fetched_as_of`), must produce the same
        data_version -- otherwise IngestionRunner's own idempotency
        dedup key would never recognize it as already-seen."""
        provider, _ = _provider([], monkeypatch)
        base = {"date": "2024-01-02T00:00:00.000Z", "security_id": "AAPL",
                "open": "185.0", "high": "186.0", "low": "184.0", "close": "185.5", "volume": "1000000", "adjClose": "185.5"}
        record1 = dict(base, _fetched_as_of=utc(2024, 1, 3))
        record2 = dict(base, _fetched_as_of=utc(2024, 6, 1))  # much later re-ingestion run
        version1 = provider.normalize("AAPL", [record1])[0].provenance.data_version
        version2 = provider.normalize("AAPL", [record2])[0].provenance.data_version
        assert version1 == version2

    def test_ingestion_runner_end_to_end_with_stub_transport(self, monkeypatch) -> None:
        """Proves TiingoDataProvider's fetch/normalize signatures
        genuinely conform to what IngestionRunner (Phase 1, unmodified)
        calls -- not just individually testable in isolation."""
        provider, _ = _provider(
            [{"date": "2024-01-02T00:00:00.000Z", "open": "185.0", "high": "186.0", "low": "184.0", "close": "185.5", "volume": "1000000", "adjClose": "185.5"}],
            monkeypatch,
        )
        repo = InMemoryDataRepository()
        runner = IngestionRunner(provider, repo)
        result = runner.run(["AAPL"], utc(2024, 1, 1), utc(2024, 1, 3))
        assert result.status.value == "SUCCESS"
        assert len(repo.all_bars()) == 1
        assert repo.all_bars()[0].security_id == "AAPL"


class TestCorporateActions:
    def test_split_factor_produces_a_split_event(self, monkeypatch) -> None:
        provider, _ = _provider([], monkeypatch)
        raw = [{"date": "2024-06-10T00:00:00.000Z", "splitFactor": "4.0", "divCash": "0.0"}]
        actions = provider.normalize_corporate_actions("AAPL", raw, retrieved_at=utc(2024, 6, 11), ingestion_time=utc(2024, 6, 11))
        assert len(actions) == 1
        assert actions[0].action_type == CorporateActionType.SPLIT
        assert actions[0].details["ratio"] == 4.0

    def test_split_factor_below_one_produces_a_reverse_split_event(self, monkeypatch) -> None:
        provider, _ = _provider([], monkeypatch)
        raw = [{"date": "2024-06-10T00:00:00.000Z", "splitFactor": "0.125", "divCash": "0.0"}]
        actions = provider.normalize_corporate_actions("GE", raw, retrieved_at=utc(2024, 6, 11), ingestion_time=utc(2024, 6, 11))
        assert actions[0].action_type == CorporateActionType.REVERSE_SPLIT

    def test_div_cash_produces_a_dividend_event(self, monkeypatch) -> None:
        provider, _ = _provider([], monkeypatch)
        raw = [{"date": "2024-03-14T00:00:00.000Z", "splitFactor": "1.0", "divCash": "0.24"}]
        actions = provider.normalize_corporate_actions("AAPL", raw, retrieved_at=utc(2024, 3, 15), ingestion_time=utc(2024, 3, 15))
        assert len(actions) == 1
        assert actions[0].action_type == CorporateActionType.DIVIDEND
        assert actions[0].details["amount"] == 0.24

    def test_ordinary_row_produces_no_action(self, monkeypatch) -> None:
        provider, _ = _provider([], monkeypatch)
        raw = [{"date": "2024-03-15T00:00:00.000Z", "splitFactor": "1.0", "divCash": "0.0"}]
        actions = provider.normalize_corporate_actions("AAPL", raw, retrieved_at=utc(2024, 3, 16), ingestion_time=utc(2024, 3, 16))
        assert actions == []

    def test_split_and_dividend_on_the_same_date_both_produced(self, monkeypatch) -> None:
        provider, _ = _provider([], monkeypatch)
        raw = [{"date": "2024-06-10T00:00:00.000Z", "splitFactor": "2.0", "divCash": "0.10"}]
        actions = provider.normalize_corporate_actions("XYZ", raw, retrieved_at=utc(2024, 6, 11), ingestion_time=utc(2024, 6, 11))
        assert {a.action_type for a in actions} == {CorporateActionType.SPLIT, CorporateActionType.DIVIDEND}
