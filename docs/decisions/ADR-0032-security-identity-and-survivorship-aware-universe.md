# ADR-0032: Security Identity and Survivorship-Aware Universe (Phase 29)

**Status:** Accepted

## Context

Phase 29's instruction asks for a broad, long-horizon (2010 -> latest),
survivorship-bias-aware US equity universe: securities identified by a
permanent identity independent of ticker, delisted/renamed/merged
securities included rather than only today's survivors, and
`get_universe(as_of_date)` returning genuinely different results for
different historical dates. Its central question: *"was a good result
produced by picking today's known winners and projecting them into the
past, or would the strategy have repeatedly worked against the real,
full, historically-correct universe?"*

## Decision 1 -- Audit first: this architecture already exists (Phase 1), unmodified

Before writing anything, this phase audited `src/data_infra/models.py`
and `src/data_infra/repository.py` directly rather than assuming a new
`SecurityIdentity` concept was needed. It already is:

- `SecurityMaster.security_id` is already a stable identifier
  independent of `ticker` ("ticker/exchange/status can change over the
  security's life without invalidating historical references", Phase 1
  spec section 6) -- this is exactly the "permanent identifier" concept
  the instruction asks for, just not under that name.
- `SecurityMaster.valid_from`/`valid_to` and `SecurityStatus`
  (`ACTIVE`/`DELISTED`/`RENAMED`/`MERGED`) already model exactly the
  delisted/inactive tracking the instruction asks for.
- `UniverseMembership.valid_from`/`valid_to` (Phase 1 spec section 8,
  its own docstring already says "used to support survivorship-bias-free
  historical universe queries") already scopes universe membership to a
  real historical interval.
- `DataRepository.get_universe(market, universe, as_of_time)` (both
  `InMemoryDataRepository` and `storage.data_repository.DuckDBDataRepository`,
  Phase 1/4, unmodified) already does exactly the point-in-time
  filtering the instruction's worked example (section 12) describes --
  verified directly by reading both implementations' query logic, not
  assumed: `InMemoryDataRepository` filters via
  `UniverseMembership.is_member_at(as_of_time)` in Python;
  `DuckDBDataRepository` runs the equivalent
  `valid_from <= ? AND (valid_to IS NULL OR ? < valid_to)` SQL. Both
  paths were exercised this phase (`tests/data_infra/test_phase29_survivorship_aware_universe.py`
  for the in-memory path, a new case in
  `tests/strategy_research/test_duckdb_backed_research_pipeline.py` for
  a real on-disk DuckDB restart) and both correctly exclude a delisted
  security once `as_of_time` passes its `valid_to`, and correctly
  exclude a not-yet-listed security before its `valid_from`.

This was the only design considered: building a second, parallel
"SecurityIdentity" type alongside `SecurityMaster` would have
duplicated an already-correct, already-tested Phase 1 mechanism for no
benefit, repeating the exact mistake ADR-0030 explicitly avoided for
`UniverseMembership` one phase earlier.

## Decision 2 -- The real gap: per-symbol historical dates were never wired through

`SymbolMetadata` (Phase 24) already had `listed_from`/`listed_to`
fields. `build_security_masters`/`build_universe_memberships`
(`src/data_infra/universe.py`, also Phase 24) ignored them --
every symbol in a `UniverseDefinition` was given the SAME
caller-supplied `valid_from`, an unconditional `valid_to=None`, and a
hardcoded `status=SecurityStatus.ACTIVE`, regardless of what
`SymbolMetadata` actually recorded. This meant the Phase 1
survivorship-aware query mechanism above had no path to ever receive
real per-symbol historical dates -- the gap was in population, not in
the underlying architecture.

Fixed additively: both functions now use `s.listed_from or valid_from`
and `s.listed_to` per symbol, and `status` is derived as `DELISTED`
when `listed_to` is set, `ACTIVE` otherwise. This cannot distinguish
`RENAMED`/`MERGED` from a plain `DELISTED` using only two dates --
`SymbolMetadata` carries no explicit reason field -- so `DELISTED` is
used as the honest, least-specific-that-is-still-correct default rather
than guessing a more specific one. Every existing `SymbolMetadata`
entry in this project (`PILOT_UNIVERSE_V1`, all `listed_from`/`listed_to`
still `None`) produces byte-for-byte identical output to before this
change -- confirmed by a dedicated regression test
(`test_symbol_without_confirmed_listed_dates_falls_back_to_caller_value_unchanged`),
so this is purely additive.

## Decision 3 -- Ticker-reuse vs. ticker-collision, distinguished structurally

Instruction section 8 names a real risk: the same ticker string can
belong to two different companies at two different points in time
(legitimate reuse), or -- as a data bug -- to two different
`security_id`s at the *same* point in time (a genuine collision that
would silently merge two unrelated companies' histories).
`data_infra.universe.detect_ticker_collisions` distinguishes these:
two `SecurityMaster` records sharing a `ticker` with non-overlapping
`[valid_from, valid_to)` windows is not flagged (legitimate reuse); the
same ticker with overlapping windows across two different
`security_id`s is. It returns findings rather than raising -- callers
(a future ingestion script, a test) decide whether a finding is fatal
for their use case.

## Decision 4 -- Broad-universe discovery groundwork: `fetch_symbol_metadata`, not broad ingestion itself

Instruction section 15 (Stage 1) asks for provider metadata discovery
as the first step toward a broad universe. `TiingoDataProvider.fetch_symbol_metadata`/
`normalize_symbol_metadata` were added, mirroring exactly how
`fetch_corporate_actions`/`normalize_corporate_actions` (Phase 20)
isolated their own Tier-2-documentation assumptions in one place --
this module has never been exercised against a live Tiingo response in
this environment (network to `api.tiingo.com` remains
`BLOCKED_BY_ENVIRONMENT`, re-verified this phase, unchanged since Phase
26's diagnosis). `normalize_symbol_metadata` maps only the fields Tier
2 documentation actually names (`ticker`, `exchangeCode`, `startDate`,
`endDate`) into `SymbolMetadata`; `sector`/`market_cap_bucket` are never
populated from this endpoint (not part of its documented shape) and
stay `None`, per this project's "never guess a value a provider does
not actually supply" discipline (ADR-0030 Decision 3, same rule,
reapplied here).

**This phase does not perform broad ingestion.** With network access
blocked, no real `SymbolMetadata` was ever fetched, and no
`RESEARCH_UNIVERSE` Stage 2/broad/survivorship-aware named universe was
populated with real dates -- doing so would mean guessing dates this
project's own discipline forbids guessing. The plumbing (Decisions 2-4)
is now ready and tested; population remains blocked exactly as real
ingestion has been blocked since Phase 20, for the same, unchanged
reason.

## Consequences

- A future phase with real network/provider access can populate
  `SymbolMetadata.listed_from`/`listed_to` per symbol (via
  `fetch_symbol_metadata`/`normalize_symbol_metadata` or an equivalent
  real source) and immediately get a genuinely survivorship-aware,
  point-in-time-correct universe out of `build_security_masters`/
  `build_universe_memberships` -- no further architecture work is
  required.
- `get_universe(as_of_date=...)` returning different results for
  different historical dates -- the instruction's central technical
  ask -- was proven correct this phase against both the in-memory and
  the real on-disk DuckDB persistence paths, using synthetic fixtures.
  This is a pipeline-correctness result, not a claim about any real
  historical US equity universe (none exists in this environment; see
  `docs/research/STRATEGY-VALIDATION-REPORT.md`'s Phase 29 Addendum).
- Delisting-return availability (instruction section 47's documented
  limitation -- a delisted security's last available price is not
  necessarily its true delisting return) remains unresolved and
  undocumented as anything more than a known limitation; this ADR does
  not claim "survivorship-bias-free," only "survivorship-aware" (the
  distinction the instruction itself insists on in section 47).
