# ADR-0194: `guru_consensus_score` -- a curated, point-in-time-aware tracked-filer registry

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Claude Code (session continued), account owner

## Context

Following on from `institutional_ownership_change_score` (ADR-0104,
Chen/Jegadeesh/Wermers 2000 -- aggregate LONG institutional ownership
change, summed across every Form 13F filer with no identity), the
account owner asked a direct follow-up question: since 13F data lets a
security be tracked by SPECIFIC, named, well-known investors ("거물
투자자"), does this project have a strategy that buys what several of
them independently hold ("거물투자자들이 공통적으로 구매하는 기업 찾아서
구매하는 전략은 없지?")? It did not.

The account owner also, unprompted, raised the real risk in choosing a
FIXED set of investors: any one of them can retire, close their fund,
or die, and asked for a design that would not require rewriting the
strategy when that happens ("그 거물투자자가 사망하거나 이러면 다 바꿔야
할 수도 있으니까 지속적으로 업데이트 가능한 형식으로 만들어줘").

## Decision

### A new, separate per-filer data model, not an extension of the existing aggregate one

`institutional_holding_records`/`InstitutionalHoldingRecord` already
exist and are explicitly, deliberately AGGREGATE (see that model's own
module docstring: Form 13F, unlike Form 4, is filed BY the institution
ABOUT its entire portfolio, so per-security aggregation across all
filers was already baked into the schema before this ADR). Rather than
retrofitting filer identity onto that table, this ADR adds a distinct,
parallel set of components:

- `data_infra.institutional_holding_models.InstitutionalFilerHoldingRecord`
  -- one filer's own reported position in one security for one quarter.
- `data_infra.providers.institutional_filer_holding_file_import` --
  combined-CSV-only (`security_id,filer_cik,quarter_end,shares_held`),
  unlike the aggregate module's two-mode (`--data-dir`/`--combined-csv`)
  option: a small, curated filer set naturally produces one
  quarter-covering export, not one file per security.
- `institutional_filer_holding_records` (new DuckDB table) +
  `storage.institutional_filer_holding_repository.
  DuckDBInstitutionalFilerHoldingRepository`, with a
  `get_latest_holdings_for_security(security_id, filer_ciks, as_of_time)`
  method (DuckDB `QUALIFY ROW_NUMBER() OVER (PARTITION BY filer_cik ...)`)
  that is `guru_consensus_score`'s own primary read path -- one query
  per security across every currently-tracked filer, not N queries.
- `scripts/ingest_institutional_holdings.py` gained a third,
  mutually-exclusive `--filer-combined-csv` mode alongside its existing
  two (kept in the same CLI rather than a new script, since the only
  difference is which loader/repository is invoked).

Reusing `InstitutionalHoldingRecord` and giving it an optional
`filer_cik` would have silently let the ALL-filers aggregate and a
SPECIFIC filer's own position live in the same rows with no way to
distinguish them at the type level -- the same "don't collapse two
genuinely different data shapes into one type" reasoning
`InstitutionalHoldingRecord`'s own docstring already uses to explain
why it is NOT modeled like `InsiderTransaction` (per-person) despite
both ultimately deriving from SEC filings.

### `data_infra.tracked_institutional_filers`: a point-in-time-aware registry, not a hardcoded list

`TrackedFiler(cik, name, tracked_from, tracked_until, note)` --
`active_tracked_filers(as_of_time)` reads the point-in-time VIEW,
never the raw `TRACKED_FILERS` constant directly. This is the direct
answer to the account owner's retirement/death concern: editing
`tracked_until` for one investor today changes nothing about what a
backtest computes for an `as_of_time` before that edit, because
`is_tracked_at` checks `tracked_from <= as_of_time <= (tracked_until or
+inf)` rather than the registry's CURRENT state. This is the same
look-ahead discipline `available_time`/`AsOfDataView` already apply to
the underlying 13F DATA, applied here one level up, to the definition
of WHO COUNTS as tracked.

A plain `active: bool` flag was rejected specifically because it would
retroactively rewrite history the moment a filer's status changed --
exactly the leak `tracked_from`/`tracked_until` exist to prevent.

### Filer selection: four investors, chosen narrowly and verified, not guessed

This sandboxed session's network egress to `sec.gov` is confirmed
blocked (unchanged from ADR-0104/ADR-0192's own re-verification this
session). Each filer's CIK was instead verified via `WebSearch`
against real, dated SEC EDGAR filing URLs and index pages (this
session's `WebFetch` to `sec.gov` itself still failed with
`EGRESS_BLOCKED`, confirming the block is current; `WebSearch` is a
separate, working mechanism, and every claim below is backed by a real
retrieved URL, not invented):

| Filer | CIK | Investor | Status as of 2026-09-24 |
|---|---|---|---|
| Berkshire Hathaway Inc | 0001067983 | Warren Buffett | active |
| Pershing Square Capital Management, L.P. | 0001336528 | Bill Ackman | active |
| Baupost Group LLC/MA | 0001061768 | Seth Klarman | active |
| Scion Asset Management, LLC | 0001649339 | Michael Burry | **deregistered 2025-11-10** |

Scion is a real, already-observed instance of exactly the scenario the
account owner raised -- not a hypothetical test fixture. `tracked_from`
for Scion is its own real founding (May 2013, a DIFFERENT entity than
the earlier Scion Capital LLC, CIK 1182422, which closed in 2008 and is
deliberately not tracked, since that CIK does not file today's data).
`tracked_until` is 2025-11-10, the confirmed deregistration date --
`guru_consensus_score` for any `as_of_time` on or before that date
still counts Scion; any later `as_of_time` does not, matching what was
actually true then.

**Selection criteria (RULE 0.8, decided before any factor result
exists)**: a fixed, small set of investors with long (>= 10 years),
individually well-documented, publicly-attributed track records under
their own name -- deliberately NOT a "biggest 13F filers by AUM/size"
ranking, which would immediately be dominated by index-fund managers
and market-makers with no active stock-picking thesis at all
(BlackRock, Vanguard, State Street, Citadel Securities). A size-based
ranking would also just reinvent `institutional_ownership_change_
score`'s existing aggregate signal under a different name. Expanding
this curated list later (adding more named investors) is expected and
fine; changing the SELECTION CRITERIA to a size ranking is not.

### `guru_consensus_score`: RULE 0.8 construction, honest attribution

Raw, unweighted COUNT of currently-tracked filers (per
`active_tracked_filers(as_of_time)`) with a known, positive reported
position in the security as of their own most recent available quarter
-- not weighted by position size or AUM (no independently-verified
basis exists in this project for cross-fund weighting), not negated
(more agreement hypothesized to predict higher returns, matching this
module's "higher score = more attractive" convention). Returns `0.0`
(a real "no consensus" result) when filers are tracked but none holds
a position yet; returns `None` only when NO filer was tracked at all as
of `as_of_time` (nothing measurable).

Unlike `institutional_ownership_change_score`'s Chen/Jegadeesh/Wermers
(2000) academic basis, this factor is explicitly documented as **the
account owner's own construction, not a published academic citation**
-- following this project's "never fabricate a citation" discipline
(ADR-0047) exactly as `institutional_ownership_change_score`'s own
docstring already models for an idea with no literature citation.

### Wiring

New `--institutional-filer-db-path` CLI flag on
`scripts/run_long_horizon_validation.py`, gated independently of every
other `--*-db-path` flag (same pattern as `--institutional-db-path`,
`--short-interest-db-path`, etc.) -- a SEVENTH distinct DuckDB catalog,
distinct from `--institutional-db-path` (that one is the all-filers
aggregate; this one the per-filer tracked-filer data).
`institutional_filer_included` added to the experiment_id-affecting
report metadata, matching every other `*_included` flag's own
collision-prevention reasoning.

## Consequences

- A future retirement/death/fund-closure of a tracked investor is a
  one-line registry edit (`tracked_until=...`), not a code change, and
  provably does not alter past backtest results (see the
  `test_editing_tracked_until_does_not_change_a_past_as_of_time` and
  `test_a_deregistered_filers_last_known_position_is_excluded_after_
  deregistration` tests).
- This factor has NOT been run against real data -- this sandboxed
  session's network is still blocked (see above), and no per-filer 13F
  CSV has been produced by the account owner's own external
  preprocessing yet. Real per-filer data acquisition would need the
  same kind of external, network-capable step
  `institutional_ownership_change_score`'s own aggregate data already
  requires, filtered down to just `TRACKED_FILERS`' CIKs.
- `guru_consensus_score` is gated independently, so its absence never
  blocks any other candidate; omitting `--institutional-filer-db-path`
  reproduces every prior run's behavior exactly.

## Tests

`tests/data_infra/test_tracked_institutional_filers.py` (registry
construction, `is_tracked_at`/`active_tracked_filers` point-in-time
behavior, the real Scion deregistration date's effect before/after);
`tests/data_infra/test_institutional_holding_models.py` (added
`InstitutionalFilerHoldingRecord` validation classes);
`tests/data_infra/test_institutional_filer_holding_file_import.py`
(combined-CSV parsing/validation); `tests/storage/
test_institutional_filer_holding_repository.py` (persistence,
idempotency, point-in-time look-ahead guard, `get_latest_holdings_for_
security` multi-filer behavior); `tests/strategy_research/
test_guru_consensus_score.py` (construction, the `0.0`-vs-`None`
distinction, the deregistration-exclusion scenario using Scion's real
CIK); `tests/data_infra/test_ingest_institutional_holdings_cli.py`
(new `TestIngestInstitutionalHoldingsCliFilerCombinedCsv` class,
end-to-end real DuckDB write/read); `tests/strategy_research/
test_run_long_horizon_validation_factor_wiring.py` (updated candidate-
table union/count to include `guru_consensus`). Full suite run before
merge as the merge gate (see PR).
