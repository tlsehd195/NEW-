"""StooqDataProvider: a real (not mock) `data_infra.provider.DataProvider`
implementation for US equity daily OHLCV via Stooq's no-API-key CSV
endpoint -- the documented secondary/fallback provider from ADR-0025,
implemented in Phase 22.

**Honesty about evidence tier**: this implementation is built against
Tier 2 (secondary, commonly-cited) knowledge of Stooq's historical-data
CSV endpoint shape (`stooq.com/q/d/l/`, `.us`-suffixed US ticker
symbols, `Date,Open,High,Low,Close,Volume` columns) -- it has never been
exercised against a live Stooq response in this environment (network
access to `stooq.com` is blocked here, same as every other
financial-data domain tried this project, ADR-0025). Every parsing
assumption lives in `normalize()` alone, so it can be corrected in one
place once real verification is possible.

**Deliberately does NOT implement corporate-action fetching.** ADR-0025
records Stooq as having "weakest documentation" for anything beyond
plain price history -- "explicitly not relied upon for corporate-action
data." Unlike `TiingoDataProvider`, this class has no
`fetch_corporate_actions`/`normalize_corporate_actions` methods; it
supplies raw price bars only. `adjusted_close` is never populated here
either, for the same reason -- fabricating an adjustment this provider's
documented shape does not confirm would violate the point-in-time
raw/adjusted separation this project enforces everywhere else.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Sequence

from data_infra.models import PriceBar, Provenance
from data_infra.provider import PermanentProviderError
from data_infra.providers.stooq_config import StooqConfig
from data_infra.providers.stooq_transport import StooqHttpTransport
from data_infra.versioning import compute_data_version

_DAILY_HISTORY_PATH = "/q/d/l/"
_EXPECTED_HEADER = ("Date", "Open", "High", "Low", "Close", "Volume")


class StooqDataProvider:
    """Implements `data_infra.provider.DataProvider` for real (not
    mock) Stooq EOD data. `retrieved_at`/`ingestion_time` are always
    derived from the caller-supplied `end` parameter (never
    `datetime.now()`/`utcnow()`), identical discipline to
    `TiingoDataProvider`."""

    def __init__(self, config: StooqConfig, transport: StooqHttpTransport) -> None:
        self._config = config
        self._transport = transport

    def _stooq_symbol(self, security_id: str) -> str:
        # Tier 2 convention: US-listed tickers are suffixed `.us` on
        # Stooq (e.g. "aapl.us") -- unverified against a live response
        # in this environment.
        return f"{security_id.lower()}.us"

    def fetch(self, security_id: str, start: datetime, end: datetime) -> list[dict]:
        params = {
            "s": self._stooq_symbol(security_id),
            "d1": start.date().strftime("%Y%m%d"),
            "d2": end.date().strftime("%Y%m%d"),
            "i": "d",
        }
        response = self._transport.get(_DAILY_HISTORY_PATH, params=params, timeout=self._config.timeout_seconds)
        if not response.raw_text:
            raise PermanentProviderError(f"empty Stooq response for {security_id}")

        reader = csv.reader(io.StringIO(response.raw_text))
        rows = list(reader)
        if not rows or tuple(rows[0]) != _EXPECTED_HEADER:
            # Stooq is documented to return a plain-text "no data" body
            # for an unrecognized symbol or an out-of-range date window
            # rather than a proper CSV header -- never guessed at, never
            # parsed as if it were valid data.
            raise PermanentProviderError(
                f"unexpected Stooq response shape for {security_id}: expected CSV header {_EXPECTED_HEADER}, "
                f"got {rows[0] if rows else '(empty)'}"
            )

        records = []
        for row in rows[1:]:
            if len(row) != len(_EXPECTED_HEADER):
                continue
            date_str, open_, high, low, close, volume = row
            records.append({
                "date": date_str, "open": open_, "high": high, "low": low, "close": close, "volume": volume,
                "security_id": security_id, "_fetched_as_of": end,
            })
        return records

    def validate(self, raw_records: Sequence[dict]) -> list[str]:
        issues: list[str] = []
        required = ("date", "open", "high", "low", "close", "volume")
        for i, record in enumerate(raw_records):
            missing = [f for f in required if f not in record]
            if missing:
                issues.append(f"record[{i}] missing fields: {missing}")
        return issues

    def normalize(self, security_id: str, raw_records: Sequence[dict]) -> list[PriceBar]:
        bars: list[PriceBar] = []
        for record in raw_records:
            timestamp = datetime.strptime(record["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            as_of = record["_fetched_as_of"]
            content_fields = {k: v for k, v in record.items() if k not in ("_fetched_as_of", "security_id")}
            provenance = Provenance(
                source="stooq",
                source_dataset=f"stooq_eod_{security_id}",
                source_record_id=f"{security_id}:{record['date']}",
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
                    available_time=timestamp,
                    ingestion_time=as_of,
                    provenance=provenance,
                    adjusted_close=None,  # never fabricated -- see module docstring
                    currency="USD",
                )
            )
        return bars

    def metadata(self) -> dict:
        return {
            "provider_id": self._config.provider_id,
            "provider_name": "Stooq",
            "rate_limit_per_minute": None,  # UNKNOWN -- see ADR-0025/ADR-0028, not asserted without Tier 1 confirmation
            "is_real_external_provider": True,
            "configuration_version": self._config.configuration_version(),
            "supports_corporate_actions": False,  # deliberately not implemented, see module docstring
        }
