# ADR-0160: Tiingo proactive request budget; Stooq's JS bot-challenge documented as a permanent dead end

**Status:** Accepted
**Date:** 2026-09-18
**Deciders:** Claude Code (session continued)
**Related documents:** `docs/decisions/ADR-0157-tiingo-stooq-rate-limit-and-retry-after.md`
(the immediately preceding fix this one follows up on — its own
"Negative / Trade-offs" section already flagged "no proactive
client-side request pacing was added" as a known gap), `src/data_infra/providers/tiingo_budget.py`,
`src/data_infra/providers/tiingo_transport.py`, `src/data_infra/providers/stooq.py`,
`src/data_infra/providers/fallback.py`, `scripts/ingest_real_market_data.py`

---

## Context

A real `workflow_dispatch` production run, after ADR-0157's Retry-After
fix was live, confirmed two more real facts:

1. **Tiingo's real hard limit is 50 requests/hour**, confirmed directly
   against the real account (not a Tier 2 guess — the previous
   `"rate_limit_per_minute": None  # UNKNOWN` in `tiingo.py::metadata()`
   predates this confirmation). ADR-0157's Retry-After-aware backoff is
   *reactive* — it waits and retries after a 429. That is the wrong fix
   for an *account-wide hourly quota already used up*: waiting 60
   seconds and retrying 3 times per symbol cannot refill an hourly cap
   that has already hit zero. Against a real run of ~88 symbols, this
   reactive-only behavior burns roughly 25 minutes failing one symbol
   at a time instead of failing fast in roughly 3.5 minutes once the
   quota is gone — worse than doing nothing, because it also delays
   ever reaching Stooq or giving up cleanly.

2. **Stooq's ADR-0157 User-Agent fix changed Stooq's failure mode, but
   did not fix it.** A real production log now shows Stooq responding
   HTTP 200 (not the previous 404) with a body that is an HTML page
   containing a JavaScript bot-verification challenge — the literal
   text `"This site requires JavaScript to verify your browser"` plus
   `noindex,nofollow` meta tags. This is not a header problem: no
   `User-Agent` or other request header can make a non-browser,
   `urllib`-based HTTP client pass an *active* JS challenge, because
   passing it requires actually executing JavaScript in a real browser
   engine, which this client is not.

Investigated directly against the code before deciding anything:

- `TiingoHttpTransport.get()` (`tiingo_transport.py`) is the single
  choke point every real Tiingo call passes through — `TiingoData
  Provider.fetch()`, `fetch_corporate_actions()`, and
  `fetch_symbol_metadata()` all call it, and nothing else in this
  package makes a real Tiingo HTTP request.
- `scripts/ingest_real_market_data.py` already constructs exactly
  **one** `TiingoHttpTransport` instance and passes it into exactly one
  `TiingoDataProvider` instance (`tiingo`), which is then used both via
  `FallbackDataProvider(tiingo, stooq)` (the `IngestionRunner` path)
  **and** directly for the `fetch_corporate_actions` loop below it. The
  two real call paths already share one provider/transport instance —
  they were never actually split into two, just never given any
  budget tracking at all.
- `StooqDataProvider.fetch()`'s existing CSV-header check
  (`stooq.py`) already rejects a non-CSV body (including the JS
  challenge page, whose first "row" is HTML, not
  `("Date","Open","High","Low","Close","Volume")`) as
  `PermanentProviderError` — no code change was needed to make this
  failure safe, only to document it.
- `FallbackDataProvider`'s dual-failure branch (`fallback.py`) only
  stays `PermanentProviderError` (no further `IngestionRunner` retry)
  when **both** underlying failures are `PermanentProviderError`; if
  either side is `TransientProviderError`, the combined failure is
  re-raised as Transient and `IngestionRunner` retries it. A
  budget-exhaustion failure must therefore be Permanent, or retrying a
  provably-exhausted hourly quota would be attempted anyway.

## Decision

### 1. `TiingoRequestBudget` — proactive, rolling-window request tracking

New `src/data_infra/providers/tiingo_budget.py`: a small class tracking
individual request timestamps in a **rolling** 1-hour window (not a
fixed hourly bucket) — chosen because Tiingo's real quota is naturally
rolling (each request's own hour-ago mark is when it stops counting),
and a fixed window can under-count right after its own reset boundary
even though 50 real requests landed in the last real 60 minutes.

- `record_request()` — call once for every real HTTP call actually
  made (including one that goes on to fail; Tiingo's server-side quota
  counts it regardless of the response).
- `remaining()` / `would_exceed()` — read-only checks, always computed
  after pruning entries older than the window.
- A `safety_margin` (default 2, against the real 50/hour cap — i.e.
  exhaustion is declared at 48 in-window requests, not 50) is reserved
  headroom: small enough not to waste much real quota, large enough
  that this class's own bookkeeping (or a stray untracked call) cannot
  itself be what tips the real account over its real limit.

### 2. Owned by `TiingoHttpTransport`, checked before every real call

`TiingoHttpTransport.__init__` now takes an optional `budget:
TiingoRequestBudget`, defaulting to a fresh instance-owned one when
omitted (every existing call site in this repository constructs
`TiingoHttpTransport(base_url)` with no `budget` argument, and must
keep working unchanged). `get()` checks `would_exceed()` **before**
building the request; if the budget is exhausted, it logs a warning and
raises `PermanentProviderError` — never `TransientProviderError` (see
Context, `FallbackDataProvider`'s classification) — naming the
exhaustion explicitly, so an operator reading a failure can tell
"budget exhausted, skipped N symbols" apart from "provider actually
broken." No request is wasted proving the obvious once exhausted.

Putting the check at this layer, rather than inside `TiingoDataProvider`
or threading a parameter through `scripts/ingest_real_market_data.py`,
covers every method that reaches Tiingo (`fetch`,
`fetch_corporate_actions`, `fetch_symbol_metadata`) for free, and the
two real call paths (`IngestionRunner`'s `FallbackDataProvider.fetch()`
and the script's direct `fetch_corporate_actions` loop) already share
one `TiingoHttpTransport` instance today — so they now share one budget
automatically, with **no change needed to the script's construction
code**, which was verified directly rather than assumed.

### 3. Stooq's JS challenge documented as a permanent, non-fixable-via-HTTP dead end

`stooq.py`'s existing CSV-header-mismatch check already correctly
rejects the JS-challenge response as `PermanentProviderError` (its
first row is not the expected CSV header) — a comment was added at that
exact site pointing at this ADR, so a future reader does not mistake
the HTTP 200 for a working response and does not attempt another
header/User-Agent-based fix, which cannot work against an active JS
challenge from a non-browser client.

**Headless-browser automation was explicitly considered and rejected**
as out of scope: it would add a new, heavy dependency (a real browser
engine) to a stdlib-only provider layer, for a fallback provider ADR-0025
already recorded as having "weakest documentation" and "explicitly not
relied upon for corporate-action data"; it could not be verified from
this sandbox (network access to `stooq.com` is blocked here, same as
every other financial-data domain this project has tried); and running
a real browser against a site whose own challenge exists specifically
to detect and block non-human/automated clients is a materially
different risk/legitimacy posture than sending a descriptive HTTP
header (the class of fix ADR-0157 made, and the class every other
provider in this package uses).

**Operational implication**: Stooq effectively never succeeds as a
fallback right now. `FallbackDataProvider`'s existing behavior already
handles this gracefully with no further code change needed — a
Tiingo-budget-exhausted `PermanentProviderError` combined with a
Stooq-JS-challenge `PermanentProviderError` is a dual-Permanent
failure, which stays Permanent (see Context) and lets `IngestionRunner`
stop cleanly on that symbol instead of retrying. The combined failure
message already names both providers and both real reasons
(`fallback.py`'s existing `message` construction), and
`ingest_real_market_data.py` already surfaces per-symbol errors to
stdout (`Non-SUCCESS per-symbol ingestion results`) and into the
manifest (`per_symbol_results`/`corporate_actions_per_symbol`) — an
operator reading either already sees the real reason, not a silent
gap. No new runtime warning log was added on top of this, since the
existing failure path already makes the condition visible; this
judgment call is recorded here rather than left implicit.

## Consequences

### Positive

- A real, confirmed Tiingo quota exhaustion now fails fast (one
  `PermanentProviderError` per remaining symbol once the budget is
  gone) instead of spending the retry budget proving the obvious on
  every one of them.
- Both real call paths that hit Tiingo share one counter without any
  script-level wiring change, because they already shared one
  transport instance — verified, not assumed.
- The account's real 50/hour cap is never itself exceeded by this
  client's own request pattern, with a documented 2-request safety
  margin.
- Stooq's real, confirmed failure mode is now explained at the exact
  site a future reader would otherwise be tempted to "fix" again with
  another header change that cannot work.
- `Stooq` never previously required any code change to fail safely
  (verified, not assumed) — this ADR closes out that investigation
  without introducing new, likely-brittle browser-automation code.

### Negative / Trade-offs

- The 2-request safety margin (48 of 50 treated as the effective cap)
  is a judgment call, not derived from any documented Tiingo behavior
  — if the real account's rolling-window accounting differs subtly
  from this class's own (e.g. a slightly different window length), the
  margin may be slightly too generous or slightly too tight. It is
  cheap to change in one place (`TiingoRequestBudget`'s default
  arguments) if a future real run shows it needs adjustment.
- The budget is process-local (in-memory), not persisted — a fresh
  process (e.g. a retried CI job) starts with a full budget even if
  the account's real quota is still exhausted from a previous process
  in the same real hour. This project's ingestion is a single
  short-lived CLI invocation per scheduled run, so this is an accepted
  gap, not a fix deferred by oversight: persisting request timestamps
  across process boundaries (e.g. to the DuckDB catalog) is a larger
  design this ADR does not undertake.
- Stooq remains effectively non-functional as a fallback provider for
  the foreseeable future — this ADR documents that fact rather than
  resolving it; if Stooq's own challenge policy changes, or a different
  no-auth secondary provider is chosen, the actual fallback capacity
  problem (this project effectively runs on Tiingo alone right now)
  is a separate decision this ADR does not make.

## Tests

- `tests/data_infra/test_tiingo_budget.py` (new, 19 tests): construction
  validation, `remaining()`/`would_exceed()` boundary behavior exactly
  at the safety-margined cap, rolling-window rollover (partial and
  full), and two independent callers sharing one instance's counter —
  all against an injected fake clock, never real `time.sleep`/wall-clock
  waits.
- `tests/data_infra/test_tiingo_transport.py`: new `TestRequestBudget`
  (7 tests) — an exhausted budget raises `PermanentProviderError`
  (never `TransientProviderError`) before any network call is made; a
  request within budget still succeeds and consumes one slot; a shared
  budget object is consumed correctly across repeated calls and across
  two separate transport instances; the instance-owned default budget
  (no explicit `budget` argument, matching every real call site) still
  enforces the real cap.
- `tests/data_infra/test_ingest_real_market_data_wiring.py`: new
  `TestTiingoRequestBudgetSharedAcrossBothCallPaths` (2 tests, AST/
  source-text based like this file's existing tests, since the script
  is never imported/executed by the automated suite) — regression-locks
  that exactly one `TiingoHttpTransport` is constructed and that the
  same `tiingo` variable backs both the `FallbackDataProvider` call
  path and the direct `fetch_corporate_actions` loop.
- **Verification discipline**: `tiingo_transport.py`'s fix was
  temporarily reverted with `git stash push -- src/data_infra/providers/tiingo_transport.py`
  (leaving the new tests in place) and the new `TestRequestBudget`
  tests were re-run — all 6 failed exactly as expected (a `TypeError`
  for the now-missing `budget` keyword argument, or `DID NOT RAISE
  PermanentProviderError` for the default-budget test), confirming
  they actually catch the real gap rather than passing vacuously. The
  fix was then restored with `git stash pop` and the full suite
  re-confirmed green.
- Full suite re-run: see PR for the exact pass count.

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed.
