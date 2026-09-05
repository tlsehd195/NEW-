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

**Session 36 addition**: `fetch_submissions`/`normalize_submissions`
(`data.sec.gov/submissions/CIK##########.json`) -- a second, distinct
EDGAR endpoint from company facts, returning one filer's entity summary
including a real SIC industry classification (`sicDescription`). The
honest counterpart to `TiingoDataProvider.normalize_symbol_metadata`,
whose own docstring flags that Tiingo's metadata endpoint never
supplies `sector`; this is the one place in this project a real,
provider-sourced `SymbolMetadata.sector` value exists, not a fabricated
GICS mapping -- see `normalize_submissions`'s own docstring for the
SIC-vs-GICS distinction.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional, Sequence

from data_infra.fundamentals_models import FundamentalRecord
from data_infra.insider_models import InsiderTransaction
from data_infra.models import Provenance
from data_infra.provider import PermanentProviderError
from data_infra.providers.sec_edgar_config import SecEdgarConfig
from data_infra.providers.sec_edgar_transport import SecEdgarHttpTransport
from data_infra.versioning import compute_data_version

_COMPANY_FACTS_PATH_TEMPLATE = "/api/xbrl/companyfacts/CIK{cik}.json"
_TICKER_MAP_PATH = "/files/company_tickers.json"  # served from www.sec.gov, a DIFFERENT host than data.sec.gov -- see fetch_ticker_map
_SUBMISSIONS_PATH_TEMPLATE = "/submissions/CIK{cik}.json"  # same host (data.sec.gov) as company facts -- see fetch_submissions
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

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

    def fetch_submissions(self, cik: str) -> dict:
        """`GET /submissions/CIK##########.json` -- EDGAR's per-filer
        entity summary (Tier 2 documentation, long-stable, publicly
        documented shape): entity name, `sic`/`sicDescription` (the SEC's
        own industry classification, the field this method exists to
        reach), `exchanges`, `tickers`, `stateOfIncorporation`, etc.
        Same host (`data.sec.gov`) as `fetch_company_facts`, unlike
        `fetch_ticker_map` -- no second transport argument needed. `cik`
        must already be the zero-padded 10-digit form, same contract as
        `fetch_company_facts`."""
        response = self._transport.get(
            _SUBMISSIONS_PATH_TEMPLATE.format(cik=cik), timeout=self._config.timeout_seconds
        )
        if not isinstance(response.body, dict):
            raise PermanentProviderError(f"unexpected SEC EDGAR response shape for CIK {cik} submissions: expected a JSON object")
        return response.body

    def normalize_submissions(self, security_id: str, raw: dict) -> "SymbolMetadata":
        """Maps EDGAR's submissions response onto `SymbolMetadata` --
        the honest counterpart to `TiingoDataProvider.normalize_symbol_
        metadata`, whose own docstring explicitly flags that Tiingo's
        `/tiingo/daily/<ticker>` endpoint never supplies `sector` ("not
        part of its documented shape... never guess a value a provider
        does not actually supply"). EDGAR's submissions response DOES
        document a real classification field (`sicDescription`, the SEC's
        own Standard Industrial Classification text, e.g. "CRUDE
        PETROLEUM AND NATURAL GAS") -- mapped onto `sector` here as the
        one genuinely provider-sourced value this project has for that
        field, not a fabricated GICS mapping. SIC and GICS are DIFFERENT
        taxonomies (SIC is the older, coarser, US-government scheme;
        GICS is the newer, finer-grained, MSCI/S&P-owned one this
        project has no licensed access to) -- `sector` here should be
        read as "this filer's SEC-assigned SIC description," not a GICS
        sector label, and any code comparing two securities' `sector`
        values is comparing SIC descriptions, not GICS sectors.

        `exchange` uses the first entry of EDGAR's `exchanges` list when
        present and non-empty (a filer can in principle be listed on more
        than one exchange; `SymbolMetadata.exchange` is a single string,
        so only the first is kept, same "one field, take the first known
        value" honesty tradeoff `_latest_price`/`_latest_fiscal_year_value`
        already make elsewhere in this project for a different kind of
        single-valued field). Every field EDGAR's own documented shape
        does not name (`market_cap_bucket`, `listed_from`, `listed_to`)
        stays `None`, unchanged from `SymbolMetadata`'s own default --
        this endpoint's shape does not name a machine-readable listing
        date."""
        from data_infra.universe import SymbolMetadata  # local import: avoids a module-level

        # providers -> universe dependency for every other use of this file.
        sic_description = raw.get("sicDescription")
        exchanges = raw.get("exchanges") or []
        exchange = next((e for e in exchanges if e), None)
        return SymbolMetadata(
            symbol=security_id,
            exchange=exchange,
            sector=str(sic_description) if sic_description else None,
            source="sec_edgar",
        )

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
                    if filed_time < period_end:
                        # A REAL, observed EDGAR data-quality issue (found
                        # via a real Stage 4 ingestion run, LMT): SEC does
                        # NOT validate filer-submitted XBRL for logical
                        # date consistency, so a small number of entries
                        # in the wild genuinely have `filed` earlier than
                        # `end` -- almost certainly a filer-side tagging
                        # error (e.g. a schedule/note item mistagged under
                        # the wrong concept or period), not a bug in this
                        # normalize() function. `FundamentalRecord.
                        # __post_init__` already refuses to construct such
                        # a record (it exists specifically to catch this
                        # class of ordering violation before storage) --
                        # skipping the single malformed entry here, same
                        # "skip rather than fabricate/crash" discipline as
                        # the missing-field check just above, is the
                        # honest choice: this one entry cannot be trusted
                        # regardless of which of its two dates is wrong,
                        # but it must not take down the rest of a real
                        # ingestion run over one bad upstream data point.
                        continue
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

    def fetch_form4_filing_list(
        self, cik: str, transport: SecEdgarHttpTransport, *, count: int = 40
    ) -> list[dict]:
        """`GET /cgi-bin/browse-edgar?action=getcompany&CIK=...&type=4&
        owner=include&output=atom` -- EDGAR's Atom feed listing an
        issuer's own Form 4 filings, one `<entry>` per filing (Tier 1:
        verified against a real response this session, ADR-0086, unlike
        every other method in this class which is Tier 2 documentation
        only). `transport` must be a `SecEdgarHttpTransport` constructed
        with `base_url="https://www.sec.gov"` -- a different host than
        `data.sec.gov`, the same two-host requirement `fetch_ticker_map`
        already documents; `/cgi-bin/browse-edgar` and `/Archives/...`
        both live on `www.sec.gov`. Returns one dict per filing:
        `{"accession_number", "filing_date", "filing_href"}`, oldest-
        first order not guaranteed (EDGAR returns newest-first; callers
        needing chronological order should sort)."""
        path = (
            f"/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4"
            f"&dateb=&owner=include&count={count}&output=atom"
        )
        response = transport.get(path, timeout=self._config.timeout_seconds)
        if not response.raw_text:
            return []
        root = ET.fromstring(response.raw_text)
        filings = []
        for entry in root.findall("atom:entry", _ATOM_NS):
            content = entry.find("atom:content", _ATOM_NS)
            if content is None:
                continue
            accession = content.findtext("atom:accession-number", namespaces=_ATOM_NS)
            filing_date_raw = content.findtext("atom:filing-date", namespaces=_ATOM_NS)
            filing_href = content.findtext("atom:filing-href", namespaces=_ATOM_NS)
            if not accession or not filing_date_raw:
                continue  # incomplete entry -- skip rather than fabricate
            filings.append({
                "accession_number": accession,
                "filing_date": _parse_edgar_date(filing_date_raw),
                "filing_href": filing_href,
            })
        return filings

    def fetch_form4_index(self, cik: str, accession_number: str, transport: SecEdgarHttpTransport) -> dict:
        """`GET /Archives/edgar/data/{cik}/{accession-no-dashes}/index.json`
        -- lists every file in one filing's own directory (Tier 1,
        verified this session). **The CIK in this path is NOT zero-
        padded**, unlike `_COMPANY_FACTS_PATH_TEMPLATE`'s -- a real,
        directly-observed difference (verified against AAPL's real CIK
        `0000320193` resolving only at `/Archives/edgar/data/320193/...`,
        never the zero-padded form), not an assumption. `transport` must
        be the `www.sec.gov` transport, same as `fetch_form4_filing_list`."""
        accession_no_dashes = accession_number.replace("-", "")
        cik_no_padding = str(int(cik))
        path = f"/Archives/edgar/data/{cik_no_padding}/{accession_no_dashes}/index.json"
        response = transport.get(path, timeout=self._config.timeout_seconds)
        if not isinstance(response.body, dict):
            raise PermanentProviderError(f"unexpected SEC EDGAR response shape for index.json at {path}: expected a JSON object")
        return response.body

    def select_form4_primary_document(self, index_json: dict) -> Optional[str]:
        """Picks the one file in a Form 4 filing's `index.json` that is
        the actual ownership-document XML. **Verified against exactly
        ONE real filing this session** (AAPL, accession
        0001140361-26-035636, whose only `.xml` file was named
        `form4.xml`) -- this heuristic (the first `*.xml` file, excluding
        XBRL-viewer rendering fragments whose names start with `R`) is
        UNVERIFIED beyond that one real sample and may need correction
        once run against a broader real set. Stated honestly as a Tier 1
        finding from a single observation, not assumed to generalize the
        way `normalize_company_facts`'s Tier 2 documentation-based
        assumptions are labeled differently."""
        items = index_json.get("directory", {}).get("item", [])
        for item in items:
            name = str(item.get("name", ""))
            if name.lower().endswith(".xml") and not name.upper().startswith("R"):
                return name
        return None

    def fetch_form4_document(self, cik: str, accession_number: str, filename: str, transport: SecEdgarHttpTransport) -> str:
        """`GET /Archives/edgar/data/{cik}/{accession-no-dashes}/{filename}`
        -- the raw ownership-document XML text (Tier 1, verified this
        session). Same non-zero-padded CIK path convention as
        `fetch_form4_index`; `transport` must be the `www.sec.gov`
        transport."""
        accession_no_dashes = accession_number.replace("-", "")
        cik_no_padding = str(int(cik))
        path = f"/Archives/edgar/data/{cik_no_padding}/{accession_no_dashes}/{filename}"
        response = transport.get(path, timeout=self._config.timeout_seconds)
        if not response.raw_text:
            raise PermanentProviderError(f"empty response fetching Form 4 document at {path}")
        return response.raw_text

    def normalize_form4_document(
        self,
        security_id: str,
        xml_text: str,
        *,
        accession_number: str,
        filing_date: datetime,
        retrieved_at: datetime,
        ingestion_time: datetime,
    ) -> list[InsiderTransaction]:
        """Parses one ownership-document XML's `nonDerivativeTable`
        into `InsiderTransaction` rows (Tier 1: schema verified against
        one real AAPL filing this session, ADR-0086). **Deliberately
        does not parse `derivativeTable`** (option exercises, RSU
        vesting, and similar equity-compensation events) -- those are a
        structurally different signal (compensation mechanics, not a
        discretionary market trade) that this project's literature
        basis (Lakonishok & Lee 2001; Seyhun 1986) is not about, and
        adding them later needs its own hypothesis, not a silent scope
        expansion of this method. `filing_date` must come from the
        Atom feed entry that pointed at this document (`available_time`
        here is the real SEC filing date, never anything parsed out of
        the document's own `periodOfReport`/`transactionDate`, exactly
        the same point-in-time discipline `InsiderTransaction`'s own
        module docstring requires). Skips any transaction row missing a
        required field rather than fabricating one -- same discipline
        `normalize_company_facts` already applies to incomplete XBRL
        entries."""
        root = ET.fromstring(xml_text)
        owner = root.find("reportingOwner")
        if owner is None:
            return []
        owner_id = owner.find("reportingOwnerId")
        cik = (owner_id.findtext("rptOwnerCik") or "") if owner_id is not None else ""
        name = (owner_id.findtext("rptOwnerName") or "") if owner_id is not None else ""
        if not cik:
            return []
        relationship = owner.find("reportingOwnerRelationship")
        is_officer = relationship is not None and relationship.findtext("isOfficer") == "true"
        is_director = relationship is not None and relationship.findtext("isDirector") == "true"
        is_ten_percent_owner = relationship is not None and relationship.findtext("isTenPercentOwner") == "true"
        officer_title = relationship.findtext("officerTitle") if relationship is not None else None
        is_10b5_1_plan = root.findtext("aff10b5One") == "true"

        table = root.find("nonDerivativeTable")
        if table is None:
            return []

        transactions: list[InsiderTransaction] = []
        for idx, txn in enumerate(table.findall("nonDerivativeTransaction")):
            date_raw = txn.findtext("transactionDate/value")
            coding = txn.find("transactionCoding")
            amounts = txn.find("transactionAmounts")
            if not date_raw or coding is None or amounts is None:
                continue
            code = coding.findtext("transactionCode")
            shares_raw = amounts.findtext("transactionShares/value")
            acquired_disposed = amounts.findtext("transactionAcquiredDisposedCode/value")
            price_raw = amounts.findtext("transactionPricePerShare/value")
            if not code or shares_raw is None or not acquired_disposed:
                continue
            content_fields = {
                "accession_number": accession_number, "row_index": idx, "transaction_date": date_raw,
                "transaction_code": code, "shares": shares_raw, "acquired_disposed": acquired_disposed,
                "price": price_raw,
            }
            transactions.append(
                InsiderTransaction(
                    security_id=security_id,
                    reporting_owner_cik=cik,
                    reporting_owner_name=name,
                    is_officer=is_officer,
                    is_director=is_director,
                    is_ten_percent_owner=is_ten_percent_owner,
                    officer_title=officer_title,
                    transaction_date=_parse_edgar_date(date_raw),
                    transaction_code=code,
                    acquired_disposed_code=acquired_disposed,
                    shares=float(shares_raw),
                    price_per_share=float(price_raw) if price_raw else None,
                    is_10b5_1_plan=is_10b5_1_plan,
                    accession_number=accession_number,
                    available_time=filing_date,
                    ingestion_time=ingestion_time,
                    provenance=Provenance(
                        source="sec_edgar",
                        source_dataset=f"sec_edgar_form4_{security_id}",
                        source_record_id=f"{accession_number}:{idx}",
                        retrieved_at=retrieved_at,
                        data_version=compute_data_version(content_fields),
                    ),
                )
            )
        return transactions

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
