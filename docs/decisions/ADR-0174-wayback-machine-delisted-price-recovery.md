# ADR-0174: Recover sparse delisted-stock prices from Wayback Machine snapshots of stockanalysis.com

**Status:** Accepted
**Date:** 2026-09-19
**Deciders:** Claude Code (session continued), account owner (asked
this session to check Wayback Machine reachability, then walked
through a real, live recon of what it actually contains together, then
explicitly asked to build the full pipeline once the technique was
confirmed to work)

## Context

`docs/PROJECT_STATUS.md`'s 2026-09-17 checklist listed "Wayback
Machine(archive.org) 경로 실측" as an item this session's own egress
could not verify (`archive.org` itself is not blocked, but was rate-
limited, HTTP 429, on first real attempts). A real retry later in the
session succeeded.

The real, concrete motivation is the survivorship-bias gap ADR-0129
already honestly measured and quantified: 623 real S&P 500 tickers
removed since 2000, only 59 with any real price data recovered
(ADR-0126/ADR-0128), 564 remaining a real, named gap.
`stockanalysis.com` itself (the live site) is directly blocked from
every environment this project has tried it from (403, this session's
own sandbox and a GitHub Actions runner alike) -- but its PAST content
is preserved by the Wayback Machine, which is not blocked.

**Real recon, not assumed** (`https://web.archive.org/wayback/available`
then the CDX API `https://web.archive.org/cdx/search/cdx`, both hit
directly this session): AVB's real page history showed 28 real
snapshots from 2020-08-06 through 2026-06-15. Fetching individual
snapshots and searching for real dollar-prefixed and bare-decimal price
values (never assumed from a stale format memory) found REAL, cross-
checkable prices (e.g. $150.97 on 2020-08-06, 233.52 on 2024-09-13 --
both consistent with AVB's actual known trading range on those real
dates) across **three distinct real HTML layouts** the site was
redesigned through:

1. (~2020-08 to ~2021-04) `id="qLast">$PRICE</td>` inside a "Stock
   Quote" table.
2. (~2021-10 to ~2023-03) `class="p svelte-XXXXX">PRICE</div>` -- a
   Svelte-compiled build, whose scoped-class hash suffix is build-
   specific and was matched generically (`svelte-\w+`), not hardcoded.
3. (~2023-04 onward) `class="text-4xl font-bold ... inline-block">
   PRICE</div>` -- a Tailwind-based redesign that itself gained extra
   utility classes in a later sub-revision (confirmed against a real
   2025-03 snapshot), matched with a wildcard between the two stable
   class fragments rather than an exact full class-string match.

**Real, structural limits this ADR does not attempt to work around**:
`stockanalysis.com` itself did not exist before ~2020 (AVB's earliest
real snapshot is 2020-08-06) -- Wayback cannot recover what was never
published. Re-running the exact same `removed_since()` query this
project's own `report_survivorship_price_coverage.py` already uses,
against the real, live `fja05680/sp500` CSV, with a `2020-01-01` cutoff
instead of `2000-01-01`, found **142 of the 623** real candidates
qualify (`scripts/select_delisted_candidates_since.py`). The other 481
were removed before stockanalysis.com existed and cannot benefit from
this technique regardless of parser quality. Real snapshot cadence is
also sparse (~28 snapshots across 6 years for AVB, roughly quarterly)
-- a coarse anchor series, never a substitute for real daily OHLCV.

## Decision

Added `scripts/ingest_stockanalysis_wayback_delisted_prices.py`:
queries the real Wayback CDX index per ticker, fetches each real
snapshot, tries the three real confirmed patterns above in order, and
persists one `PriceBar` per successfully-parsed snapshot via the
existing `DuckDBDataRepository.append_bars` (idempotent by its own
existing natural key). Each bar's `timestamp` is the snapshot's own
real CDX capture time (used as a reasonable real proxy for observation
time, since these are "current price" pages -- no per-era "as of" text
parsing is attempted, since each era phrases it differently and the
CDX timestamp is already a real, given value).

**Explicit, honest simplification, not fabrication**: each bar sets
`open == high == low == close` to the single real scraped price and
`volume = 0.0`, because that is genuinely all `stockanalysis.com`'s
own page ever shows per snapshot -- never a real OHLC breakdown.
`provenance.source` is always `"stockanalysis_com_via_wayback_machine"`
specifically so a future consumer can recognize and exclude this
source from any check that assumes real volume or real intraday range,
mirroring ADR-0126's own "confirmed scraper artifact, filtered by
`volume == 0`" precedent for a different real gap.

`scripts/select_delisted_candidates_since.py` reuses this project's
own existing `removed_since()` (no new selection logic) with a
`--since` default of `2020-01-01` -- the real, confirmed boundary of
what this technique can possibly help with.

New `ingest_stockanalysis_wayback_delisted_prices.yml`
(`workflow_dispatch`-only, an optional `symbols` input defaulting to
auto-selecting the full real 142-candidate set) fetches the live
`fja05680/sp500` CSV via `raw.githubusercontent.com` (confirmed
reachable) at run time -- never committing a generated candidate list,
matching this project's existing convention (ADR-0120).

Rate-limited to 1 request/second (`_REQUEST_DELAY_SECONDS`) -- this
same session was real-429'd by `archive.org` at a higher, unthrottled
rate earlier, on a completely different, single-request check.

## Consequences

### Positive
- A real, previously call-untested backlog item is resolved with a
  real, working (if partial) technique, verified end-to-end against
  real, cross-checkable price data before any code was written.
- Real, executable test coverage using the ACTUAL HTML fragments
  recovered during this session's own recon as fixtures (not
  synthesized guesses at what the three real layouts look like).
- `select_delisted_candidates_since.py` is a pure, 6-line reuse of
  already-existing, already-tested selection logic -- no new business
  logic, just a different real cutoff for a different real constraint.

### Negative / Trade-offs
- Covers at most 142 of the 623 real candidates (23%), and even for
  those, only a sparse (~quarterly), single-price-per-snapshot series
  -- this closes part of a real gap, not all of it, and ADR-0129's own
  564-ticker honest accounting is only partially reduced by this, not
  eliminated.
- Three real site layouts were found for ONE ticker (AVB) across
  2020-2026; other tickers delisted in the same window presumably hit
  the same three real eras (site layout is a property of the site, not
  the ticker), but this was not independently re-verified per-ticker
  before this ADR -- a real run against the full 142-candidate set is
  this ADR's own necessary follow-up, and could surface a fourth real
  layout this recon did not encounter.
- `open == high == low == close`/`volume == 0.0` is a real, disclosed
  simplification (see Decision) -- any future consumer must be aware
  real OHLC-range-dependent or volume-dependent computations (e.g.
  Amihud illiquidity, Corwin-Schultz spread) will produce degenerate,
  meaningless results if run against this specific `provenance.source`
  without explicitly excluding it first.
- 1 request/second across 142 tickers x ~28 snapshots each is a real,
  multi-hour run against a free, shared archival service -- considerate
  but not free of real load; not something to re-run casually.

## Tests

`tests/scripts/test_select_delisted_candidates_since.py` (6 tests):
pure selection logic against a small real-schema CSV fixture.
`tests/scripts/test_ingest_stockanalysis_wayback_delisted_prices.py`
(12 tests): all three real HTML-fragment fixtures parse to their real,
confirmed prices; CDX-timestamp parsing; CDX response filtering (a
real 308 redirect row is excluded); full `main()` end-to-end runs
against a real temporary DuckDB/Parquet catalog (real bars persisted
with the documented `open==high==low==close`/`volume==0` shape, a
per-snapshot parse failure recorded not silently dropped, a fetch
failure marks that symbol failed, idempotent re-run). `tests/deploy/
test_ingest_stockanalysis_wayback_delisted_prices_workflow.py`
(6 tests): workflow structure. Full suite re-run: see
`docs/PROJECT_STATUS.md`'s session log for the exact count.

## Status of Implementation at Time of This ADR

Code, tests, and workflow complete and merged. The real full
142-candidate run itself (a genuine multi-hour, rate-limited run
against `archive.org`) is the next, separate step this ADR does not
itself claim to have executed -- see this session's own live reporting
to the account owner for that real outcome once triggered.
