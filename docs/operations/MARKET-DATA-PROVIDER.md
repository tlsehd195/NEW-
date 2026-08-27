# Market Data Provider -- Operations

Phase 20, universe superseded in Phase 22 (see below). Companion to
`docs/decisions/ADR-0025-market-data-provider-selection.md` (the *why*
for provider selection) and `docs/decisions/ADR-0028-us-longterm-paper-trading-operating-model.md`
(the *why* for the Phase 22 universe/strategy/operating-model
decisions); this document is the *what/how*: the pilot universe, the
credential this provider needs, and what remains unverified.

## Provider

**Primary: Tiingo** (`src/data_infra/providers/tiingo.py`,
`TiingoDataProvider`, implementing `data_infra.provider.DataProvider`
unmodified). Requires an API key in the environment variable
`MARKET_DATA_API_KEY` (already reserved in `.env.example` since Phase
1) -- **not set, not requested from the user this phase.** No real
network call has been made to Tiingo from this environment; see
ADR-0025's "Honest evidence-access constraint" section.

**Secondary/fallback: Stooq** -- `src/data_infra/providers/stooq.py`,
`StooqDataProvider`, implemented in Phase 22 against the same
`DataProvider` Protocol (see ADR-0028 section on Stooq for the exact
Tier 2 evidence basis and its real limitations: no corporate-action
feed, CSV rather than JSON, unauthenticated). Selects between Tiingo
and Stooq via `data_infra.providers.fallback.FallbackDataProvider`
(Phase 22, additive) -- primary-fails-try-secondary, with every
resulting record's `Provenance.source` naming which provider actually
answered, never silently presenting a fallback result as if the
primary had succeeded.

## Pilot Universe (Phase 22 -- supersedes Phase 20's list for Paper Trading)

Phase 20 originally selected a 16-symbol universe optimized for
exercising corporate-action edge cases (including GE specifically for
its reverse-split history). Phase 22's instruction specifies a
**different, fixed 16-symbol Paper Trading universe** directly --
today's actual large-cap composition rather than a
corporate-action-edge-case-optimized set. This document now treats the
Phase 22 list below as the authoritative **default Paper Trading
universe**; Phase 20's original list and rationale are kept below for
reference/history and remain valid for point-in-time/corporate-action
*testing* purposes (that test coverage lives in synthetic fixtures, not
real ingested data, so losing GE's real-world reverse-split example
from the default universe does not reduce actual test coverage).

**Phase 22 default Paper Trading universe (fixed for now; expansion is
a future phase's decision, per instruction section 4):**

| Symbol | Sector (approximate) |
|---|---|
| AAPL | Technology |
| MSFT | Technology |
| NVDA | Technology / Semiconductors |
| AMZN | Consumer Discretionary / Internet |
| GOOGL | Communication Services / Internet |
| META | Communication Services / Internet |
| AVGO | Technology / Semiconductors |
| TSLA | Consumer Discretionary / Automotive |
| JPM | Financials |
| V | Financials / Payments |
| MA | Financials / Payments |
| COST | Consumer Staples / Retail |
| WMT | Consumer Staples / Retail |
| JNJ | Healthcare |
| XOM | Energy |
| SPY | Benchmark ETF (S&P 500 proxy, not part of the equity universe itself) |

**Honest limitation carried over from Phase 20, unchanged**: no
provider has real network access verified from this environment for
any of these 16 symbols (Tiingo or Stooq) -- see "What remains
UNKNOWN" below. This list defines what *would* be ingested once access
exists; it does not itself constitute ingested data.

### Phase 20's original pilot universe (historical, kept for reference)

10-20 US large-caps was Phase 20's instructed range. That document
selected **15 equities + 1 benchmark ETF (SPY)** = 16 symbols, chosen
against these criteria (not popularity):

- **Liquidity**: every symbol is a mega/large-cap S&P 500 constituent
  with consistently high daily volume -- none should ever produce a
  "insufficient volume to compute a reference price" data-quality
  issue.
- **Long historical data availability**: every symbol has been
  continuously listed for decades, avoiding the "how does point-in-time
  ingestion behave for a security that didn't exist yet" edge case
  (a real question, but not this pilot's purpose) and giving a long
  enough history to meaningfully test the point-in-time/corporate-action
  machinery over many real historical events.
- **Corporate action history**: every symbol has a real, documented
  history of at least one stock split and regular dividends (several
  have decades of consecutive dividend payments) -- picked
  specifically so the pilot ingestion actually exercises
  `CorporateActionType.SPLIT`/`DIVIDEND`, not just price bars with an
  empty corporate-action table.
- **Sector representativeness**: spread deliberately across GICS
  sectors (not all technology) so no single sector's data
  characteristics (e.g. tech's higher volatility) dominates any later
  Paper Trading or research use of this pilot data.
- **Stable ticker history**: no symbol in this list has undergone a
  ticker-symbol change in a way that would complicate this pilot
  (`CorporateActionType.TICKER_CHANGE` handling is left for a
  future pilot expansion, deliberately not exercised here).

| Symbol | Sector | Rationale |
|---|---|---|
| AAPL | Technology | Very high liquidity, multiple historical splits, regular dividends since 2012 |
| MSFT | Technology | Very high liquidity, historical splits, long dividend history |
| IBM | Technology (legacy) | Multi-decade listed history, long dividend history, useful contrast to AAPL/MSFT's growth profile |
| JNJ | Healthcare | Multi-decade "dividend aristocrat" history, defensive sector representative |
| PFE | Healthcare | Large-cap pharma, different volatility/event profile than JNJ |
| JPM | Financials | Large-cap money-center bank, financial-sector representative |
| XOM | Energy | Multi-decade history, commodity-linked volatility profile, dividend history |
| CVX | Energy | Second energy-sector representative for within-sector contrast |
| KO | Consumer Staples | One of the longest continuously-listed dividend/split histories available |
| PG | Consumer Staples | Long dividend-aristocrat history, defensive sector representative |
| WMT | Consumer Staples / Retail | Large-cap retail, historical splits |
| HD | Consumer Discretionary | Large-cap retail/discretionary contrast to WMT |
| DIS | Consumer Discretionary / Media | Media/entertainment representative, historical splits |
| CAT | Industrials | Cyclical industrials representative, long dividend history |
| GE | Industrials | Multi-decade history **including a reverse split** -- a deliberately chosen edge case for `CorporateActionType.REVERSE_SPLIT` handling, distinct from every other pilot symbol's forward-split-only history |
| SPY | Benchmark ETF (not part of the equity pilot universe) | S&P 500 proxy -- see ADR-0025 and the benchmark ADR for why SPY, not the index itself |

## What remains UNKNOWN / not done this phase

- Tiingo's exact free-tier numeric rate limits (Tier 2 only).
- Whether `api.tiingo.com` is reachable from any real deployment
  environment (untested; blocked from this sandboxed environment).
- Whether `TiingoDataProvider`'s parsing logic matches Tiingo's actual
  live response shape (built against Tier 2 documentation of a
  long-stable, widely-referenced public API shape, not verified
  against a live response).
- No `MARKET_DATA_API_KEY` value exists anywhere in this repository or
  environment; none was requested from the user.
- No real data has been ingested for any of the 16 pilot symbols.

## Phase 23 reachability re-verification

Re-checked this session, directly rather than assumed unchanged: the
environment's egress proxy status (`curl "$HTTPS_PROXY/__agentproxy/status"`)
recorded a 403 CONNECT rejection for `api.tiingo.com`, `stooq.com`, and
`openapi.tossinvest.com` -- all three still **BLOCKED**, identical to
Phase 20's finding. No real ingestion was performed this phase either.

`scripts/ingest_real_market_data.py` was added this phase specifically
so this reachability question (and the actual ingestion it blocks) can
be answered from a different environment without needing another
Claude Code session to rebuild the wiring -- it reuses
`FallbackDataProvider`/`IngestionRunner`/`DuckDBDataRepository`/
`DataQualityFramework` exactly as they exist in `src/`, unmodified.
