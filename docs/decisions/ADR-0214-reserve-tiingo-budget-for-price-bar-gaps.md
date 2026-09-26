# ADR-0214: Twelve Data first for price bars, Tiingo reserved for gaps

**Status:** Accepted
**Date:** 2026-09-26
**Deciders:** account owner, Claude Code session

**Related documents:** `docs/decisions/ADR-0160` (Tiingo hourly request
budget), `docs/decisions/ADR-0164` (3-tier price fallback chain),
`docs/decisions/ADR-0211` (the schema fix this run was verifying), PR #132
(corporate actions collected before price bars).

## Context

`paper_trading_cycle.yml` run #47 (36241691921, 2026-09-26) got past the
ADR-0211 schema fix but still exited 1 as `PARTIAL_SUCCESS`:

```
all providers failed for AVB: tiingo=PermanentProviderError(Tiingo request
budget exhausted ...); twelvedata=PermanentProviderError(not found calling
/time_series); alphavantage=TransientProviderError(... 25 requests per day ...)
```

Since PR #132 the corporate-action loop runs first and spends Tiingo's
whole 48-call hourly budget, so every price bar already came from Twelve
Data or Alpha Vantage. Twelve Data does not serve AVB, and Alpha Vantage's
25/day was already spent on corporate-action fallbacks, so AVB had no
working source and the run failed. This happens on most days, not once.
(The 87 `ingestion_precedes_availability` ERRORs in the same run do not
gate the exit code; only CRITICAL does.)

## Decision

- Price-bar chain order becomes `FallbackDataProvider(twelvedata, tiingo,
  alphavantage)`. Twelve Data (~800/day) serves the bulk; Tiingo is
  only called for symbols Twelve Data fails on.
- The corporate-action loop stops calling Tiingo once the shared budget
  has `TIINGO_PRICE_RESERVE` (8) calls left and falls through to Alpha
  Vantage, as it already did for an exhausted budget.
- `--tiingo-only` (ADR-0213) is unchanged.

## Consequences

- AVB-like symbols keep up to 8 Tiingo calls per run for their price bars.
- Up to 8 fewer symbols get corporate actions from Tiingo per run. Their
  fallback is Alpha Vantage, and corporate-action failures already do
  not gate the exit code (PR #132).
- Price bars that were nominally Tiingo-first now come from Twelve Data
  first, which matches what already happened in practice (run #47).
