"""Category: Provider Fallback Test (Phase 22 instruction section 7) --
FallbackDataProvider tries primary, falls back to secondary on failure,
and never hides which provider actually answered."""

from __future__ import annotations

from helpers import utc

import pytest

from data_infra.provider import IngestionRunner, PermanentProviderError, TransientProviderError
from data_infra.providers.fallback import FallbackDataProvider
from data_infra.providers.tiingo import TiingoDataProvider
from data_infra.providers.tiingo_config import TiingoConfig
from data_infra.providers.tiingo_transport import TiingoTransportResponse
from data_infra.providers.stooq import StooqDataProvider
from data_infra.providers.stooq_config import StooqConfig
from data_infra.providers.stooq_transport import StooqTransportResponse
from data_infra.repository import InMemoryDataRepository


class _TiingoStub:
    def __init__(self, body=None, raise_error=None) -> None:
        self._body = body
        self._raise_error = raise_error

    def post(self, path, *, headers, json_body, timeout):
        raise NotImplementedError

    def get(self, path, *, params, timeout):
        if self._raise_error is not None:
            raise self._raise_error
        return TiingoTransportResponse(status_code=200, body=self._body, raw_text=None, headers={})


class _StooqStub:
    def __init__(self, raw_text=None, raise_error=None) -> None:
        self._raw_text = raw_text
        self._raise_error = raise_error

    def get(self, path, *, params, timeout):
        if self._raise_error is not None:
            raise self._raise_error
        return StooqTransportResponse(status_code=200, raw_text=self._raw_text, headers={})


_TIINGO_BODY = [{"date": "2024-01-02T00:00:00.000Z", "open": "185.0", "high": "186.0", "low": "184.0", "close": "185.5", "volume": "1000000", "adjClose": "185.5"}]
_STOOQ_CSV = "Date,Open,High,Low,Close,Volume\n2024-01-02,185.0,186.0,184.0,185.5,1000000\n"


def _providers(monkeypatch, *, tiingo_raise=None, stooq_raise=None):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")
    tiingo = TiingoDataProvider(TiingoConfig(), _TiingoStub(body=_TIINGO_BODY, raise_error=tiingo_raise))
    stooq = StooqDataProvider(StooqConfig(), _StooqStub(raw_text=_STOOQ_CSV, raise_error=stooq_raise))
    return tiingo, stooq


class TestPrimarySucceeds:
    def test_uses_primary_when_it_succeeds(self, monkeypatch) -> None:
        tiingo, stooq = _providers(monkeypatch)
        fallback = FallbackDataProvider(tiingo, stooq)
        raw = fallback.fetch("AAPL", utc(2024, 1, 1), utc(2024, 1, 3))
        assert all(r["_answered_by"] == "tiingo" for r in raw)
        bars = fallback.normalize("AAPL", raw)
        assert bars[0].provenance.source == "tiingo"


class TestFallsBackOnPrimaryFailure:
    def test_falls_back_to_secondary_when_primary_raises(self, monkeypatch) -> None:
        tiingo, stooq = _providers(monkeypatch, tiingo_raise=TransientProviderError("simulated timeout"))
        fallback = FallbackDataProvider(tiingo, stooq)
        raw = fallback.fetch("AAPL", utc(2024, 1, 1), utc(2024, 1, 3))
        assert all(r["_answered_by"] == "stooq" for r in raw)
        bars = fallback.normalize("AAPL", raw)
        assert bars[0].provenance.source == "stooq"  # never disguised as tiingo

    def test_falls_back_on_permanent_primary_error_too(self, monkeypatch) -> None:
        tiingo, stooq = _providers(monkeypatch, tiingo_raise=PermanentProviderError("simulated 401"))
        fallback = FallbackDataProvider(tiingo, stooq)
        raw = fallback.fetch("AAPL", utc(2024, 1, 1), utc(2024, 1, 3))
        assert all(r["_answered_by"] == "stooq" for r in raw)


class TestBothFail:
    def test_both_failing_raises_permanent_error_naming_both(self, monkeypatch) -> None:
        tiingo, stooq = _providers(
            monkeypatch, tiingo_raise=TransientProviderError("tiingo down"), stooq_raise=TransientProviderError("stooq down"),
        )
        fallback = FallbackDataProvider(tiingo, stooq)
        with pytest.raises(PermanentProviderError) as exc_info:
            fallback.fetch("AAPL", utc(2024, 1, 1), utc(2024, 1, 3))
        assert "tiingo" in str(exc_info.value) and "stooq" in str(exc_info.value)


class TestIngestionRunnerEndToEnd:
    def test_fallback_provider_works_through_the_real_ingestion_runner(self, monkeypatch) -> None:
        tiingo, stooq = _providers(monkeypatch, tiingo_raise=TransientProviderError("simulated timeout"))
        fallback = FallbackDataProvider(tiingo, stooq)
        repo = InMemoryDataRepository()
        runner = IngestionRunner(fallback, repo)
        result = runner.run(["AAPL"], utc(2024, 1, 1), utc(2024, 1, 3))
        assert result.status.value == "SUCCESS"
        bars = repo.all_bars()
        assert len(bars) == 1
        assert bars[0].provenance.source == "stooq"


class TestMetadataDisclosesComposition:
    def test_metadata_names_both_providers(self, monkeypatch) -> None:
        tiingo, stooq = _providers(monkeypatch)
        fallback = FallbackDataProvider(tiingo, stooq)
        meta = fallback.metadata()
        assert meta["primary_provider_id"] == "tiingo"
        assert meta["secondary_provider_id"] == "stooq"
