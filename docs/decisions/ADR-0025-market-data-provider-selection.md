# ADR-0025: Market Data Provider Selection (US Equities, Free Tier)

## Context

`ADR-0005-data-provider-strategy.md` (Phase 1) deliberately shipped no
real `DataProvider` implementation, deferring provider selection to a
dedicated future decision evaluated against explicit criteria once a
concrete need existed. Phase 20's user-set policy creates that need:
US equities, long-term investment, free-tier data, selected for fit
with this system's architecture rather than name recognition.

This ADR evaluates candidates against the 17 criteria the Phase 20
instruction specifies (coverage, historical OHLCV, corporate actions,
adjusted/unadjusted availability, point-in-time safety, rate limits,
free-tier actual limits, delay, ticker coverage, delisted-security
history, reliability, API stability, licensing, DuckDB/Parquet fit,
Paper Trading connectability, Live-architecture separability, and
benchmark/S&P 500 availability).

## Honest evidence-access constraint (mirrors the Toss situation exactly)

Every candidate provider's official documentation domain
(`alphavantage.co`, `tiingo.com`/`api.tiingo.com`, `stooq.com`,
`financialmodelingprep.com`/`site.financialmodelingprep.com`) returned
`EGRESS_BLOCKED` when fetched directly from this environment this
session -- the same network restriction already established for
Toss Securities' domains across Phase 13/17/18/19. This is not a
per-vendor block; it appears to be a blanket restriction on
financial-data-provider domains from this sandboxed environment.

Consequently, **no candidate's free-tier limits, rate limits, or exact
schema could be verified against a Tier 1 (official, directly-read)
source this session** -- every fact below is Tier 2 (aggregated from
independent secondary sources via web search), the same evidentiary
tier Phase 13 was initially stuck at for Toss before the user supplied
the real document. This ADR is explicit about that ceiling rather than
presenting Tier 2 facts as if they were confirmed. **Actual network
accessibility of the selected provider from a production environment
remains UNKNOWN/BLOCKED as verified from this session** -- this is
recorded as a real, unresolved item, not glossed over as done.

## Candidates considered

| Provider | Free tier (Tier 2, unverified) | Separate corporate-action feed | Notes |
|---|---|---|---|
| **Tiingo** | Historical EOD data described as "30+ years free" across independent sources; dedicated Splits API and Dividends API documented as distinct endpoints (not baked into one adjusted-close number) | **Yes -- explicit, separate Split/Dividend APIs** | An API key (secret) is required. Referenced by independent quant-research write-ups (e.g. QuantStart) evaluating its data coverage specifically, a mild positive signal for community reliance, not treated as proof of quality on its own. |
| **Alpha Vantage** | Free tier confirmed (Tier 2, multiple independent sources agree) at **25 requests/day, 5/minute** -- a hard, severe cap | No -- `TIME_SERIES_DAILY_ADJUSTED` bakes split/dividend effects into a single `adjusted_close` field; no separately queryable corporate-action event stream found in Tier 2 sources | The 25/day cap is workable only for an extremely slow, manual pilot; it is structurally hostile to any future periodic re-ingestion. More importantly, its adjusted-only model conflicts directly with this project's point-in-time architecture (`data_infra.models.PriceBar`/`CorporateAction` deliberately keep raw OHLCV and corporate events *separate*, per ADR-0004) -- adopting Alpha Vantage as primary would mean either not populating `CorporateAction` at all, or reverse-engineering split/dividend amounts out of an adjustment ratio, neither of which this project should do. |
| **Stooq** | No-API-key CSV endpoint (`stooq.com/q/d/l/`), commonly cited as a lightweight free source | Not documented as separate from price data in any source found | Weakest documentation of licensing/redistribution terms and long-term reliability among the four; kept only as a possible last-resort fallback, not primary, given this project's explicit "licensing/access constraints" evaluation criterion cannot be satisfied with confidence. |
| **Financial Modeling Prep (FMP)** | Free tier reported to exist across secondary sources; exact limits and corporate-action endpoint structure not independently confirmed this session | Unconfirmed | Insufficient Tier 2 evidence gathered this session to compare meaningfully against Tiingo; not selected, not ruled out -- a candidate for re-evaluation once Tier 1 access exists. |

## Decision

**Primary: Tiingo.** The deciding factor is criterion C/D (corporate
actions, adjusted vs. unadjusted) combined with criterion N
(DuckDB/Parquet + this project's existing data model fit): Tiingo is
the only candidate found this session that documents raw price data
and split/dividend events as genuinely separate resources, which is
exactly the shape `data_infra.models.PriceBar` (raw OHLCV,
`adjusted_close` kept optional and separate) and
`data_infra.models.CorporateAction` (a distinct event type with its
own `announcement_time`/`effective_time`/`event_time`) already expect
-- adopting it requires no compromise to the point-in-time architecture
Phase 1 already built. Alpha Vantage was seriously considered and
rejected specifically for the opposite reason: its severe request cap
and adjusted-only pricing model would force a structural compromise
this project should not make merely because a provider is free.

**Secondary/fallback: Stooq**, recorded but not implemented this
phase, for its zero-credential simplicity as an emergency data source
-- explicitly not relied upon for corporate-action data given its
weaker documentation.

**Not selected, not ruled out: FMP.** Insufficient evidence gathered
this session; a future session with real network access should
evaluate it before assuming Tiingo is the only viable option long-term.

## What remains genuinely unresolved

1. **Actual free-tier numeric limits (requests/day, requests/minute)
   for Tiingo** -- Tier 2 only. `docs/operations/MARKET-DATA-PROVIDER.md`
   marks this `UNKNOWN` rather than asserting a number.
2. **Actual network reachability of `api.tiingo.com` from a real
   deployment environment** -- untested this session (this sandboxed
   environment blocks it, mirroring every other financial-data domain
   tried). A future session or the eventual production deployment
   environment must verify this directly before any live ingestion is
   attempted.
3. **Full response schema for Tiingo's EOD/Splits/Dividends endpoints**
   -- the `TiingoDataProvider` implementation built this phase
   (`src/data_infra/providers/tiingo.py`) is written against the
   best-available Tier 2 description of that schema and is explicitly
   **not verified against a live response**. Every parsing assumption
   is isolated to `TiingoDataProvider.normalize()`/`validate()` so it
   can be corrected in one place once Tier 1 verification is possible,
   mirroring exactly how `broker/toss/mapping.py` isolated Toss's own
   response-parsing assumptions in Phase 13.
4. **API key acquisition** -- not requested from, or provided by, the
   user this phase; `MARKET_DATA_API_KEY` (already reserved in
   `.env.example` since Phase 1) remains unset. No real ingestion can
   run until a real key exists and reachability is confirmed.

## Alternatives Considered

1. **Select Alpha Vantage for its name recognition / commonly-cited
   free tier.** Rejected -- see Decision; the 25/day cap and
   adjusted-only pricing are real structural problems for this
   project, not merely inconveniences.
2. **Implement multiple providers simultaneously this phase.**
   Rejected -- the instruction explicitly asks for one primary
   provider implemented now, with a secondary *documented*, not built,
   to avoid unnecessary complexity before even one provider's
   reachability is confirmed.
3. **Treat Tier 2 evidence as sufficient to claim verified
   accessibility.** Rejected -- doing so would repeat exactly the
   mistake this project's own discipline (and Phase 13's original Toss
   research) exists to prevent. Accessibility is recorded as
   UNKNOWN/BLOCKED, not assumed.

## Consequences

### Positive

- A provider selection now exists with a substantive, architecture-fit
  rationale rather than "it's free" alone.
- `TiingoDataProvider` is additive (`src/data_infra/providers/`, a new
  subpackage) -- zero changes to `data_infra.provider.DataProvider`'s
  Protocol, `MockDataProvider`, or any Phase 1-19 test.
- The credential-isolation pattern Phase 13 established for
  `broker/toss/auth.py` is reused identically for market data
  (`src/data_infra/providers/tiingo_auth.py` is the only file touching
  `os.environ` for this key).

### Negative / Trade-offs

- No real data has actually been ingested this phase, and cannot be,
  given this environment's network restriction -- `TiingoDataProvider`
  is tested only against recorded/fixture HTTP responses
  (`tests/data_infra/test_tiingo_provider.py`), the same discipline
  `tests/broker/toss/test_toss_transport.py` already established for
  Toss's transport layer.
- Tiingo's exact free-tier numeric limits remain unverified; a future
  session must confirm them (or discover they are more restrictive
  than assumed) before relying on this provider for anything beyond a
  small pilot universe.
