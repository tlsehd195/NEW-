# Market Data Provider -- Operations

Phase 20. Companion to `docs/decisions/ADR-0025-market-data-provider-selection.md`
(the *why*); this document is the *what/how*: the pilot universe, the
credential this provider needs, and what remains unverified.

## Provider

**Primary: Tiingo** (`src/data_infra/providers/tiingo.py`,
`TiingoDataProvider`, implementing `data_infra.provider.DataProvider`
unmodified). Requires an API key in the environment variable
`MARKET_DATA_API_KEY` (already reserved in `.env.example` since Phase
1) -- **not set, not requested from the user this phase.** No real
network call has been made to Tiingo from this environment; see
ADR-0025's "Honest evidence-access constraint" section.

**Secondary/fallback: Stooq** -- documented, not implemented this phase.

## Pilot Universe

10-20 US large-caps was the instructed range. This document selects
**15 equities + 1 benchmark ETF (SPY)** = 16 symbols, chosen against
these criteria (not popularity):

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
