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

`adjusted_close` is never populated here -- Alpha Vantage's free
`TIME_SERIES_DAILY` endpoint does not return a split/dividend-adjusted
close (that is a separate, premium `TIME_SERIES_DAILY_ADJUSTED`
endpoint this project does not use), and fabricating one would violate
this project's raw/adjusted separation discipline.

**Corporate-action fetching (`fetch_corporate_actions`/
`normalize_corporate_actions`, added 2026-09-25)**: confirmed Tier 1,
not guessed -- `scripts/recon_corporate_action_providers.py`'s own real
`workflow_dispatch` run got real HTTP 200 data from BOTH the
`DIVIDENDS` and `SPLITS` functions on a real free-tier key, including
GE's own real 2021-08-02 reverse split (`split_factor: "0.1250"`,
matching this project's own already-known REVERSE_SPLIT edge case,
`docs/operations/MARKET-DATA-PROVIDER.md`). This closes the gap run #44
(2026-09-25) exposed: corporate-action collection previously called
Tiingo ONLY, with no fallback at all, so a day where Tiingo's own
hourly budget (ADR-0160, shared with price-bar fetching) was already
exhausted failed corporate actions for every requested symbol at once.
`scripts/ingest_real_market_data.py` now tries Tiingo first, falling
back to this provider per symbol -- never the reverse, since Alpha
Vantage's real free-tier cap (25 requests/day, TWO calls per symbol
here) could not cover a full ~87-symbol universe on its own even if it
went first.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from data_infra.enums import CorporateActionType
from data_infra.models import CorporateAction, PriceBar, Provenance
from data_infra.provider import PermanentProviderError, TransientProviderError, bar_available_time, clamp_ingestion_time
from data_infra.providers.alphavantage_auth import resolve_api_key
from data_infra.providers.alphavantage_config import AlphaVantageConfig
from data_infra.providers.alphavantage_transport import AlphaVantageHttpTransport
from data_infra.versioning import compute_data_version

_QUERY_PATH = "/query"
_TIME_SERIES_KEY = "Time Series (Daily)"
_REQUIRED_RAW_FIELDS = ("1. open", "2. high", "3. low", "4. close", "5. volume")
_CORPORATE_ACTION_FUNCTIONS = (
    # (function, kind, the raw record's own date field)
    ("DIVIDENDS", "dividend", "ex_dividend_date"),
    ("SPLITS", "split", "effective_date"),
)


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
            "supports_corporate_actions": True,  # confirmed 2026-09-25, see module docstring
        }

    # -- Corporate actions (extra, not part of the DataProvider
    # Protocol -- same addition TiingoDataProvider already makes) --

    def fetch_corporate_actions(self, security_id: str, start: datetime, end: datetime) -> list[dict]:
        """Two real calls per symbol (`DIVIDENDS` then `SPLITS`),
        client-side filtered to `[start, end]` -- neither function
        accepts a date-range query parameter, same limitation
        `fetch()`'s own "No native date-range query parameter" already
        documents for `TIME_SERIES_DAILY`. Each returned record carries
        `_kind` so `normalize_corporate_actions` knows which shape it
        is without re-inspecting field names."""
        api_key = resolve_api_key(self._config)
        start_date, end_date = start.date(), end.date()
        records: list[dict] = []
        for function, kind, date_field in _CORPORATE_ACTION_FUNCTIONS:
            params = {"function": function, "symbol": security_id, "apikey": api_key}
            response = self._transport.get(_QUERY_PATH, params=params, timeout=self._config.timeout_seconds)
            body = response.body

            if isinstance(body, dict) and ("Error Message" in body or "Note" in body or "Information" in body):
                message = body.get("Error Message") or body.get("Note") or body.get("Information")
                if "Note" in body or "Information" in body:
                    raise TransientProviderError(f"Alpha Vantage rate limited for {security_id} ({function}): {message}")
                raise PermanentProviderError(f"Alpha Vantage error for {security_id} ({function}): {message}")

            if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                raise PermanentProviderError(
                    f"unexpected Alpha Vantage response shape for {security_id} ({function}): "
                    f"expected an object with a 'data' list"
                )

            for row in body["data"]:
                date_str = row.get(date_field)
                if not date_str:
                    continue
                row_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if not (start_date <= row_date <= end_date):
                    continue  # client-side range filter -- see this method's own docstring
                records.append(dict(row, security_id=security_id, _kind=kind))
        return records

    def normalize_corporate_actions(
        self, security_id: str, raw_records: Sequence[dict], *, retrieved_at: datetime, ingestion_time: datetime,
    ) -> list[CorporateAction]:
        """A `split_factor` != 1.0 becomes a SPLIT/REVERSE_SPLIT event
        (identical `ratio > 1.0` convention `TiingoDataProvider.
        normalize_corporate_actions` already uses); an `amount` > 0
        dividend row becomes a DIVIDEND event. Same point-in-time
        discipline as Tiingo's own implementation: `available_time`/
        `ingestion_time` are always the caller-supplied ingestion
        moment, never the (possibly much earlier) real event date --
        backdating would make a late-discovered action falsely visible
        to an as-of query made before this system actually knew about
        it."""
        actions: list[CorporateAction] = []
        for record in raw_records:
            if record["_kind"] == "split":
                ratio = float(record["split_factor"])
                if ratio == 1.0:
                    continue
                event_date = datetime.strptime(record["effective_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                action_type = CorporateActionType.SPLIT if ratio > 1.0 else CorporateActionType.REVERSE_SPLIT
                actions.append(
                    CorporateAction(
                        security_id=security_id,
                        action_type=action_type,
                        available_time=ingestion_time,
                        ingestion_time=ingestion_time,
                        provenance=Provenance(
                            source="alphavantage", source_dataset=f"alphavantage_corporate_actions_{security_id}",
                            source_record_id=f"{security_id}:{record['effective_date']}:split",
                            retrieved_at=retrieved_at,
                            data_version=compute_data_version(
                                {"effective_date": record["effective_date"], "split_factor": record["split_factor"]}
                            ),
                        ),
                        event_time=event_date,
                        effective_time=event_date,
                        details={"ratio": ratio},
                    )
                )
            elif record["_kind"] == "dividend":
                amount = float(record["amount"])
                if amount <= 0.0:
                    continue
                event_date = datetime.strptime(record["ex_dividend_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                actions.append(
                    CorporateAction(
                        security_id=security_id,
                        action_type=CorporateActionType.DIVIDEND,
                        available_time=ingestion_time,
                        ingestion_time=ingestion_time,
                        provenance=Provenance(
                            source="alphavantage", source_dataset=f"alphavantage_corporate_actions_{security_id}",
                            source_record_id=f"{security_id}:{record['ex_dividend_date']}:dividend",
                            retrieved_at=retrieved_at,
                            data_version=compute_data_version(
                                {"ex_dividend_date": record["ex_dividend_date"], "amount": record["amount"]}
                            ),
                        ),
                        event_time=event_date,
                        effective_time=event_date,
                        details={"amount": amount, "currency": "USD"},
                    )
                )
        return actions
