# ADR-0092: General-purpose lookahead-bias audit added

**Status:** Accepted
**Session:** 36 (continued)

## Context

Third of the 5 items identified from comparing this project against
`dragon1086/prism-insight` (see ADR-0090's Context for the full
background), per the account owner's "전부 적용" instruction.

Before writing anything, the actual residual risk had to be identified
correctly rather than assumed: `strategy_research.factor_scores`'s
fundamentals-family score functions (`FundamentalsScoreFn`/
`HybridScoreFn`/`UniverseScoreFn`) all take a raw `repository: object`
and forward `as_of_time` into it themselves, unlike the price-only
`ScoreFn` family, which reads through `AsOfDataView` (a structural,
can't-request-the-future guard, ADR-0004). Reading
`storage.fundamentals_repository.DuckDBFundamentalsRepository.
get_fundamentals` and `storage.insider_repository.DuckDBInsiderRepository.
get_insider_transactions` directly showed both already enforce
`available_time <= as_of_time` as a hard SQL `WHERE` clause -- also a
structural guard, not ad hoc per-function filtering as initially
assumed. So the real, residual, previously-unaudited risk is narrower
than "does a score function forget to filter": it is "does a score
function forward the exact `as_of_time` it received into every one of
its own sub-queries" -- a wrong-argument or stale-variable wiring bug a
structural per-repository guard cannot catch by itself, since the guard
only protects a query actually given the correct time. This project has
hit exactly that class of bug twice already this session in a different
subsystem (the "매매 근거 기록 후 재학습" pipeline wiring bugs,
`PROJECT_STATUS.md` Session 36).

## Decision

Added `tests/strategy_research/test_lookahead_bias_audit.py`: one
shared assertion helper, `_assert_unaffected_by_a_future_record`, that
computes a score, adds exactly one record dated strictly after
`as_of_time` (with a value dramatic enough to visibly change the score
if it leaked), recomputes, and asserts the two results are identical.
Applied to one representative function per DISTINCT code path this
module has, not all ~28 registered fundamentals-family functions
(stated explicitly in the test file's own module docstring, not
implied): `roe_score` (`_fy_ratio`/`_fy_records`, shared verbatim by
`roa_score`/`net_margin_score`/`leverage_score`/`gross_profitability_
score`), `asset_growth_score` (year-over-year `_fy_records`),
`sue_score` (`_quarterly_records`, the only quarterly-granularity
path), `insider_buying_score` (the only score reading
`DuckDBInsiderRepository` rather than `DuckDBFundamentalsRepository`,
and the only one with no dedicated unit test file at all until now),
`shareholder_yield_score` (`HybridScoreFn`, needs both fundamentals and
price), `quality_minus_junk_score` (`UniverseScoreFn`, the
cross-sectional call shape).

**Verified the fixtures are not vacuously true before trusting them**:
for the `roe_score` case, manually confirmed that querying with a
LATER `as_of_time` (after the "future" record's `available_time`) DOES
pick up the added record and changes the score from `0.2` to `999.99`
-- proving the added record genuinely would leak into the answer if the
guard were broken, not merely that nothing in the fixture happens to
matter.

## What this does NOT do

Does not claim to audit all ~28 registered fundamentals-family score
functions individually -- 6 representative code paths, explicitly
listed above and in the test file's own docstring. Does not re-test the
repository-layer `available_time <= as_of_time` SQL guard itself
(already covered by that layer's own existing tests) -- this audit's
target is one level up, the calling score function's own `as_of_time`
forwarding. Does not touch the price-only `ScoreFn` family
(`low_volatility_score` and friends) -- those already read through
`AsOfDataView`'s own structural guard, and re-testing that guard here
would just be re-testing Phase 1/2's own point-in-time correctness
work, already covered elsewhere. Does not implement the remaining 2
`prism-insight`-derived items (reentry cooldown, shadow-evaluation
harness -- tracked separately).

## Tests

`tests/strategy_research/test_lookahead_bias_audit.py` (6 tests, one
per representative code path, all passing against the actual current
code -- i.e., this audit did not find a real bug, it establishes a
mechanism that would catch one going forward). No existing test files
changed.
