# ADR-0033: Real Historical US Equity Data Source Decision Tree (Phase 30)

**Status:** Accepted

## Context

Phase 30 asks for a systematic evaluation of practical sources for a
2010-latest, broad, survivorship-aware US equity dataset (instruction
sections 3-6), and explicitly forbids assuming a provider supplies
survivorship-bias-free historical universe data without evidence.

This session's network egress remains blocked to every market-data
provider host tested (re-confirmed this phase -- see the Phase 30
Addendum in `docs/research/STRATEGY-VALIDATION-REPORT.md`), so nothing
below was live-tested against a real API response. This is desk
research from each provider's own public documentation and third-party
technical write-ups, gathered via web search this session (source URLs
cited inline) -- the same "Tier 2 documentation, never live-verified"
discipline this project has used since Phase 20 for Tiingo's corporate
actions and symbol metadata endpoints
(`docs/operations/MARKET-DATA-PROVIDER.md`). A "REALISTIC" rating below
means "documented capability, not yet confirmed against this system's
actual parsing/normalization code" -- never "verified."

## Decision 1 -- Three distinct universe concepts (instruction section 5)

The instruction requires this project to stop treating three different
questions as interchangeable:

| Concept | Question it answers | This project's current instance |
|---|---|---|
| **Historical price universe** | Which securities have *any* price observations in the store? | Whatever `IngestionRunner` has actually ingested (currently: nothing real -- `data/` is empty). |
| **Historical tradable universe** | Which securities could a strategy have reasonably selected at a historical date? | `UniverseDefinition` + `SecurityMaster.valid_from/valid_to` + `UniverseMembership.valid_from/valid_to`, queried via `DataRepository.get_universe(as_of_time=...)` (Phase 1/29). |
| **Historical index constituent universe** | Which securities were *members of a specific named index* (e.g. S&P 500) at a historical date? | **Not modeled by this project at all.** `PILOT_UNIVERSE_V1`'s own docstring already disclaims this explicitly: "not a claim of index representativeness." |

This project's `UniverseDefinition.role` is `"PILOT"` or `"RESEARCH"` --
never `"INDEX"` -- and no code path claims S&P 500 (or any other named
index) membership. This ADR makes that distinction an explicit,
named decision rather than an implicit property nobody had to state
before Phase 30 asked for it; no code changed as a result (the
existing `PILOT_UNIVERSE_V1`/`RESEARCH_UNIVERSE_STAGE1` descriptions
already avoided the conflation this section warns against).

A "historical price universe" ingested by `ingest_real_market_data.py`
must never be treated as a "historical tradable universe" without the
explicit `SecurityMaster`/`UniverseMembership` step
(`build_security_masters`/`build_universe_memberships`, Phase 24/29) --
this is already how the script is wired (it populates both, not price
bars alone), so this is a documentation decision, not a code change.

## Decision 2 -- Provider capability classification (instruction section 4)

Classified across the instruction's six required dimensions.
`REALISTIC` = the provider's own documentation states this capability
exists and is plausible for this project's needs; `PARTIAL` = exists
but with a material, documented gap; `INSUFFICIENT` = documented as
absent or acknowledged-unreliable; `UNKNOWN` = could not be determined
from what this session could reach (web search results only -- the
provider's own API was never queried).

| Provider | Historical prices | Delisted securities | Ticker changes | Corporate actions | Historical universe membership | Point-in-time metadata | Licensing/access |
|---|---|---|---|---|---|---|---|
| **Tiingo** (this project's primary, ADR-0025) | REALISTIC -- 30+ years, ~37k US/Chinese stocks documented ([tiingo.com](https://www.tiingo.com/products/stock-api)) | PARTIAL -- delisting dates appear in metadata (e.g. a documented Genentech/DNA 2010 delisting example), but this project's own `fetch_symbol_metadata` (Phase 29) only maps `startDate`/`endDate`, nothing about *why* a security left (merger vs. plain delisting) | INSUFFICIENT (from this project's own perspective) -- Tiingo documentation doesn't describe a ticker-history/predecessor-symbol endpoint this project could find; unconfirmed | REALISTIC -- already integrated (`fetch_corporate_actions`, Phase 20) | INSUFFICIENT -- no named-universe/index-constituent-history endpoint found | UNKNOWN -- free-tier request/date limits could not be confirmed from documentation alone in earlier phases either (Phase 24 finding, unchanged) | Commercial, has a free tier (`MARKET_DATA_API_KEY` already the project's config point) |
| **Stooq** (fallback, ADR-0028) | PARTIAL -- free CSV daily bars, but "none of the free sources guarantee a complete delisted universe" per third-party review ([QuantStart](https://www.quantstart.com/articles/an-introduction-to-stooq-pricing-data/)) | INSUFFICIENT -- no dedicated delisted-securities feed; already known in this project (`supports_corporate_actions == False`, ADR-0028) | INSUFFICIENT | INSUFFICIENT (ADR-0028, pre-existing finding) | INSUFFICIENT | UNKNOWN | Free, no documented formal terms found this session |
| **Nasdaq Data Link (Quandl)** | PARTIAL -- free "Wiki" dataset (3000+ US equities, discontinued/frozen per general knowledge, unconfirmed this session) vs. paid Sharadar SEP (21,000+ active+delisted tickers back to 1998) ([help.data.nasdaq.com](https://data.nasdaq.com/databases/SEP)) | REALISTIC, but **only on the paid Sharadar tier** -- the free tier does not appear to include it | UNKNOWN | REALISTIC on Sharadar (splits/dividends/delist reasons documented); UNKNOWN on the free tier | INSUFFICIENT -- found no evidence of index-constituent history even on the paid tier | UNKNOWN | Paid tier required for delisted coverage -- a licensing decision this session cannot make unilaterally |
| **Polygon.io** | REALISTIC -- documented coverage from 2003-2004 | PARTIAL -- vendor claims full coverage "since 2003" on paid tiers, but independent reviews describe delisted-ticker *metadata* (company name, industry code) as "spotty at best" ([Medium reviews](https://medium.com/@yolotrading/a-complete-review-of-the-polygon-io-api-everything-you-wanted-to-know-c79e992a74ff)) -- prices vs. metadata completeness are separate claims here | UNKNOWN | UNKNOWN (not found in this session's search results) | INSUFFICIENT -- no index-constituent-history evidence found | UNKNOWN | Paid tiers required for full historical + delisted coverage |
| **Alpha Vantage** | PARTIAL -- 20+ years documented, but free tier capped at 25 requests/day, 5/minute ([alphavantage.co](https://www.alphavantage.co/documentation/)) -- a real constraint against "broad universe" (hundreds/thousands of symbols would take weeks at this rate) | UNKNOWN -- no delisted-securities endpoint found in this session's search | UNKNOWN | REALISTIC -- `TIME_SERIES_DAILY_ADJUSTED` documented to include split/dividend history | INSUFFICIENT | UNKNOWN | Free tier exists but rate-limited to the point of being INSUFFICIENT for "broad universe" alone |
| **Financial Modeling Prep** | PARTIAL -- has a documented Delisted Companies endpoint (`/api/v3/delisted-companies`) ([site.financialmodelingprep.com](https://site.financialmodelingprep.com/developer/docs/delisted-companies-api)) | REALISTIC (dedicated endpoint exists) -- but this session found no information on how far back its price history for those delisted names actually reaches | UNKNOWN | UNKNOWN (not found in this session's search results) | UNKNOWN | UNKNOWN | Delisted endpoint appears gated to paid plans per the pricing page found |
| **CRSP** (via WRDS) | REALISTIC -- the academic gold standard, PERMNO permanent identifier explicitly designed for this exact problem ([crsp.org](https://www.crsp.org/research/crsp-survivor-bias-free-us-mutual-funds/)) | REALISTIC -- purpose-built survivorship-bias-free design | REALISTIC (PERMNO tracks identity through ticker/name changes by design) | REALISTIC | REALISTIC (for equities; the mutual-fund product found in this search is a different CRSP product, not the equity one this project would need) | REALISTIC | **INSUFFICIENT for this project** -- requires an academic/institutional WRDS subscription; nothing in this session indicates the user has one, and this project has no mechanism to acquire one autonomously |

## Decision 3 -- No provider selection is made this phase

This ADR does not choose a new primary provider. Tiingo/Stooq
(ADR-0025/ADR-0028) remain the project's configured providers --
switching primary data source is a licensing/cost decision for the
user, not something this session can decide unilaterally (instruction
section 13: never ask the user to paste a key into this conversation;
a provider switch would additionally require a new
`*_transport.py`/`*_provider.py` implementation this phase did not
build, since doing so without ever being able to test it against a
live response would be exactly the kind of unverified code this
project's discipline avoids). If the user has CRSP/WRDS access
already, that is the strongest documented option for the
survivorship-bias-free universe the instruction ultimately wants — but
acquiring and wiring that access is future work requiring the user's
own institutional credentials, entered only via the existing
`MARKET_DATA_API_KEY`-style environment-variable mechanism, never
through this conversation.

## Consequences

- No code in this repository changed as a result of this ADR beyond
  what Decision 1 already documents as a pre-existing, correct
  behavior. This is a desk-research/documentation deliverable only.
- A future phase with real network access can use this table to decide
  where to spend a first real ingestion attempt, but should still
  live-verify any specific endpoint before trusting it -- every rating
  here is bounded by "documented," never "confirmed."
- `RESEARCH_UNIVERSE_STAGE1`'s honesty discipline (no guessed
  provider limits, ADR-0030/ADR-0032) extends naturally to this table:
  every `UNKNOWN` cell above stays `UNKNOWN` until an actual response
  is observed, not filled from general impression.
