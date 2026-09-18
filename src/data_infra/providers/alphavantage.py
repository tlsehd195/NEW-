"""AlphaVantageDataProvider: a real (not mock) `data_infra.provider.
DataProvider` implementation for US equity daily OHLCV via Alpha
Vantage's `TIME_SERIES_DAILY` endpoint -- the third fallback tier in
the Tiingo -> Twelve Data -> Alpha Vantage chain (ADR-0164), only ever
reached when both of those fail for a given call.

**Evidence tier**: the success response shape below (`{"Meta Data":
{...}, "Time Series (Daily)": {"<date>": {"1. open", "2. high",
"3. low", "4. close", "5. volume"}}}`) was directly confirmed against a
real Alpha Vantage response the account owner fetched and pasted back
(2026-09-18, SO/MS/WFC all HTTP 200 with this exact shape) -- Tier 1,
not guessed. The error-body shapes (`"Error Message"`/`"Note"`/
`"Information"` keys on an HTTP 200, Alpha Vantage's long-documented
way of reporting a bad symbol or a rate-limit/quota rejection) are
still Tier 2 (public documentation, not exercised live in this
environment) -- isolated entirely in `fetch()`'s error-body branch
below.

**No native date-range query parameter, and `outputsize=full` is a
paid-only feature (Tier 1, corrected after this provider's first real
production run, ADR-0164's own follow-up correction)**: unlike
Tiingo/Twelve Data, `TIME_SERIES_DAILY` always returns either the most
recent ~100 daily bars (`outputsize=compact`) or the full available
history (`outputsize=full`) for a symbol -- there is no `start`/`end`
the server accepts. This provider was originally written to always
request `full` for date-range correctness regardless of how far back
`start` fell; a real production run found every single real call
rejected with `"The outputsize=full parameter value is a premium
feature for the TIME_SERIES_DAILY endpoint"` -- `full` is not available
on the free tier at all, contrary to this module's own original,
unverified assumption. This provider now always requests `compact`
(the only option the free tier actually serves) and filters to
`[start, end]` itself in `fetch()`, mirroring `MockDataProvider.
fetch()`'s identical client-side range filter. **Real, accepted
limitation**: `compact` only ever returns the ~100 most recent trading
days, so a requested `start` older than that will simply return fewer
bars than asked for, never an error and never fabricated data -- this
is acceptable because this tier is only reached when both Tiingo and
Twelve Data have already failed for a symbol during this project's own
narrow daily incremental catch-up window (a few weeks at most, ADR-0164),
not a broad historical backfill.

**Deliberately does NOT implement corporate-action fetching**, same
reasoning as `StooqDataProvider`/`TwelveDataDataProvider`: Tiingo
remains this project's sole corporate-action source. `adjusted_close`
is never populated here either -- Alpha Vantage's free
`TIME_SERIES_DAILY` endpoint does not return a split/dividend-adjusted
close (that is a separate, premium `TIME_SERIES_DAILY_ADJUSTED`
endpoint this project does not use), and fabricating one would violate
this project's raw/adjusted separation discipline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from data_infra.models import PriceBar, Provenance
from data_infra.provider import PermanentProviderError, TransientProviderError, bar_available_time, clamp_ingestion_time
from data_infra.providers.alphavantage_auth import resolve_api_key
from data_infra.providers.alphavantage_config import AlphaVantageConfig
from data_infra.providers.alphavantage_transport import AlphaVantageHttpTransport
from data_infra.versioning import compute_data_version

_QUERY_PATH = "/query"
_TIME_SERIES_KEY = "Time Series (Daily)"
_REQUIRED_RAW_FIELDS = ("1. open", "2. high", "3. low", "4. close", "5. volume")


class AlphaVantageDataProvider:
    """Implements `data_infra.provider.DataProvider` for real (not
    mock) Alpha Vantage EOD data. `retrieved_at`/`ingestion_time` are
    always derived from the caller-supplied `end` parameter (never
    `datetime.now()`/`utcnow()`), identical discipline to
    `TiingoDataProvider`/`TwelveDataDataProvider`."""

    def __init__(self, config: AlphaVantageConfig, transport: AlphaVantageHttpTransport) -> None:
        self._config = config
        self._transport = transport

    def fetch(self, security_id: str, start: datetime, end: datetime) -> list[dict]:
        api_key = resolve_api_key(self._config)
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": security_id,
            # "full" is a paid-only feature on this endpoint (confirmed
            # by a real rejected call, see module docstring) -- "compact"
            # is the only option the free tier actually serves.
            "outputsize": "compact",
            "apikey": api_key,
        }
        response = self._transport.get(_QUERY_PATH, params=params, timeout=self._config.timeout_seconds)
        body = response.body

        if isinstance(body, dict) and ("Error Message" in body or "Note" in body or "Information" in body):
            message = body.get("Error Message") or body.get("Note") or body.get("Information")
            if "Note" in body or "Information" in body:
                # Both keys are Alpha Vantage's documented way of
                # reporting a rate-limit/quota rejection on an HTTP 200
                # -- see module docstring's "Evidence tier".
                raise TransientProviderError(f"Alpha Vantage rate limited for {security_id}: {message}")
            raise PermanentProviderError(f"Alpha Vantage error for {security_id}: {message}")

        if not isinstance(body, dict) or not isinstance(body.get(_TIME_SERIES_KEY), dict):
            raise PermanentProviderError(
                f"unexpected Alpha Vantage response shape for {security_id}: "
                f"expected an object with a '{_TIME_SERIES_KEY}' object"
            )

        start_date, end_date = start.date(), end.date()
        records = []
        for date_str, values in body[_TIME_SERIES_KEY].items():
            timestamp_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if not (start_date <= timestamp_date <= end_date):
                continue  # client-side range filter -- see module docstring
            records.append(dict(values, datetime=date_str, security_id=security_id, _fetched_as_of=end))
        return records

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
            timestamp = datetime.strptime(record["datetime"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            as_of = record["_fetched_as_of"]
            content_fields = {k: v for k, v in record.items() if k not in ("_fetched_as_of", "security_id")}
            provenance = Provenance(
                source="alphavantage",
                source_dataset=f"alphavantage_eod_{security_id}",
                source_record_id=f"{security_id}:{record['datetime']}",
                retrieved_at=as_of,
                data_version=compute_data_version(content_fields),
            )
            bars.append(
                PriceBar(
                    security_id=security_id,
                    timestamp=timestamp,
                    open=float(record["1. open"]),
                    high=float(record["2. high"]),
                    low=float(record["3. low"]),
                    close=float(record["4. close"]),
                    volume=float(record["5. volume"]),
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
            "provider_name": "Alpha Vantage",
            # Alpha Vantage's own published free-tier limit (25
            # requests/day) is per-DAY, not per-minute, so this field
            # (shaped for a per-minute figure, same unit mismatch
            # TiingoDataProvider.metadata() already discloses for
            # Tiingo's per-hour limit) stays None rather than forcing a
            # false per-minute number into it.
            "rate_limit_per_minute": None,
            "is_real_external_provider": True,
            "configuration_version": self._config.configuration_version(),
            "supports_corporate_actions": False,  # deliberately not implemented, see module docstring
        }
