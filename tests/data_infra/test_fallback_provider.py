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
    def test_both_transient_raises_transient_so_the_runner_still_retries(self, monkeypatch) -> None:
        """Session 37 (ADR-0115, external review N-12): before this fix,
        ANY dual failure -- even two TransientProviderError, the exact
        case a retry could plausibly recover from -- was always
        repackaged as PermanentProviderError, so `IngestionRunner`'s
        retry/backoff (which only retries on TransientProviderError) was
        structurally unreachable through this provider. This module's
        own docstring promises "each retry attempt gets a fresh primary-
        then-secondary chance"; that is only true if this call actually
        raises TransientProviderError here."""
        tiingo, stooq = _providers(
            monkeypatch, tiingo_raise=TransientProviderError("tiingo down"), stooq_raise=TransientProviderError("stooq down"),
        )
        fallback = FallbackDataProvider(tiingo, stooq)
        with pytest.raises(TransientProviderError) as exc_info:
            fallback.fetch("AAPL", utc(2024, 1, 1), utc(2024, 1, 3))
        assert "tiingo" in str(exc_info.value) and "stooq" in str(exc_info.value)

    def test_a_mix_of_transient_and_permanent_still_raises_transient(self, monkeypatch) -> None:
        """Either side being transient is reason enough to give the
        Runner a fresh retry chance -- only a dual PERMANENT failure is
        truly non-retryable."""
        tiingo, stooq = _providers(
            monkeypatch, tiingo_raise=PermanentProviderError("tiingo unknown symbol"),
            stooq_raise=TransientProviderError("stooq timeout"),
        )
        fallback = FallbackDataProvider(tiingo, stooq)
        with pytest.raises(TransientProviderError):
            fallback.fetch("AAPL", utc(2024, 1, 1), utc(2024, 1, 3))

    def test_both_permanent_raises_permanent_error_naming_both(self, monkeypatch) -> None:
        tiingo, stooq = _providers(
            monkeypatch, tiingo_raise=PermanentProviderError("tiingo unknown symbol"),
            stooq_raise=PermanentProviderError("stooq unknown symbol"),
        )
        fallback = FallbackDataProvider(tiingo, stooq)
        with pytest.raises(PermanentProviderError) as exc_info:
            fallback.fetch("AAPL", utc(2024, 1, 1), utc(2024, 1, 3))
        assert "tiingo" in str(exc_info.value) and "stooq" in str(exc_info.value)

    def test_both_transient_gets_retried_and_can_still_succeed_end_to_end(self, monkeypatch) -> None:
        """The concrete payoff of raising TransientProviderError here:
        `IngestionRunner` actually calls `fetch()` again (its own retry
        policy triggers at all, which the pre-fix PermanentProviderError
        made impossible) -- and if the underlying condition has cleared
        by the second attempt, the symbol succeeds instead of failing
        outright on the very first pass."""
        monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")
        stooq_stub = _StooqStub(raw_text=_STOOQ_CSV, raise_error=TransientProviderError("stooq down"))
        tiingo = TiingoDataProvider(TiingoConfig(), _TiingoStub(raise_error=TransientProviderError("tiingo down")))
        stooq = StooqDataProvider(StooqConfig(), stooq_stub)
        fallback = FallbackDataProvider(tiingo, stooq)

        original_get = stooq_stub.get
        calls = {"n": 0}

        def _flaky_stooq_get(path, *, params, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                raise stooq_stub._raise_error  # first attempt: still down
            stooq_stub._raise_error = None  # retry: recovered
            return original_get(path, params=params, timeout=timeout)

        stooq_stub.get = _flaky_stooq_get
        repo = InMemoryDataRepository()
        runner = IngestionRunner(fallback, repo, max_retries=1, sleep_fn=lambda _seconds: None)
        result = runner.run(["AAPL"], utc(2024, 1, 1), utc(2024, 1, 3))
        assert result.status.value == "SUCCESS"
        assert calls["n"] == 2  # proves the retry actually happened
        assert repo.all_bars()[0].provenance.source == "stooq"


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
