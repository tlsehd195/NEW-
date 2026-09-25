# ADR-0203: Corporate-action fallback to Alpha Vantage, reordering, and severity fix

**Status:** Accepted
**Date:** 2026-09-25
**Deciders:** Claude Code (daily Paper Trading Actions health-check routine), account owner
**Related documents:** `docs/decisions/ADR-0160-tiingo-proactive-budget-and-stooq-js-challenge-dead-end.md`
(the shared Tiingo budget this ADR's root cause traces to), `docs/decisions/ADR-0164-second-and-third-fallback-data-providers.md`
(the price-bar-only Tiingo → Twelve Data → Alpha Vantage chain this ADR
extends to corporate actions), `scripts/recon_corporate_action_providers.py`
(the real reconnaissance this decision is based on)

## Context

Run #44 (2026-09-25, `36077212315`, 00:22:09–00:34:19 UTC =
09:22:09–09:34:19 KST) failed the Paper Trading Daily Cycle. Diagnosis
found two separate things true at once:

1. **Price-bar ingestion was 100% successful** — all 86 requested
   symbols, zero missing, via the existing Tiingo → Twelve Data → Alpha
   Vantage fallback chain (ADR-0164).
2. **Corporate-action collection failed for every one of the 88
   requested symbols at once.** `scripts/ingest_real_market_data.py`
   fetched corporate actions from Tiingo ONLY, with no fallback, and
   ran that loop AFTER price-bar ingestion — by the time it ran,
   price-bar fetching had already exhausted Tiingo's shared hourly
   request budget (ADR-0160), so every corporate-action call failed
   instantly with "budget exhausted." The script's own exit-code gate
   treated "corporate actions failed for every requested symbol" as
   fatal for the WHOLE run, skipping "Run paper trading cycle" that
   day even though price data was completely fine.

Asked directly whether Twelve Data/Alpha Vantage (already integrated
for price bars) could serve as a real fallback for corporate actions
too — both providers' modules had previously declared
`supports_corporate_actions=False`, documented as "deliberate" but
without stating whether their real APIs actually lack this data.
Verified for real (not guessed) via a new one-shot reconnaissance
script/workflow (`scripts/recon_corporate_action_providers.py`,
`.github/workflows/recon_corporate_action_providers.yml`), since both
provider domains are blocked by this environment's own egress proxy
and only a GitHub Actions runner can reach them:

- **Twelve Data `/dividends`**: real HTTP 200, real data. Free tier works.
- **Twelve Data `/splits`**: real HTTP 403 — "available exclusively
  with grow or pro or ultra or venture or enterprise plans." Paid only.
- **Alpha Vantage `DIVIDENDS`**: real HTTP 200, real data. Free tier works.
- **Alpha Vantage `SPLITS`**: real HTTP 200, real data — including GE's
  own real 2021-08-02 reverse split (`split_factor: "0.1250"`), matching
  this project's own already-known REVERSE_SPLIT edge case
  (`docs/operations/MARKET-DATA-PROVIDER.md`). Free tier works.

(The first real run fired both Alpha Vantage calls 4ms apart and its
SPLITS result came back as an inconclusive throttle notice instead of
real data or a real error — a >1s pacing gap on the re-run gave a
clean, trustworthy answer for both calls; see
`AlphaVantageRateLimiter`'s own module docstring.)

Alpha Vantage genuinely provides both dividends and splits on its free
tier, but its real cap (25 requests/day, and this integration needs TWO
calls per symbol) cannot cover a full ~87-symbol universe on its own.

## Decision

Three changes, made together (account owner's own "C" combined
proposal):

1. **Corporate-action collection now falls back to Alpha Vantage per
   symbol.** `AlphaVantageDataProvider` gains real
   `fetch_corporate_actions`/`normalize_corporate_actions` methods
   (mirroring `TiingoDataProvider`'s existing shape and point-in-time
   discipline exactly — `available_time`/`ingestion_time` are always
   the caller-supplied ingestion moment, never backdated to the real
   event date) and now declares `supports_corporate_actions=True`. A
   new `AlphaVantageRateLimiter` (1 request/second, mirroring
   `TwelveDataRateLimiter`'s per-minute pacing) is wired into
   `AlphaVantageHttpTransport` so the two real calls per symbol
   (DIVIDENDS then SPLITS) never repeat the throttled-result problem
   the first recon run hit. `scripts/ingest_real_market_data.py` tries
   Tiingo first, Alpha Vantage second, per symbol — never the reverse,
   since Alpha Vantage's tiny daily cap could not serve the whole
   universe on its own.

2. **Corporate-action collection now runs BEFORE price-bar ingestion**,
   not after. Tiingo's shared hourly budget is a scarce resource with
   only one real substitute (Alpha Vantage, capacity-limited);
   price-bar fetching already has a real 3-tier fallback chain of its
   own and tolerates absorbing the remainder far better. Giving the
   resource with no good substitute first claim on the shared budget
   reduces (though does not guarantee zero) days where corporate
   actions run out of budget entirely.

3. **Corporate-action failure (partial OR total) no longer gates this
   script's own exit code.** A missed split/dividend refresh is
   recoverable on the next successful run — nothing is deleted, only
   delayed (Raw Immutability, Phase 1 spec section 17) — while skipping
   an entire day of Paper Trading on otherwise-good price data is not
   proportionate to that risk. Both partial and total corporate-action
   failures are still printed directly to the job's own CI log
   (previously only a full wipeout was) and recorded per-symbol in the
   manifest (`corporate_actions_per_symbol`/`corporate_action_failed_symbols`),
   just never fatal.

## Consequences

### Positive

- Closes the exact gap run #44 exposed: a Tiingo-budget-exhaustion day
  no longer skips an entire day of Paper Trading over corporate-action
  freshness alone.
- Two real, independently confirmed fallback tiers (reorder + Alpha
  Vantage) meaningfully reduce how often corporate actions fail for
  every symbol at once, without any guessed capability claims — every
  new provider capability here was verified against a real API
  response first.

### Negative / Trade-offs

- Alpha Vantage's real 25-requests/day cap (two calls per symbol) means
  it can only ever cover a fraction of the universe as a fallback, not
  a full second source — some days may still see partial corporate-action
  gaps. Accepted: this is now a partial, recoverable gap (next run's
  own Tiingo-first fetch always retries any earlier miss for the same
  date range), not a fatal one.
- No daily-budget proactive refusal was added for Alpha Vantage (unlike
  Tiingo's `TiingoRequestBudget`) — a real quota rejection there still
  comes back as an ordinary `TransientProviderError` via the existing
  "Note"/"Information" body-shape handling. Deferred as unnecessary
  complexity for a rarely-reached fallback tier; revisit if it proves
  to matter in practice.

## Tests

- `tests/data_infra/test_alphavantage_ratelimit.py` (new, 6 tests):
  `AlphaVantageRateLimiter` pacing, mirroring `TwelveDataRateLimiter`'s
  own test shape.
- `tests/data_infra/test_alphavantage_transport.py` (new `TestRateLimiting`
  class, 2 tests): a shared rate limiter is consulted before every real
  call, and a default one is still enforced when none is passed.
- `tests/data_infra/test_alphavantage_provider.py` (new
  `TestFetchCorporateActions`/`TestNormalizeCorporateActions` classes,
  7 tests; updated `TestMetadata`): real recon-confirmed response
  shapes (including GE's real reverse split), date-range filtering,
  rate-limit/shape error handling, SPLIT vs REVERSE_SPLIT ratio
  convention, point-in-time discipline, real repository read-back.
- `tests/data_infra/test_ingest_real_market_data_wiring.py` (updated):
  removed the three tests asserting the old fatal-on-total-failure
  gate; added tests confirming the exit-code condition no longer
  references corporate-action failure at all, that both partial and
  total failures are still printed, that the Alpha Vantage fallback is
  wired, and that corporate-action collection runs before price-bar
  ingestion in source order (AST/source-text checks — this script is
  never imported/executed by the suite, it makes real network calls).

Full suite re-run: see `docs/PROJECT_STATUS.md`'s session log.

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed.
