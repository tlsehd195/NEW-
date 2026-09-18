"""TwelveDataDataProvider: a real (not mock) `data_infra.provider.
DataProvider` implementation for US equity daily OHLCV via Twelve
Data's `/time_series` endpoint -- the second fallback tier in the
Tiingo -> Twelve Data -> Alpha Vantage chain (ADR-0164), replacing
Stooq (ADR-0160: confirmed permanent dead end, a JS bot-verification
challenge page on every real request, never fixable via headers).

**Evidence tier**: unlike Tiingo/Stooq's original Tier-2-only
implementations, the success response shape below (`{"meta": {...},
"values": [{"datetime", "open", "high", "low", "close", "volume"}]}`)
was directly confirmed against a real Twelve Data response the account
owner fetched and pasted back (2026-09-18, SO/MS/WFC all HTTP 200 with
this exact shape) -- Tier 1, not guessed. The error-body shape
(`{"code": ..., "status": "error", "message": ...}` on an HTTP 200,
a documented Twelve Data API quirk for quota/rate-limit rejections) is
still Tier 2 (public documentation, not exercised live in this
environment or the account owner's own test run) -- isolated entirely
in `fetch()`'s error-body branch below so it can be corrected in one
place if real behavior differs.

**Deliberately does NOT implement corporate-action fetching**, same
reasoning as `StooqDataProvider`: Tiingo remains this project's sole
corporate-action source (`fetch_corporate_actions`/
`normalize_corporate_actions`, called directly on the Tiingo instance,
never through `FallbackDataProvider`). `adjusted_close` is never
populated here either -- Twelve Data's free `/time_series` endpoint
does not return a split/dividend-adjusted close, and fabricating one
would violate this project's raw/adjusted separation discipline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from data_infra.models import PriceBar, Provenance
from data_infra.provider import PermanentProviderError, TransientProviderError, bar_available_time, clamp_ingestion_time
from data_infra.providers.twelvedata_auth import resolve_api_key
from data_infra.providers.twelvedata_config import TwelveDataConfig
from data_infra.providers.twelvedata_transport import TwelveDataHttpTransport
from data_infra.versioning import compute_data_version

_TIME_SERIES_PATH = "/time_series"
_REQUIRED_RAW_FIELDS = ("datetime", "open", "high", "low", "close", "volume")


class TwelveDataDataProvider:
    """Implements `data_infra.provider.DataProvider` for real (not
    mock) Twelve Data EOD data. `retrieved_at`/`ingestion_time` are
    always derived from the caller-supplied `end` parameter (never
    `datetime.now()`/`utcnow()`), identical discipline to
    `TiingoDataProvider`/`StooqDataProvider`."""

    def __init__(self, config: TwelveDataConfig, transport: TwelveDataHttpTransport) -> None:
        self._config = config
        self._transport = transport

    def fetch(self, security_id: str, start: datetime, end: datetime) -> list[dict]:
        api_key = resolve_api_key(self._config)
        params = {
            "symbol": security_id,
            "interval": "1day",
            "start_date": start.date().isoformat(),
            "end_date": end.date().isoformat(),
            "apikey": api_key,
        }
        response = self._transport.get(_TIME_SERIES_PATH, params=params, timeout=self._config.timeout_seconds)
        body = response.body

        # Twelve Data reports quota/rate-limit/bad-symbol errors as HTTP
        # 200 with an error object in the body, not a real HTTP error
        # status -- see this module's own "Evidence tier" docstring.
        if isinstance(body, dict) and body.get("status") == "error":
            code = body.get("code")
            message = body.get("message", "(no message)")
            if code == 429:
                raise TransientProviderError(f"Twelve Data rate limited for {security_id}: {message}")
            raise PermanentProviderError(f"Twelve Data error for {security_id} (code={code}): {message}")

        if not isinstance(body, dict) or not isinstance(body.get("values"), list):
            raise PermanentProviderError(
                f"unexpected Twelve Data response shape for {security_id}: expected an object with a 'values' list"
            )

        return [dict(row, security_id=security_id, _fetched_as_of=end) for row in body["values"]]

    def validate(self, raw_records: Sequence[dict]) -> list[str]:
        issues: list[str] = []
        for i, record in enumerate(raw_records):
            missing = [f for f in _REQUIRED_RAW_FIELDS if f not in record]
            if missing:
                issues.append(f"record[{i}] missing fields: {missing}")
        return issues

    def normalize(self, security_id: str, raw_records: Sequence[dict]) -> list[PriceBar]:
        bars: list[PriceBar] = []
        for record in raw_records:
            timestamp = _parse_twelvedata_date(record["datetime"])
            as_of = record["_fetched_as_of"]
            content_fields = {k: v for k, v in record.items() if k not in ("_fetched_as_of", "security_id")}
            provenance = Provenance(
                source="twelvedata",
                source_dataset=f"twelvedata_eod_{security_id}",
                source_record_id=f"{security_id}:{record['datetime']}",
                retrieved_at=as_of,
                data_version=compute_data_version(content_fields),
            )
            bars.append(
                PriceBar(
                    security_id=security_id,
                    timestamp=timestamp,
                    open=float(record["open"]),
                    high=float(record["high"]),
                    low=float(record["low"]),
                    close=float(record["close"]),
                    volume=float(record["volume"]),
                    available_time=bar_available_time(timestamp),
                    ingestion_time=clamp_ingestion_time(as_of, bar_available_time(timestamp)),
                    provenance=provenance,
                    adjusted_close=None,  # never fabricated -- see module docstring
                    currency="USD",
                )
            )
        return bars

    def metadata(self) -> dict:
        return {
            "provider_id": self._config.provider_id,
            "provider_name": "Twelve Data",
            # Twelve Data's own published free-tier limit (8 req/minute,
            # 800/day) -- Tier 2 documentation, not independently load-
            # tested against sustained real usage in this environment.
            "rate_limit_per_minute": 8,
            "is_real_external_provider": True,
            "configuration_version": self._config.configuration_version(),
            "supports_corporate_actions": False,  # deliberately not implemented, see module docstring
        }


def _parse_twelvedata_date(raw: str) -> datetime:
    """Twelve Data's daily interval returns a bare `YYYY-MM-DD` date
    string (Tier 1, confirmed against a real response) -- always
    interpreted as midnight UTC, matching Tiingo/Stooq's identical
    convention for a daily EOD bar's event date."""
    return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
