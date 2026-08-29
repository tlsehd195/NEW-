"""SecEdgarFundamentalsProvider: a real (not mock) fundamentals data
source for US equities -- SEC EDGAR's XBRL "company facts" API
(`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`), a free,
official, no-API-key-required US government data source (Phase 33,
ADR-0042).

Deliberately does NOT implement `data_infra.provider.DataProvider` --
that Protocol's shape (`fetch(security_id, start, end) -> list[dict]`
returning OHLCV-like rows) does not fit a filings-based data source
where a single response already carries a company's entire multi-year
history and the natural per-record filter is "which XBRL concept", not
"which date range". This mirrors how `TiingoDataProvider` itself adds
`fetch_corporate_actions`/`fetch_symbol_metadata` as extra methods
beyond the Protocol rather than force-fitting them into it; here the
mismatch is large enough that a fresh, non-Protocol class is the more
honest design than a strained implementation of a Protocol built for a
different kind of data.

**Honesty about evidence tier**: this implementation is built against
Tier 2 (secondary/public documentation) knowledge of SEC EDGAR's
long-stable, publicly documented XBRL API shape -- it has never been
exercised against a live EDGAR response in this environment (network
access to `data.sec.gov` is blocked here; re-verified this phase, see
ADR-0042). Every parsing assumption lives in `normalize_company_facts`
alone, so it can be corrected in one place once real verification is
possible -- exactly the same isolation discipline `tiingo.py` already
established for its own unverified assumptions.

**The point-in-time-critical field**: `normalize_company_facts` maps
each EDGAR fact's own `filed` date onto `FundamentalRecord.available_time`
-- never `end` (period_end). See `data_infra.fundamentals_models`'s
module docstring for why using `end` instead would leak the future.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from data_infra.fundamentals_models import FundamentalRecord
from data_infra.models import Provenance
from data_infra.provider import PermanentProviderError
from data_infra.providers.sec_edgar_config import SecEdgarConfig
from data_infra.providers.sec_edgar_transport import SecEdgarHttpTransport
from data_infra.versioning import compute_data_version

_COMPANY_FACTS_PATH_TEMPLATE = "/api/xbrl/companyfacts/CIK{cik}.json"
_TICKER_MAP_PATH = "/files/company_tickers.json"  # served from www.sec.gov, a DIFFERENT host than data.sec.gov -- see fetch_ticker_map

# Only these two form types are treated as real financial-statement
# filings for this project's purposes -- EDGAR's company-facts response
# also mixes in amendments and other form types (10-K/A, etc.) whose
# handling is UNKNOWN/unverified, so they are excluded rather than
# silently included with an unverified assumption about how they relate
# to the original filing they amend.
_ACCEPTED_FORM_TYPES = ("10-K", "10-Q")

# The one taxonomy this project reads from -- `us-gaap`, the standard
# US GAAP concept namespace. EDGAR's company-facts response also
# carries a `dei` (Document and Entity Information) namespace for
# non-financial facts (e.g. entity name); not consumed here.
_TAXONOMY = "us-gaap"


class SecEdgarFundamentalsProvider:
    """Real (not mock) SEC EDGAR XBRL fundamentals access. Unlike
    `TiingoDataProvider`, no API key is required (SEC EDGAR is a free
    public data source) -- only a descriptive User-Agent header, which
    `SecEdgarConfig`/`SecEdgarHttpTransport` already carry."""

    def __init__(self, config: SecEdgarConfig, transport: SecEdgarHttpTransport) -> None:
        self._config = config
        self._transport = transport

    def fetch_company_facts(self, cik: str) -> dict:
        """`cik` must already be the zero-padded 10-digit form EDGAR's
        URL scheme requires (see `resolve_cik`) -- this method does not
        pad or validate it beyond that, matching `TiingoDataProvider.
        fetch`'s own "caller supplies the exact identifier the endpoint
        needs" contract."""
        response = self._transport.get(
            _COMPANY_FACTS_PATH_TEMPLATE.format(cik=cik), timeout=self._config.timeout_seconds
        )
        if not isinstance(response.body, dict):
            raise PermanentProviderError(f"unexpected SEC EDGAR response shape for CIK {cik}: expected a JSON object")
        return response.body

    def fetch_ticker_map(self, transport: SecEdgarHttpTransport) -> dict:
        """`transport` must be a `SecEdgarHttpTransport` constructed
        with `base_url="https://www.sec.gov"` -- a *different* host
        than `data.sec.gov` (this instance's own `self._transport`),
        which is why this method takes an explicit transport argument
        rather than silently using `self._transport` against the wrong
        host. Kept as an explicit parameter rather than a second config
        field so the two-host requirement can never be missed."""
        response = transport.get(_TICKER_MAP_PATH, timeout=self._config.timeout_seconds)
        if not isinstance(response.body, dict):
            raise PermanentProviderError("unexpected SEC EDGAR response shape for company_tickers.json: expected a JSON object")
        return response.body

    def normalize_company_facts(
        self,
        security_id: str,
        raw: dict,
        concepts: Sequence[str],
        *,
        retrieved_at: datetime,
        ingestion_time: datetime,
    ) -> list[FundamentalRecord]:
        """Matches only `concepts` present under the `us-gaap` taxonomy
        -- a concept absent from a given company's filings (common;
        not every company reports every concept) silently contributes
        no records for it, never a fabricated value. `retrieved_at`/
        `ingestion_time` must always be supplied explicitly by the
        caller (never `datetime.now()`/`datetime.utcnow()`), matching
        `TiingoDataProvider.normalize_corporate_actions`'s identical
        contract."""
        facts = raw.get("facts", {})
        taxonomy_facts = facts.get(_TAXONOMY, {})
        records: list[FundamentalRecord] = []

        for concept in concepts:
            concept_data = taxonomy_facts.get(concept)
            if concept_data is None:
                continue  # this company's filings never reported this concept -- not an error
            units = concept_data.get("units", {})
            for unit, entries in units.items():
                for entry in entries:
                    form_type = entry.get("form")
                    if form_type not in _ACCEPTED_FORM_TYPES:
                        continue
                    if "filed" not in entry or "end" not in entry or "val" not in entry:
                        continue  # incomplete entry -- skip rather than fabricate a missing field
                    filed_time = _parse_edgar_date(entry["filed"])
                    period_end = _parse_edgar_date(entry["end"])
                    period_start = _parse_edgar_date(entry["start"]) if entry.get("start") else None
                    accn = entry.get("accn", "")
                    content_fields = {
                        "concept": concept, "unit": unit, "end": entry["end"],
                        "start": entry.get("start"), "val": entry["val"], "form": form_type, "accn": accn,
                    }
                    records.append(
                        FundamentalRecord(
                            security_id=security_id,
                            concept=concept,
                            period_end=period_end,
                            period_start=period_start,
                            fiscal_year=int(entry["fy"]) if entry.get("fy") is not None else period_end.year,
                            fiscal_period=str(entry.get("fp", "")),
                            form_type=form_type,
                            value=float(entry["val"]),
                            unit=unit,
                            available_time=filed_time,
                            ingestion_time=ingestion_time,
                            provenance=Provenance(
                                source="sec_edgar",
                                source_dataset=f"sec_edgar_companyfacts_{security_id}",
                                # A single filing (accn) very commonly
                                # reports the SAME concept for MULTIPLE
                                # periods at once (e.g. a 10-K's balance
                                # sheet showing both the current and
                                # prior fiscal year-end, or a 10-Q
                                # showing both the current quarter and
                                # year-to-date) -- keying on accn alone
                                # (a prior version of this line) collided
                                # those distinct period observations onto
                                # the same natural key, so
                                # DuckDBFundamentalsRepository's
                                # ON CONFLICT DO NOTHING silently kept
                                # only the first and dropped the rest.
                                # Discovered from a REAL ingestion run
                                # (Phase 33, ADR-0042 Decision 7): XOM's
                                # corrected re-fetch produced 771 raw
                                # entries but only 317 distinct rows
                                # persisted under the old key. `unit` is
                                # also included since the outer loop
                                # already iterates per-unit and a concept
                                # could in principle be reported in more
                                # than one.
                                source_record_id=(
                                    f"{security_id}:{concept}:{unit}:{accn}:"
                                    f"{entry['end']}:{entry.get('start') or ''}"
                                ),
                                retrieved_at=retrieved_at,
                                data_version=compute_data_version(content_fields),
                            ),
                        )
                    )
        return records

    def metadata(self) -> dict:
        return {
            "provider_id": self._config.provider_id,
            "provider_name": "SEC EDGAR (XBRL company facts)",
            "rate_limit_per_minute": 600,  # SEC's published fair-access guidance is ~10 req/sec -- Tier 2 documentation, unverified in this environment
            "is_real_external_provider": True,
            "requires_api_key": False,
            "configuration_version": self._config.configuration_version(),
        }


def resolve_cik(ticker: str, ticker_map: dict) -> Optional[str]:
    """Pure function, no network -- looks up `ticker` (case-insensitive)
    in an already-fetched `company_tickers.json`-shaped dict (see
    `fetch_ticker_map`) and returns the zero-padded 10-digit CIK string
    `fetch_company_facts` needs, or `None` if `ticker` is not present.
    Kept separate from any fetch so it stays trivially unit-testable
    against a small synthetic map."""
    ticker_upper = ticker.upper()
    for entry in ticker_map.values():
        if str(entry.get("ticker", "")).upper() == ticker_upper:
            return str(entry["cik_str"]).zfill(10)
    return None


def _parse_edgar_date(raw: str) -> datetime:
    """EDGAR's XBRL dates are plain `"YYYY-MM-DD"` (no time component,
    Tier 2 documentation) -- interpreted as UTC midnight, matching this
    project's "every stored timestamp is timezone-aware" rule even for
    a source that itself only reports a date."""
    return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
