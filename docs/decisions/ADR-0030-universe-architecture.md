# ADR-0030: Expandable Universe Architecture (Phase 24)

**Status:** Accepted

## Context

Phase 22 adopted a fixed 16-symbol US long-term Paper Trading universe
as a pilot. Phase 23's strategy research framework consumed that list
implicitly (via whatever `security_ids` a caller happened to pass).
Neither phase built a structural mechanism preventing that 16-symbol
list from becoming a permanent ceiling -- it simply hadn't been an
issue yet, since no caller had tried to use a different list. Phase 24's
instruction explicitly requires closing that gap: the pilot universe
must remain available, but the codebase must not treat it as the only
possible universe, must not hardcode it inside strategy code, and must
document a real path to expansion without inventing unverifiable
provider limits.

## Decision 1 — Build on Phase 1's `UniverseMembership`, not around it

A repo-wide check (`grep -rln '"AAPL"' src/`) confirmed that, in fact,
no symbol list was ever hardcoded inside `src/` at all -- the 16-symbol
list existed only in documentation prose and in
`scripts/ingest_real_market_data.py`'s own `DEFAULT_UNIVERSE` constant.
What was genuinely missing was a *named, versioned* way to describe a
universe with metadata, and a populator for Phase 1's own
`UniverseMembership`/`SecurityMaster` records (`data_infra.models`,
Phase 1 spec section 8: "used to support survivorship-bias-free
historical universe queries") -- which had a query side
(`DataRepository.get_universe(market, universe, as_of_time)`,
already point-in-time-safe by construction) but no populator anywhere
in `src/`; every existing populated universe in this codebase came from
hand-built test fixtures. `src/data_infra/universe.py` adds exactly
that populator layer, reusing the underlying persistence mechanism
unchanged. This was the only design considered: reimplementing
membership storage would have duplicated Phase 1 for no benefit.

## Decision 2 — `UniverseDefinition`/`SymbolMetadata`, `role` in `{"PILOT", "RESEARCH"}`, benchmark structurally excluded

`UniverseDefinition(name, version, role, description, symbols)` is a
plain, validated dataclass. `role` is restricted to `"PILOT"` or
`"RESEARCH"` by `__post_init__` -- there is no `"BENCHMARK"` role,
because `BENCHMARK_SYMBOL` (`"SPY"`) is tracked as a single module-level
constant, never as a `UniverseDefinition` member. `UniverseDefinition.__post_init__`
actively raises `ValueError` if `BENCHMARK_SYMBOL` appears among its
`symbols` -- instruction section 32/13's "전략 universe와 benchmark를
혼동하지 않는다" is enforced structurally, not just documented.

## Decision 3 — Every `SymbolMetadata` field beyond the bare symbol defaults to unconfirmed

`exchange`, `sector`, `market_cap_bucket`, `listed_from`, `listed_to`
all default to `None`. `PILOT_UNIVERSE_V1`'s 15 entries leave every one
of these `None` -- including `exchange`, even though "AAPL trades on
NASDAQ" is common knowledge. This was a deliberate choice weighed
against the alternative (filling in well-known exchange names from
general knowledge): the instruction's own repeated wording ("provider가
실제로 제공하지 않는 정보를 추측하여 채우지 않는다. UNKNOWN은 UNKNOWN으로
남긴다") reads as a description of what THIS SYSTEM has verified, not
what is true in the world -- and this module's entire purpose is to be
that honest record. `build_security_masters` uses the literal string
`"UNKNOWN"` as `SecurityMaster.exchange`'s fallback (that field is
non-Optional `str`), never a guessed exchange name.

## Decision 4 — `RESEARCH_UNIVERSE` Stage 1 is intentionally identical to `PILOT_UNIVERSE`

Instruction section 31 lays out a 4-stage expansion plan (16 → ~30-50 →
provider-limit-confirmed further expansion → survivorship-aware
membership) but explicitly forbids assuming a free-tier limit
("임의로 '50개 가능'이라고 가정하지 않는다"). This session re-attempted
gathering that evidence via two independent paths -- direct `curl`
through the egress proxy, and `WebFetch` (a separate fetch mechanism)
against `www.tiingo.com` and `stooq.com` -- both returned
`EGRESS_BLOCKED` for every domain tried, identical to every prior
phase's finding. With no confirmed limit, Stage 2 is not populated:
`RESEARCH_UNIVERSE_STAGE1`'s symbols are identical to
`PILOT_UNIVERSE_V1`'s, existing as a distinct *name* so a caller can
already opt into "the research universe, whatever it currently is"
without a future Stage 2 population requiring call-site changes.

## Decision 5 — Survivorship-bias limitation stated, not solved

Instruction section 5 draws the same distinction Phase 22/23 already
established for benchmark/FX honesty: applying a *currently selected*
universe to historical data is not the same claim as a
survivorship-bias-free historical constituent backtest. Neither
`PILOT_UNIVERSE_V1` nor `RESEARCH_UNIVERSE_STAGE1`'s docstrings claim
the latter. Phase 1's `UniverseMembership.valid_from`/`valid_to`
interval design already has the *structural* capacity for a future,
real point-in-time constituent membership dataset (a symbol could be
added to a universe with `valid_from` = its actual historical addition
date, and removed via `valid_to` at its actual removal date) -- this
phase does not populate that history (no such dataset exists or was
obtainable), but the extension point is real, not hypothetical: a
future phase would populate `UniverseMembership` records with real
historical `valid_from`/`valid_to` dates instead of Phase 24's own
`valid_from` (the caller-supplied ingestion start date).

## Decision 6 — `scripts/ingest_real_market_data.py`: `--universe` selects a `UniverseDefinition`, populates `SecurityMaster`/`UniverseMembership` too

The script's `DEFAULT_UNIVERSE` constant (a bare tuple) is replaced by
`--universe {PILOT_UNIVERSE,RESEARCH_UNIVERSE}` resolving against
`src/data_infra/universe.py`; `--symbols` remains as an explicit
override for ad-hoc runs, bypassing the universe registry entirely.
The script now also calls `build_security_masters`/
`build_universe_memberships` and persists both before running
ingestion -- previously it only ever wrote price bars, leaving the
`SecurityMaster`/`UniverseMembership` tables permanently empty even
after a real ingestion run. A content checksum
(`data_infra.versioning.compute_data_version`, unmodified, the same
function Phase 1 already uses for `data_version` computation) is now
recorded in the reproducibility manifest, satisfying instruction
section 12's "실제 데이터가 생성된 경우 checksum을 기록할 수 있도록 한다."

Manually smoke-tested end to end this session (stubbed transport, fake
API key, a temp DuckDB directory) -- universe resolution, ingestion,
`SecurityMaster`/`UniverseMembership` persistence, restart survival,
and checksum computation all verified working. This was NOT committed
as an automated test, since the script itself must never be imported
by one (instruction section 24's "실제 네트워크를 자동 테스트에서 호출하지
않는다" -- an importable test could accidentally trigger `main()`'s
real network path).

## Decision 7 — `strategy_research` needed zero code changes

`strategy_research.runner.run_gross_and_net`'s `security_ids: Sequence[str]`
parameter (Phase 23) already accepted any sequence of symbol strings,
including `UniverseDefinition.symbol_ids` (a plain `tuple[str, ...]`)
with no adaptation. No strategy class, the runner, or any other
`strategy_research` module was modified this phase --
`tests/strategy_research/test_universe_wiring.py` proves this by (a)
statically confirming no `PILOT_UNIVERSE` symbol appears as a Python
string literal anywhere in `src/strategy_research/`, and (b) exercising
the real call shape with `UniverseDefinition.symbol_ids` directly.

## Consequences

- The codebase can now express "PILOT_UNIVERSE" vs "RESEARCH_UNIVERSE"
  as distinct, named, versioned objects with a documented (if currently
  unconfirmed) metadata surface, without any strategy, backtest, or
  Paper Trading code needing to know which one is in use.
- Real universe expansion beyond 16 symbols remains genuinely blocked on
  the same constraint that has blocked real ingestion since Phase 20:
  provider network access. This ADR does not resolve that; it makes the
  expansion path ready the moment that constraint lifts.
- Survivorship-bias-free historical backtesting remains unimplemented
  and undocumented as anything more than a structural extension point --
  no false "survivorship-free" claim is made anywhere in this codebase
  as a result of this phase's work.
