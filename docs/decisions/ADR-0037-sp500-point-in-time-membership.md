# ADR-0037: Point-in-Time S&P 500 Membership from a Verified Third-Party Source

**Status:** Accepted

## Context

ADR-0034 Decision 4 (`EXTERNAL_DATASET_REQUIRED`) named this project's
biggest standing data gap: no source of point-in-time S&P 500
membership or delisted-securities history exists anywhere in this
repository. Every universe built so far (`PILOT_UNIVERSE_V1`,
`RESEARCH_UNIVERSE_STAGE1/2`) reflects today's surviving companies
projected backward across the whole backtest range --
`audit_survivorship()` correctly and honestly classifies this
`CURRENT-UNIVERSE-ONLY`, never claiming survivorship-bias-free.

This session, following up on the ad-hoc GitHub research the user
asked for (comparing this project against gs-quant, zipline, pyfolio,
alphalens, QuantConnect/Lean, man-group/Arctic -- none of which turned
up an architectural gap, see chat log), the user asked to search
specifically for candidates that could close this exact data gap.
Three were found and evaluated with real due diligence (not just
README claims -- actual files fetched and inspected):

1. `BlackFalconData-org/delisted-stocks-list` -- **rejected**. The
   repository contains a single 4.6KB `README.md` and zero actual
   data; it is a landing page for a paid Apify scraping product, not a
   dataset. Confirmed by cloning the repo directly.
2. `shardul0701/SP500-Survivorship-bias-data-2004-2026` -- **deferred,
   not used**. Spot-checks against known facts passed, but the
   repository's own transformation of the data carries no explicit
   license (only an attribution copy of an upstream MIT license for a
   *different* dataset it derives from), and its automated update
   pipeline has 9 unmerged PRs sitting open since June 2026 -- `main`
   is stale relative to its own claimed freshness. Revisit only after
   the author clarifies licensing.
3. `hanshof/sp500_constituents` -- **used, this ADR**. Real MIT
   `LICENSE` file (copyright "running_error", 2023). A genuine,
   auditable ~60-line scraper (`sp500.py`) that pulls Wikipedia's "List
   of S&P 500 companies" table and appends a `(date, tickers)` row to
   `sp_500_historical_components.csv`. Git history shows 50+
   consecutive real automated commits (not fabricated).

## Decision 1 -- Build `data_infra.providers.sp500_pit_membership`, do not fabricate precision the source data doesn't have

Cloned the real repository this session (`git clone` -- GitHub is
reachable from this sandboxed session even though every market-data
provider host is not) and inspected the actual CSV, not just the
README. Counted real rows per year to establish the dataset's true
coverage:

```
1996-2018: ~90-133 rows/year (roughly one snapshot every 2-3 trading days)
2019: 27   2020: 13   2021: 14   2022: 20   (severe, ~4-year dormancy)
2023: 234  2024: 363  2025: 222 (through Aug -- automation resumed)
```

The 2019-2022 gap falls squarely inside this project's own 2010-2026
backtest window and is a real limitation, not a hypothetical one --
membership that changed and reverted inside a gap this large would
never be captured.

Rather than silently smoothing over this, `sp500_pit_membership.py`
reports its own uncertainty explicitly:

- `membership_as_of(snapshots, as_of)` forward-fills to the nearest
  snapshot at-or-before `as_of` and returns `staleness_days` (0 if
  exact, large inside a coverage gap) alongside the ticker set --
  never a bare, unqualified answer.
- `reconstruct_intervals(snapshots)` derives each ticker's apparent
  first/last-seen dates plus `left_censored`/`right_censored` flags and
  `added_uncertainty_days`/`removed_uncertainty_days` -- the size of
  the real gap bracketing an apparent addition/removal, not a
  fabricated exact date. A ticker present in the very first or very
  last snapshot is explicitly flagged censored (true entry/exit date
  unknown, possibly outside the dataset) rather than assigned a
  misleading zero-uncertainty date.

**Validated against the real file, not just synthetic fixtures**
(re-running the same spot-checks the research step used, with this
session's own code): Bear Stearns (`BSC`) last seen 2008-05-29,
4-day uncertainty window bracketing its known 2008-06-02 removal;
Lehman (`LEHMQ`) last seen 2008-09-16, 1-day window bracketing its
known 2008-09-17 removal; Tesla (`TSLA`) first seen exactly 2020-12-21,
its documented addition date. 14 new unit tests
(`tests/data_infra/test_sp500_pit_membership.py`) use small synthetic
fixtures, including one specifically constructed to regression-guard
the "large gap produces large uncertainty, never a smoothed exact
date" promise (Decision 1's core honesty property).

## Decision 2 -- Provenance must name the real source, not an implied official one

Any `SecurityMaster`/`SymbolMetadata`/`UniverseMembership` record ever
built from this module's output must set its source string to
something like `"hanshof_sp500_constituents_wikipedia_scrape"` --
never a string that could be misread as S&P Global, CRSP, or any paid
vendor. The ultimate source is Wikipedia's crowd-maintained table, one
step removed from an official index provider. This module's docstring
states this explicitly and is the enforcement point until a future
phase wires it into `universe.py`'s `SymbolMetadata` population (see
Consequences).

## Decision 3 -- What this does NOT solve

This dataset is S&P 500 index membership only. It is not a full
delisted-securities list across all US exchanges (that candidate,
BlackFalconData-org's, was rejected for containing no data at all) --
a stock that left the S&P 500 by index-committee removal (e.g. for
falling market cap) rather than delisting/bankruptcy still exists and
trades; this module cannot tell those two cases apart, since it only
observes index membership, not corporate status. Full delisting/
bankruptcy/merger status for a security still requires either a real
provider's corporate-action feed (already implemented,
`TiingoDataProvider.fetch_corporate_actions`) for whatever a real
ingestion actually returns, or a different, still-not-found dataset.

`audit_survivorship()` is NOT modified by this ADR. Wiring this
module's output into an actual `UniverseDefinition` with populated
`listed_from`/`listed_to` (which would change `audit_survivorship`'s
classification from `CURRENT-UNIVERSE-ONLY` toward
`PARTIALLY_MITIGATED`) is deliberately left as a separate, future,
explicitly-decided step -- this ADR only builds and verifies the
parsing/query primitive, consistent with this project's incremental,
one-verified-piece-at-a-time discipline. No `UniverseDefinition` in
`universe.py` is changed by this ADR.

## Decision 4 -- No dependency added, no Live/broker/risk code touched

Pure stdlib (`csv`, `dataclasses`, `datetime`) -- no new dependency.
Purely additive: one new source file, one new test file. Does not
touch `src/broker/`, `src/risk/`, `src/learning/`, `src/evolution/`,
strategy signal-generation code, or the currently-running real
walk-forward validation in any way -- confirmed via `git diff --stat`
scope check. All 1,759 pre-existing tests plus 14 new tests pass.

## Consequences

- A future phase can use `reconstruct_intervals()`'s output to
  populate a new `UniverseDefinition`'s `SymbolMetadata.listed_from`/
  `listed_to` fields honestly, including surfacing the
  `left_censored`/`right_censored`/`*_uncertainty_days` fields
  somewhere a human reviewer can see them before trusting a
  survivorship-bias claim built on this data.
- The source CSV itself (6.7MB) is intentionally NOT committed to this
  repository -- consistent with the existing `LocalFileDataProvider`
  external-acquisition pattern (Phase 31), a user/future script
  supplies the file path at run time; only the parser and its
  synthetic-fixture tests are committed.
- `shardul0701`'s dataset remains a candidate worth revisiting once its
  licensing is clarified and its stale `main`/unmerged-PR situation
  resolves -- not rejected outright, just not used yet.
