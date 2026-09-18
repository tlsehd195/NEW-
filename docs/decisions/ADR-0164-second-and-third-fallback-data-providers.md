# ADR-0164: Add Twelve Data and Alpha Vantage as a 2nd/3rd fallback tier, replacing Stooq

**Status:** Accepted
**Date:** 2026-09-18
**Deciders:** Claude Code (session continued), account owner (chose the
candidate providers, obtained the real API keys, and ran the live
verification calls this ADR's evidence is built on)
**Related documents:** `docs/decisions/ADR-0160-tiingo-proactive-budget-and-stooq-js-challenge-dead-end.md`
(Stooq's permanent dead end; Tiingo's real ~48/hour proactive budget
cap), `docs/decisions/ADR-0025-market-data-provider-selection.md`
(the original Tiingo/Stooq selection)

---

## Context

ADR-0160's proactive Tiingo request budget made a pre-existing capacity
problem visible for the first time: `RESEARCH_UNIVERSE` (Stage 4) has
grown to 87 symbols, but Tiingo's real free-tier account limit is only
~50 requests/hour (48 after ADR-0160's safety margin). A real
`workflow_dispatch` run (2026-09-18, run `35337636963`) confirmed this
directly -- the ingestion step failed with `Tiingo request budget
exhausted` for 39 symbols, Stooq (the only configured fallback) failed
every one of those 39 with its own already-documented permanent dead
end (a JS bot-verification challenge page, ADR-0160), the whole cycle
exited non-zero, and the Discord notification step (itself correctly
configured) had no report file to send. `scripts/ingest_real_market_
data.py` iterates `list(universe.symbol_ids)` in a fixed order, so this
is not a one-off: the SAME first 48 symbols succeed and the SAME
remaining 39 fail every single cycle, a permanent blind spot for that
tail, not a transient slowdown.

The account owner obtained free-tier API keys for three real
candidates (Alpha Vantage, Twelve Data, Polygon.io) and ran a manual
verification script against three of the actually-starved tickers
(SO, MS, WFC) directly from their own machine (this session's own
egress is blocked from all three domains, confirmed by direct `curl`).
Real results pasted back:

- **Alpha Vantage**: HTTP 200, real daily OHLCV returned for all 3.
- **Twelve Data**: HTTP 200, real daily OHLCV returned for all 3.
- **Polygon.io**: HTTP 403 `NOT_AUTHORIZED` ("Your plan doesn't include
  this data timeframe") for all 3 -- the free tier rejected the
  requested (2024) date range. Not pursued further: Twelve Data alone
  already fully covers the need (see below), so a third working
  provider was not required, and Polygon's free-tier date-range
  restriction was not investigated further (e.g. querying a recent
  date range instead) since the search a second real candidate was
  already unnecessary.
- Two additional named candidates were investigated and rejected before
  reaching this decision, on real evidence rather than assumption:
  **FMP** (already integrated elsewhere in this project,
  `fmp_delisted_price_import.py`) was re-checked against ADR-0128's own
  finding that its free tier gates `historical-price-eod/full` by an
  undocumented per-symbol whitelist (only 7 of 191 previously-tested
  tickers were queryable) -- unusable for arbitrary `RESEARCH_UNIVERSE`
  members. **Finnhub** was checked via public documentation/a GitHub
  issue thread confirming its free tier now returns HTTP 403 on
  `/stock/candle` for US equities (moved to a paid tier) -- the exact
  endpoint this project would need.

Twelve Data's published free-tier limit (8 requests/minute, 800/day) is
comfortably above the ~39/day this chain needs to cover Tiingo's
overflow alone, making it sufficient on its own; Alpha Vantage (25/day)
is kept as a third-tier safety net for the rare case Twelve Data itself
fails for a given symbol, not as a primary overflow handler.

## Decision

**Twelve Data and Alpha Vantage replace Stooq as the 2nd/3rd tier of
the real market-data fallback chain** in `scripts/ingest_real_market_
data.py`: `FallbackDataProvider(tiingo, twelvedata, alphavantage)`.
Stooq's own module/tests are left in place (still a truthful,
documented record of ADR-0160's dead-end finding) but are no longer
constructed anywhere in this script -- it is fully out of the live
ingestion path.

New provider stacks, each mirroring `TiingoDataProvider`/
`StooqDataProvider`'s existing pattern exactly (config dataclass, an
isolated `*_auth.py` resolving its own environment variable,
`*_transport.py` handling real HTTP-level failures, and the provider
class itself handling `fetch`/`validate`/`normalize`/`metadata`):

- `src/data_infra/providers/twelvedata*.py` -- `TWELVEDATA_API_KEY`.
  Success response shape (`{"meta", "values": [{"datetime", "open",
  "high", "low", "close", "volume"}]}`) is Tier 1 evidence (the account
  owner's own real response). Twelve Data reports quota/rate-limit
  rejections as HTTP 200 with an error object in the body
  (`{"code": 429, "status": "error", ...}`) rather than a real HTTP
  error status -- a documented API quirk (Tier 2), handled in
  `fetch()`'s own body-shape branch, isolated so it can be corrected in
  one place if real behavior differs.
- `src/data_infra/providers/alphavantage*.py` -- `ALPHAVANTAGE_API_KEY`.
  Success response shape (`{"Meta Data", "Time Series (Daily)":
  {"<date>": {"1. open", ...}}}`) is likewise Tier 1. No native
  date-range query parameter exists on `TIME_SERIES_DAILY`, so this
  provider always requests `outputsize=full` and filters to
  `[start, end]` itself in `fetch()` (an accepted, documented tradeoff
  -- larger response payload for guaranteed correctness at any date
  range, acceptable since this is the least-frequently-reached tier).
  Rate-limit/quota rejections likewise arrive as HTTP 200 with an
  `"Error Message"`/`"Note"`/`"Information"` key (Tier 2 documentation).

Neither new provider implements corporate-action fetching (same
reasoning `StooqDataProvider` already gave: Tiingo remains this
project's sole corporate-action source, called directly on the `tiingo`
instance, never through `FallbackDataProvider`), and neither populates
`adjusted_close` (neither free endpoint returns one).

**`FallbackDataProvider` itself was widened from a fixed 2-provider
composition to an ordered N-provider chain** (`__init__(self, primary,
secondary, *rest)` -- 2-argument construction is unchanged everywhere
it already exists). Nesting two `FallbackDataProvider` instances to
reach a 3rd tier was tried first and rejected on real evidence, not
theory: reproduced directly against `MockDataProvider` before writing
any fix, an outer instance's `fetch()` unconditionally overwrites
`_answered_by` with its own secondary's `metadata()["provider_id"]`
(always the constant string `"fallback"` for a nested instance),
destroying the inner instance's real stamp; `normalize()`/`validate()`
then strip `_answered_by` before delegating to that nested instance, so
its own `_group_by_provider` sees no `_answered_by` at all and raises
`PermanentProviderError` on every record -- a full crash on the exact
path this whole ADR exists to fix, not a cosmetic issue. The widened,
flat implementation keys `_by_id` by every real provider's own id
directly, with no recursion and no synthetic "fallback" id to collide
on.

## Consequences

### Positive

- Closes the real, reproduced production failure: the 39 symbols
  Tiingo's budget cannot reach in a given cycle now have a real,
  working fallback instead of a dead one, without waiting on a day-
  spanning rotation scheme or a paid Tiingo plan.
- `FallbackDataProvider`'s widened N-provider support is itself a real,
  tested fix to a genuine bug (the nesting crash above), not just this
  ADR's own plumbing -- any future 4th-tier addition can extend the
  same flat chain rather than repeating the nesting mistake.
- Both new providers' success-response parsing is Tier 1 evidence (a
  real response the account owner fetched themselves), a stronger
  starting evidence tier than Tiingo/Stooq's original Tier-2-only
  implementations had at their own introduction.

### Negative / Trade-offs

- The error-body-shape handling (rate-limit/quota detection) for both
  new providers is still Tier 2 (public documentation only, not
  exercised live in this environment or the account owner's own test
  run, which only exercised the success path) -- isolated entirely in
  each provider's own `fetch()` so it can be corrected in one place if
  a real rate-limit response ever differs from the documented shape.
- Polygon.io was not pursued as a 4th tier after its free-tier
  date-range rejection, since Twelve Data alone already resolves the
  capacity gap -- if Twelve Data's real sustained throughput ever
  proves insufficient, Polygon.io (with a recent, in-range date query)
  remains an uninvestigated option, not a ruled-out one.
- `FallbackDataProvider.metadata()`'s `primary_provider_id`/
  `secondary_provider_id` fields still only name the first two tiers of
  the chain (kept for exact backward compatibility with existing
  callers/tests) -- the new `provider_ids` field is the correct way to
  see the full ordered chain when there are more than two.

## Tests

44 new tests: `test_twelvedata_provider.py`/`test_twelvedata_transport.py`/
`test_alphavantage_provider.py`/`test_alphavantage_transport.py` (fetch/
validate/normalize/metadata protocol conformance, error-body-shape
mapping, no-secret-in-headers, `IngestionRunner` end-to-end -- same
categories `test_stooq_provider.py`/`test_stooq_transport.py` already
established), plus `test_tiingo_auth.py`'s secret-isolation AST scan
widened to the two new per-provider auth modules.

5 new tests in `test_fallback_provider.py::TestThreeTierChain`
regression-test the nesting bug directly: falling through to a real
3rd tier, `_answered_by`/`provenance.source` never showing the nesting
bug's "fallback"/an earlier tier's name, all-three-failed naming all
three providers, `provider_ids` metadata, and an `IngestionRunner`
end-to-end run through all three tiers. `test_ingest_real_market_data_
wiring.py` updated for the new source text (still AST/source-only,
never imports the script -- unmodified discipline).

`test_paper_trading_cycle_workflow.py` gained a test confirming
`TWELVEDATA_API_KEY`/`ALPHAVANTAGE_API_KEY` are wired via the
`secrets` context in the ingestion step's `env:` block, never a literal
value.

Full suite re-run: see `docs/PROJECT_STATUS.md`'s session log for the
exact before/after counts.

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete. Requires the account owner to
add `TWELVEDATA_API_KEY`/`ALPHAVANTAGE_API_KEY` as GitHub repository
secrets (same mechanism as `DISCORD_WEBHOOK_URL`, ADR-0146) before the
next real scheduled/`workflow_dispatch` run can exercise this chain for
real -- this session's own egress cannot verify that end-to-end run
directly (both domains return a 403 CONNECT rejection here, same as
every other market-data provider domain, ADR-0025).

## Follow-up correction (same day, first real end-to-end run)

The account owner added both secrets and triggered a real
`workflow_dispatch` run (`35345167963`) immediately after this ADR's
initial merge. It still failed, surfacing two real gaps neither
provider's Tier-2-only original implementation had caught:

1. **Alpha Vantage's `outputsize=full` is a paid-only feature.** Every
   real call was rejected with `"The outputsize=full parameter value is
   a premium feature for the TIME_SERIES_DAILY endpoint"` -- this ADR's
   original "always request full for date-range correctness" decision
   was itself never actually verified against a real free-tier call
   before being written. Fixed by switching to `outputsize=compact`
   (the only option the free tier actually serves) -- see the real,
   accepted limitation this reintroduces, documented directly in
   `alphavantage.py`'s own module docstring.
2. **Twelve Data's real 8/minute limit was hit immediately** by the
   ~39-symbol burst with no pacing between calls at all -- confirmed
   directly in the run's own logs (`TransientProviderError(rate limited
   calling /time_series)` repeated across most of the tail-39 symbols).
   Fixed by adding `TwelveDataRateLimiter` (`twelvedata_ratelimit.py`),
   a proactive per-minute pacer `TwelveDataHttpTransport.get()` now
   consults before every real call -- sleeping until safe rather than
   refusing (Twelve Data's per-minute window genuinely clears within
   seconds, unlike Tiingo's per-hour cap), same category of real-usage
   gap `TiingoRequestBudget`/ADR-0160 already found and fixed for
   Tiingo, just discovered one layer later because this ADR's own first
   real run only exercised the success path, never a real sustained
   burst.

Both gaps existed because this ADR's Tier 1 evidence (the account
owner's manual test script) exercised each provider with only 3 calls,
spaced well apart, using default parameters that happened not to hit
either free-tier gate -- sufficient to confirm the response *shape*,
not sufficient to exercise the free tier's real request-volume/
parameter restrictions under this project's actual 39-symbol daily
load. Neither gap was a reason to distrust the original evidence; both
are the correct next thing a real production run is supposed to find.

3 new tests for `TwelveDataRateLimiter` (`test_twelvedata_ratelimit.py`)
plus 2 more in `test_twelvedata_transport.py` confirming
`TwelveDataHttpTransport.get()` actually consults a shared limiter
(mirroring `TiingoHttpTransport`'s own `TestRequestBudget` coverage),
and `test_alphavantage_provider.py` updated for `outputsize=compact`.
Full suite re-run: see `docs/PROJECT_STATUS.md`'s session log for the
exact before/after counts.

**Still pending**: a second real `workflow_dispatch` run to confirm
these two fixes actually resolve the failure end-to-end (this session's
own egress cannot make that call directly).
