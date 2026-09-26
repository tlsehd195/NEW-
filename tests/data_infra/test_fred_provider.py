"""Category: FRED Provider Test -- `FredMacroProvider.fetch_series()`
calls `FredHttpTransport`, always replaced here with a fixture-returning
stub -- never the real network (same discipline as
`test_tiingo_provider.py`). Not a `DataProvider` Protocol conformance
test (this module is deliberately not that Protocol -- see `fred.py`'s
own docstring) -- this tests `fetch_series`'s own real contract instead:
date/value parsing, the "." missing-value convention, and credential
isolation."""

from __future__ import annotations

from datetime import date

import pytest

from data_infra.provider import PermanentProviderError
from data_infra.providers.fred import FredMacroProvider, FredObservation
from data_infra.providers.fred_config import FredConfig
from data_infra.providers.fred_transport import FredTransportResponse


class _StubTransport:
    def __init__(self, body) -> None:
        self._body = body
        self.calls: list[dict] = []

    def get_series_observations(self, *, series_id, api_key, observation_start, observation_end, timeout):
        self.calls.append(
            {
                "series_id": series_id,
                "api_key": api_key,
                "observation_start": observation_start,
                "observation_end": observation_end,
            }
        )
        return FredTransportResponse(status_code=200, body=self._body)


def _provider(body, monkeypatch) -> tuple[FredMacroProvider, _StubTransport]:
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    transport = _StubTransport(body)
    return FredMacroProvider(FredConfig(), transport), transport


class TestFetchSeries:
    def test_fetch_series_parses_real_valued_observations(self, monkeypatch) -> None:
        provider, transport = _provider(
            {"observations": [{"date": "2024-01-02", "value": "5.40"}, {"date": "2024-01-03", "value": "5.41"}]},
            monkeypatch,
        )
        observations = provider.fetch_series("DGS3MO", date(2024, 1, 1), date(2024, 1, 31))
        assert observations == [
            FredObservation("DGS3MO", date(2024, 1, 2), 5.40, observations[0].retrieved_at),
            FredObservation("DGS3MO", date(2024, 1, 3), 5.41, observations[1].retrieved_at),
        ]
        assert transport.calls[0]["series_id"] == "DGS3MO"
        assert transport.calls[0]["api_key"] == "test-key"
        assert transport.calls[0]["observation_start"] == "2024-01-01"
        assert transport.calls[0]["observation_end"] == "2024-01-31"

    def test_missing_value_marker_becomes_none(self, monkeypatch) -> None:
        """FRED's own documented convention: an unavailable observation's
        "value" is the literal string "." -- must become None, never a
        parse crash or a fabricated 0.0."""
        provider, _ = _provider({"observations": [{"date": "2024-01-02", "value": "."}]}, monkeypatch)
        observations = provider.fetch_series("DGS3MO", date(2024, 1, 1), date(2024, 1, 31))
        assert observations[0].value is None

    def test_unexpected_response_shape_raises_permanent_error(self, monkeypatch) -> None:
        provider, _ = _provider({"not": "the expected shape"}, monkeypatch)
        with pytest.raises(PermanentProviderError):
            provider.fetch_series("DGS3MO", date(2024, 1, 1), date(2024, 1, 31))

    def test_unparseable_observation_date_raises_permanent_error(self, monkeypatch) -> None:
        provider, _ = _provider({"observations": [{"date": "not-a-date", "value": "5.0"}]}, monkeypatch)
        with pytest.raises(PermanentProviderError):
            provider.fetch_series("DGS3MO", date(2024, 1, 1), date(2024, 1, 31))

    def test_unparseable_observation_value_raises_permanent_error(self, monkeypatch) -> None:
        provider, _ = _provider({"observations": [{"date": "2024-01-02", "value": "not-a-number"}]}, monkeypatch)
        with pytest.raises(PermanentProviderError):
            provider.fetch_series("DGS3MO", date(2024, 1, 1), date(2024, 1, 31))

    def test_fetch_without_credentials_raises_before_transport_call(self, monkeypatch) -> None:
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        transport = _StubTransport({"observations": []})
        provider = FredMacroProvider(FredConfig(), transport)
        with pytest.raises(PermanentProviderError):
            provider.fetch_series("DGS3MO", date(2024, 1, 1), date(2024, 1, 31))
        assert transport.calls == []

    def test_end_before_start_raises_value_error(self, monkeypatch) -> None:
        provider, _ = _provider({"observations": []}, monkeypatch)
        with pytest.raises(ValueError):
            provider.fetch_series("DGS3MO", date(2024, 1, 31), date(2024, 1, 1))


class TestMetadata:
    def test_metadata_declares_a_real_external_provider(self, monkeypatch) -> None:
        provider, _ = _provider({"observations": []}, monkeypatch)
        metadata = provider.metadata()
        assert metadata["provider_id"] == "fred"
        assert metadata["is_real_external_provider"] is True


class _StubVintageTransport:
    """Serves `pages` in order; records each call's offset/limit."""

    def __init__(self, pages: list[dict]) -> None:
        self._pages = list(pages)
        self.calls: list[dict] = []

    def get_series_vintage_observations(
        self, *, series_id, api_key, observation_start, observation_end, offset, limit, timeout,
    ):
        self.calls.append({"series_id": series_id, "offset": offset, "limit": limit})
        return FredTransportResponse(status_code=200, body=self._pages.pop(0))


def _vintage_row(obs_date: str, value: str, start: str, end: str = "9999-12-31") -> dict:
    return {"date": obs_date, "value": value, "realtime_start": start, "realtime_end": end}


class TestFetchSeriesVintages:
    def test_parses_revisions_and_open_ended_sentinel(self, monkeypatch) -> None:
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        transport = _StubVintageTransport([
            {"count": 2, "observations": [
                _vintage_row("2024-01-01", "143.0", "2024-02-02", "2024-03-07"),
                _vintage_row("2024-01-01", "143.2", "2024-03-08"),
            ]},
        ])
        rows = FredMacroProvider(FredConfig(), transport).fetch_series_vintages(
            "PAYEMS", date(2024, 1, 1), date(2024, 1, 31)
        )
        assert [(r.value, r.realtime_start, r.realtime_end) for r in rows] == [
            (143.0, date(2024, 2, 2), date(2024, 3, 7)),
            (143.2, date(2024, 3, 8), None),
        ]

    def test_follows_count_offset_paging(self, monkeypatch) -> None:
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        transport = _StubVintageTransport([
            {"count": 3, "observations": [_vintage_row("2024-01-02", "1", "2024-01-03"), _vintage_row("2024-01-03", "2", "2024-01-04")]},
            {"count": 3, "observations": [_vintage_row("2024-01-04", "3", "2024-01-05")]},
        ])
        rows = FredMacroProvider(FredConfig(), transport).fetch_series_vintages(
            "VIXCLS", date(2024, 1, 1), date(2024, 1, 31)
        )
        assert [r.value for r in rows] == [1.0, 2.0, 3.0]
        assert [c["offset"] for c in transport.calls] == [0, 2]

    def test_missing_realtime_fields_raise_permanent_error(self, monkeypatch) -> None:
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        transport = _StubVintageTransport([{"count": 1, "observations": [{"date": "2024-01-02", "value": "1"}]}])
        with pytest.raises(PermanentProviderError):
            FredMacroProvider(FredConfig(), transport).fetch_series_vintages("VIXCLS", date(2024, 1, 1), date(2024, 1, 31))
