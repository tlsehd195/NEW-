# ADR-0213: Tiingo-only, hourly-sharded ingestion for the long-history research price catalog

**Status:** Accepted (code/workflow only -- the ingestion itself is a separate dispatch)
**Date:** 2026-09-26
**Deciders:** account owner (widen period and universe, ADR-0212), Claude Code session

**Related documents:** `ADR-0212` (Stage 5, 2000-onward price window),
`ADR-0160` (Tiingo 50/hour budget), `ADR-0164` (fallback chain),
`scripts/ingest_real_market_data.py`,
`.github/workflows/ingest_research_price_catalog.yml`,
`.github/workflows/run_full_validation.yml`.

## Context

ADR-0212 needs a price catalog for `RESEARCH_UNIVERSE_STAGE5` (203
symbols + SPY) from 2000-01-01. Running the existing ingestion once for
all 204 symbols would go wrong quietly:

1. `TiingoRequestBudget` stops Tiingo after 48 requests in a rolling
   hour and the run falls through to the next provider rather than
   waiting.
2. Corporate actions are fetched first (1 request/symbol), so Tiingo is
   spent after ~48 symbols; the rest fall to Alpha Vantage (25/day) and
   mostly fail.
3. Price bars then fall to Twelve Data, whose free tier returns at most
   5,000 bars per series (public docs, not re-verified here), about
   20 years. A 2000-onward request would come back starting around
   2006, with nothing in the manifest saying it was cut short.

## Decision

- `ingest_real_market_data.py` gains `--tiingo-only` (Tiingo is the
  sole provider for bars and corporate actions; a Tiingo error fails
  that symbol visibly) and `--shard-index`/`--shard-count` (ingest
  `sorted(universe)[i::n]`, same assignment as
  `select_universe_shard.py`; SPY only with shard 0; the whole universe
  is still registered in `security_master`/`universe_membership`,
  whose inserts are idempotent). Default behaviour without these flags
  is unchanged, so `paper_trading_cycle.yml` is unaffected.
- New `ingest_research_price_catalog.yml` (dispatch-only): 10 shards
  of at most 21 symbols + SPY (44 requests, under the 48 effective
  cap), one shard per ~61 minutes into one catalog, split across two
  chained jobs to stay under GitHub's 6-hour job limit. A coverage
  report (`report_price_catalog_coverage.py`) prints bar count and
  first/last date per symbol, fails on any zero-bar symbol, and only
  then is `price_catalog.zip` published to a Release. Symbols whose
  first bar is well after the start date are listed for a human to
  read, not failed, because a later IPO and a truncated history look
  the same without a verified listing date.
- `run_full_validation.yml` gains a `price_only` input: it downloads
  only `price_catalog.zip` and skips the fundamentals, insider and
  institutional catalogs, so the price-derived candidates can run on
  the 2000-onward window (ADR-0212 Decision 1).

## Operating constraint

Tiingo quota is shared with `paper_trading_cycle.yml` (22:00 UTC,
Mon-Fri). Dispatch the backfill on a weekend or so it finishes before
22:00 UTC. The daily total (~408 + ~176 requests) is under the
1,000/day cap either way.

## Consequences

- A full Stage 5 backfill takes about 10 hours of wall-clock time but
  no manual steps.
- If a shard fails, its symbols show zero bars in the coverage report
  and nothing is published; re-dispatching is safe because every
  insert is idempotent (a fresh run starts from an empty catalog).
- The survivorship-bias limitation from ADR-0212 applies unchanged to
  any result built on this catalog.

## Addendum (same day): what the first real run found

Run `36241935152` (2026-09-26, cancelled after its first job) showed
two real problems. Neither lost data: each shard had already persisted
its bars when it failed.

1. **Every shard crashed on the trading calendar.** exchange_calendars'
   default XNYS calendar covers only the 20 years before today (first
   session 2006-09-26), so the ingest script's
   `expected_trading_days_in_range` raised `DateOutOfBounds` for
   `--start 2000-01-01`. `build_xnys_calendar()` now starts at
   1990-01-01. The same rolling default would also have broken the
   existing 2010-01-01 validation window once today passed 2030.
2. **Shard 0 ran out of Tiingo budget for 16 of 22 symbols.** The
   budget is client-side and counts every attempt, and
   `IngestionRunner` retries a `TransientProviderError` up to three
   times. The likely cause (inferred, not confirmed from the logs) is
   the 10-second timeout on a 26-year response, whose retries spent
   the hour. Shards 1-4 were not affected.

Changes: `--tiingo-timeout-seconds` (the workflow uses 60),
`--skip-symbols-with-bars` (already-covered symbols cost nothing, so a
shard can be rerun or a run resumed), `--max-symbols`, a final retry
sweep over symbols still without bars, three chained jobs (0-3, 4-6,
7-9 + sweep), and a `resume_from_run_id` input. Every job uploads its
catalog even on failure. A shard that fetched nothing does not wait an
hour before the next one.
