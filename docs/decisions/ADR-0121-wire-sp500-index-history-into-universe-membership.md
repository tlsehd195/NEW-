# ADR-0121: Wire Real S&P 500 Index Constituent History into `UniverseMembership`

**Status:** Accepted
**Date:** 2026-09-11
**Deciders:** Claude Code (documentation cleanup session, continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0120-sp500-index-constituent-history.md`,
`docs/decisions/ADR-0037-sp500-point-in-time-membership.md`,
`docs/decisions/ADR-0061-sp500-pit-listed-from-wiring.md`,
`docs/decisions/ADR-0033-real-historical-us-equity-data-source-decision-tree.md`

---

## Context

`ADR-0120` built and real-data-verified `data_infra.providers.
sp500_index_constituent_history` (parsing/query only) against the
real, MIT-licensed `fja05680/sp500` dataset, but deliberately deferred
"actually wiring this into `universe.py`/`UniverseDefinition`" as a
separate future decision -- specifically flagging the open question of
whether `UniverseDefinition.role` should gain a new `"INDEX"` value.

The user asked directly to complete that wiring
("universe.py에 실제로 배선해줘"). Re-examining the actual mechanism
`UniverseDefinition`/`build_universe_memberships` exist to feed --
`DataRepository.get_universe(market, universe, as_of_time)` (Phase 1,
unmodified since) -- showed that `UniverseDefinition`/`SymbolMetadata`
is not, in fact, a necessary intermediate step: `get_universe` reads
directly from whatever `UniverseMembership` records exist in the
repository for a given `universe` string, and its implementation
already correctly ORs across MULTIPLE records sharing the same
`security_id` (`InMemoryDataRepository.get_universe`, `storage.
data_repository.DuckDBDataRepository`'s DuckDB-backed equivalent --
both unmodified). Going through `UniverseDefinition` would have
actually been the WRONG choice here: `SymbolMetadata` carries exactly
one `listed_from`/`listed_to` pair per symbol, and cannot represent a
ticker that left the index and later re-entered (e.g. real `AAL`:
1996-01-02 to 1997-01-15, then 2015-03-23 to 2024-09-23) without either
collapsing the two intervals into one (fabricating a continuous
membership that did not exist) or picking only one (silently dropping
real data).

## Decision 1 -- Build `UniverseMembership` records directly from `TickerMembershipInterval`s, bypassing `UniverseDefinition` entirely

Added `build_sp500_index_universe_memberships(intervals) ->
list[UniverseMembership]` to `sp500_index_constituent_history.py`
itself (not `universe.py` -- keeps the provider module self-contained,
consistent with `short_interest_file_import.py`/`institutional_
holding_file_import.py`'s own pattern of producing their target domain
records directly rather than routing through an intermediate
definition object). One `UniverseMembership` record **per interval**,
never per ticker: `AAL`'s two real intervals become two independent
records, both correctly queryable since `get_universe` already ORs
across records for the same `security_id`.

This answers ADR-0120's own deferred question: `UniverseDefinition.
role` does **not** need a new `"INDEX"` value, because this universe
was never built through `UniverseDefinition` at all. `PILOT_UNIVERSE_
V1`/`RESEARCH_UNIVERSE_STAGE*`'s `role` enum (`"PILOT"`/`"RESEARCH"`)
is completely untouched by this ADR -- zero lines changed in
`universe.py`.

## Decision 2 -- A deliberate, disclosed interpretive choice on `end_date` boundary semantics

`TickerMembershipInterval.contains()` (used by `constituents_as_of`)
treats `end_date` as INCLUSIVE. `UniverseMembership.valid_to` is,
project-wide, a half-open EXCLUSIVE boundary (`SecurityMaster`'s own
docs use the identical convention). `build_sp500_index_universe_
memberships` converts `end_date` straight to `valid_to` -- i.e.
EXCLUSIVE in the persisted record, differing from the raw interval's
own inclusive query semantics.

This is not an oversight; it is required for correctness at the real
`FB`/`META` boundary this session already found (ADR-0120): both rows
share the identical date, `FB.end_date == META.start_date ==
2022-06-09`. Treating `valid_to` as exclusive means the converted `FB`
record is a member up to but not including 2022-06-09, and `META`'s
record is a member from 2022-06-09 onward -- a clean, non-overlapping
handoff. Treating it as inclusive instead would make both `FB` and
`META` simultaneously "members" on 2022-06-09, which is not a real
state of the world for what is genuinely one continuous ticker rename.
Documented explicitly in the function's own docstring, including the
resulting (intentional) discrepancy between the two query paths'
boundary-day behavior.

## Decision 3 -- Real, in-session persistence and verification against `DataRepository.get_universe`

`scripts/fetch_sp500_index_history.py` gained a `--db-path` option:
when supplied, it builds a `DuckDBDataRepository` (`storage.engine.
StorageEngine`/`storage.config.StorageConfig`, the same construction
every other real-data ingestion script in this repository already
uses) and calls `add_universe_membership` for every converted record.
The underlying insert is already idempotent (`ON CONFLICT (security_id,
universe, valid_from) DO NOTHING`, unmodified) -- safe to re-run
against a refreshed copy of the source file.

Run for real this session against the live source
(`--db-path ./data/sp500_index_history_db`, not committed, `data/*`
gitignored): **1262 `UniverseMembership` records persisted** under the
`SP500_INDEX_HISTORICAL` universe name. Verified by querying the real
persisted catalog directly:

```
members as of 2020-01-01: 505    members as of 2026-09-11: 503
FB member as of 2020-01-01: True   FB member as of 2026-09-11: False
META member as of 2020-01-01: False  META member as of 2026-09-11: True
AABA member as of 2010-01-01: True   AABA member as of 2026-09-11: False
```

This is the first real, end-to-end, point-in-time-queryable
demonstration in this repository of "which tickers were S&P 500 index
constituents on a historical date, correctly excluding a ticker that
has since left the index" -- exactly the capability ADR-0033 Decision
1 named as absent.

## Decision 4 -- Still not wired into any tradeable universe or strategy input

`SP500_INDEX_HISTORICAL` is queryable via `DataRepository.get_universe`
but is never passed as `security_ids` to any `Strategy` constructor,
never referenced by `ingest_real_market_data.py`/`import_external_
market_data.py`, and does not affect `PILOT_UNIVERSE_V1`/`RESEARCH_
UNIVERSE_STAGE*`, any backtest, Paper Trading session, or
`audit_survivorship` call in any way. This ADR closes the "the real
historical index-membership data is actually queryable in this
project's own storage layer" gap; using it to build a genuinely
survivorship-bias-free tradeable universe/backtest (which would also
require real historical price data for every removed ticker -- a
separate, larger, still-unsolved problem, ADR-0033/ADR-0034) remains
future work.

## Tests

5 new tests (`TestBuildSp500IndexUniverseMemberships`, added to the
existing `tests/data_infra/test_sp500_index_constituent_history.py`),
synthetic fixtures only -- including one that directly exercises
`UniverseMembership.is_member_at` (the exact method `get_universe`
calls) against the built records, and one that verifies a ticker's two
non-contiguous real intervals produce two separate records rather than
one collapsed one.

## Status of Implementation at Time of This ADR

`build_sp500_index_universe_memberships`/`SP500_INDEX_HISTORICAL_
UNIVERSE_NAME` added to `src/data_infra/providers/sp500_index_
constituent_history.py`. `scripts/fetch_sp500_index_history.py` gained
`--db-path`. Run for real this session; 1262 `UniverseMembership`
records persisted to a local (gitignored, not committed) DuckDB
catalog and verified queryable via `DataRepository.get_universe`. Zero
lines changed in `src/data_infra/universe.py`.
