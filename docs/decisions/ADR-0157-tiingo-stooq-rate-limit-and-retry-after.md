# ADR-0157: Respect real Retry-After on rate limits; send a real User-Agent to Stooq

**Status:** Accepted
**Date:** 2026-09-18
**Deciders:** Claude Code (session continued)
**Related documents:** `docs/decisions/ADR-0156-scope-paper-store-backup-to-ledger-tables.md`
(the immediately preceding real-run failure this same investigation
followed), `src/data_infra/provider.py`, `src/data_infra/providers/tiingo_transport.py`,
`src/data_infra/providers/stooq_transport.py`, `src/data_infra/providers/fallback.py`

---

## Context

The same `workflow_dispatch` run that surfaced ADR-0156's backup bug
([run 35301240320](https://github.com/tlsehd195/NEW-/actions/runs/35301240320))
also failed its "Ingest latest market data" step for 7 real symbols
(MS, WFC, AXP, LLY, TMO, ABT, ADBE):

```
both providers failed for MS: tiingo=TransientProviderError(rate limited
calling /tiingo/daily/MS/prices); stooq=PermanentProviderError(Stooq
request to /q/d/l/ failed with status 404)
```

Investigated directly against the actual code (not assumed):

1. **Tiingo's 429 is real**, confirmed at `tiingo_transport.py`'s own
   status-code handling — Tiingo's server genuinely rate-limited this
   run. `IngestionRunner._ingest_one` already has retry+backoff, but
   `default_backoff_seconds` is a fixed `min(2**attempt, 30)` (2s, 4s,
   8s for the default 3 retries — 14 seconds total) with no
   relationship to the rate limit's own actual reset window, which for
   a real API quota is typically much longer. The transport already
   captured the response's `retry-after` header into
   `response_headers` but then discarded it entirely — the exception
   carried nothing for the retry loop to act on.
2. **Stooq's fallback also failed, for a separate, unrelated reason.**
   `stooq.py`'s own module docstring already disclosed this fallback
   path had "never been exercised against a live Stooq response in
   this environment" (ADR-0025's network policy blocks `stooq.com`
   here too) — this was effectively that first real exercise. All 7
   requests 404'd, including several highly liquid large-cap tickers
   (Morgan Stanley, Wells Fargo, American Express, Eli Lilly, Thermo
   Fisher, Abbott, Adobe) that are extremely unlikely to genuinely be
   absent from Stooq's coverage all at once. `StooqHttpTransport.get()`
   sent **no `User-Agent` header at all** — Python's default `urllib`
   User-Agent string is a well-documented bot fingerprint many sites
   filter, and `SecEdgarHttpTransport` (a different provider in this
   same codebase) already has to send a real one for exactly this class
   of reason.

## Decision

### 1. `TransientProviderError` carries an optional real `retry_after_seconds`

Added a keyword-only `retry_after_seconds: Optional[float] = None` to
`TransientProviderError.__init__` — `None` (never fabricated) unless a
failing response actually told us. New `parse_retry_after_seconds(value)`
helper in `data_infra/provider.py` parses HTTP's two real `Retry-After`
forms (RFC 9110 §10.2.3): a plain seconds count, or an HTTP-date to wait
until — returns `None` for anything else, including a negative value
(never silently treated as zero).

`TiingoHttpTransport`/`SecEdgarHttpTransport`/`StooqHttpTransport` all
now parse `Retry-After` on their transient-error paths (429 explicitly
for Tiingo/SEC EDGAR; Stooq's generic non-401/403/404 HTTP-error branch,
since Stooq's own 429 behavior has never been observed) and attach it
to the raised exception.

`FallbackDataProvider`'s dual-failure branch (both primary and
secondary failed) previously always constructed a fresh
`TransientProviderError(message)` with no `retry_after_seconds` even
when one side's real exception carried one — fixed to prefer the
primary's value, falling back to the secondary's, so re-wrapping two
exceptions into one never silently drops a real server-stated wait
time.

### 2. `IngestionRunner._ingest_one` prefers the real value over its guess

When retrying a `TransientProviderError`, the runner now sleeps
`exc.retry_after_seconds` (capped at `_MAX_RETRY_AFTER_SECONDS = 60.0`,
so one unusually large server-stated value cannot stall a run that
still has many other symbols left to process in the same CI job)
instead of `self._backoff_fn(attempt)`, whenever the exception actually
carries one. `default_backoff_seconds` is otherwise unchanged — there
is no confirmed evidence of Tiingo's actual rate-limit window to tune
that fixed formula against; respecting a real, server-stated value when
given is the only change made without guessing.

### 3. `StooqHttpTransport` sends a real User-Agent

A standard, current desktop-browser User-Agent string is now sent on
every Stooq request. Stooq has no official API and no documented
bot-identification convention (unlike SEC EDGAR, which requires one by
policy) — mimicking an ordinary browser is the standard workaround for
this exact class of unofficial, no-auth scraping endpoint.

**Explicitly disclosed as unverified**: this fix is built on a
plausible, well-evidenced hypothesis (a missing User-Agent causing a
blanket block that manifests as 404), not a confirmed root cause — this
session's own network policy blocks `stooq.com`, so it cannot be tested
against a live response here. It needs re-verification against a real
scheduled/`workflow_dispatch` run, the same way this bug was originally
found, not assumed fixed from this reasoning alone.

## Consequences

### Positive

- A real Tiingo rate-limit response is now respected on its own terms
  instead of being retried against a backoff schedule with no
  relationship to it.
- No exception path (transport → fallback → runner) silently drops a
  real server-stated wait time it received.
- The Stooq fallback has a concrete, plausible fix for its first real
  production failure, rather than being left broken with no action
  taken.

### Negative / Trade-offs

- The Stooq fix's actual effect is unverified as of this ADR — real
  confirmation is deferred to the next real network run, and it may
  turn out the 404s had a different cause (a genuine Stooq policy
  change, a symbol-format issue) that this fix does not address.
- `_MAX_RETRY_AFTER_SECONDS` (60s) is a judgment call bounding CI job
  time, not evidence-derived — if Tiingo's real rate-limit window is
  longer than a few retries' worth of 60s waits can cover, this will
  still not fully recover within one run; it only makes the existing
  retry budget spend its time correctly rather than uselessly.
- No proactive client-side request pacing was added (e.g. a minimum
  delay between every Tiingo call regardless of failure) — this ADR
  only makes the reactive retry path respect real signals; avoiding the
  rate limit in the first place is a separate, larger design not
  undertaken here.

## Tests

- `tests/data/test_provider_ingestion.py`: new `TestParseRetryAfterSeconds`
  (6 tests: plain seconds, plain float, HTTP-date, missing header,
  unparseable value, negative value never fabricated as zero) and
  `TestRetryAfterPreferredOverGuessedBackoff` (2 tests: a real
  retry-after is slept instead of the guessed backoff; an
  unreasonably large one is capped).
- `tests/data_infra/test_tiingo_transport.py`: 2 new tests (a real
  `Retry-After` on a 429 is parsed onto the exception; its absence
  leaves `retry_after_seconds` `None`).
- `tests/data_infra/test_stooq_transport.py`: new `TestUserAgent` (a
  real User-Agent is always sent, never the default urllib signature)
  and `TestRetryAfterHeader` (2 tests, mirroring Tiingo's).
- `tests/data_infra/test_fallback_provider.py`: 2 new tests in
  `TestBothFail` (a real retry-after from either side survives the
  dual-failure repackaging; the secondary's is used when the primary
  has none).
- Full suite re-run: 3219 passed (up from 3204).

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed. The Stooq
User-Agent fix specifically is unverified against a live response (see
Decision §3) — the next real scheduled/`workflow_dispatch` run of
`paper_trading_cycle.yml` is this fix's own real-world verification.
