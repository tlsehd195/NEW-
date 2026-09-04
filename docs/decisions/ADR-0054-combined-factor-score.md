# ADR-0054: `combined_factor_score` -- a 9-leg rank-averaged combination of the sign-matching Phase 33 candidates

**Status:** Accepted
**Session:** 36

## Context

Phase 33's 28-candidate walk-forward/PBO/DSR run (`docs/research/
STRATEGY-VALIDATION-REPORT.md`'s "Phase 33 Addendum") concluded with
zero `VALIDATED` candidates -- `size` and `altman_z`/
`rank_average_ensemble` reached `CANDIDATE` but were TEST-negative or a
concentration artifact. The user, after asking why the project keeps
getting stuck and how it will be fixed, explicitly asked to proceed
with all three of the diagnosis's proposed next steps at once
("전부 다 진행하는건?"): (1) combining factors, (2) sector
neutralization, (3) universe expansion. This ADR covers (1).

## Decision

Added `combined_factor_score` to `src/strategy_research/
factor_scores.py`, immediately after `value_composite_score`. It
rank-averages the 9 of the 20 Session 36 candidates whose raw IC SIGN
matched the direction their own literature predicts (Phase 33
Addendum section B): `short_term_reversal`, `illiquidity`,
`piotroski`, `dividend_growth`, `sloan_accruals`, `size`, `altman_z`,
`shareholder_yield`, `quality_minus_junk` (itself already a 3-leg
composite).

**Selection rule, stated precisely -- not a new practice**: sign-based
only (does the raw IC point the direction literature predicts), never
by IC magnitude or by which candidate "looked most promising" after
seeing results. This is the exact same rule `ADR-0043` Decision 5
already established for `RankAverageEnsembleStrategy`'s
leverage+net_margin pair, applied here at a larger, pre-registered
scale (all 9 qualifying candidates, not a hand-picked subset).
Including a wrong-signed factor can only dilute a real signal, never
strengthen it -- `ensemble_strategy.py`'s own docstring already gives
this reasoning for its own smaller combination.

**Construction** mirrors `value_composite_score`/`quality_minus_junk_
score` exactly: each of the 9 raw component scores is cross-
sectionally rank-averaged independently via `signal_ic.rank_average`,
then the 9 per-security ranks are averaged into one final score.
All-or-nothing on missing data (a security missing ANY of the 9 legs
is excluded from that date's cross-section entirely), the same
discipline every composite score in this module already uses. Returns
`{}` if fewer than 2 securities have all 9.

**Plumbing needed for 2 of the 9 legs**: `short_term_reversal_score`/
`illiquidity_score` are `PriceScoreFn`s (need an `AsOfDataView`, not
the raw `price_repository` `combined_factor_score` receives) --
a fresh single-checkpoint `AsOfDataView` is built internally for
exactly this, the same pattern `signal_ic.compute_ic_series`/
`compute_universe_ic_series` already establish.

`combined_factor_score` is `UniverseScoreFn`-shaped, identical to
`quality_minus_junk_score`/`value_composite_score`'s own shape, so it
needed no new Strategy class (`strategy_research/factor_strategy.py`'s
existing `UniverseFactorStrategy` already covers it) and no new IC
computation function (`signal_ic.compute_universe_ic_series` already
covers it) -- wired into `scripts/compute_fundamentals_ic_from_
catalog.py`'s existing `_UNIVERSE_SCORES` dict as `--score
combined_factor`, next to `quality_minus_junk`/`value_composite`.

**Deliberately NOT yet wired into `run_long_horizon_validation.py`'s
walk-forward/PBO/DSR pool** -- matching `idiosyncratic_volatility_
score`'s own ADR-0053 precedent: raw IC comes first, before any
decision about pool inclusion (which may still end up being "wire it
regardless of the raw IC result," per ADR-0051's own precedent -- that
decision is not made by this ADR).

## Tests

4 new tests in `tests/strategy_research/test_factor_scores.py`
(`TestCombinedFactorScore`) using monkeypatched fakes for all 9
underlying legs, matching `test_factor_strategy.py`'s isolation
approach rather than building real per-factor fixtures for a 9-leg
composite -- these tests are about the aggregation logic itself (rank-
averaging, all-or-nothing exclusion, the fresh `AsOfDataView`
construction for the 2 price-only legs), not about re-testing any
individual factor's own already-tested construction: a security
scoring higher on every leg scores higher overall; a security missing
any one leg is excluded; a security missing from the upfront
`quality_minus_junk_score` call is excluded before the per-security
loop; fewer than 2 scorable securities returns `{}`.

1 new test in `tests/strategy_research/
test_compute_fundamentals_ic_from_catalog_cli.py`
(`TestCombinedFactorScoreOption`) -- a real end-to-end CLI run against
a small synthetic 2-symbol catalog covering all 9 legs' concepts at
once, proving `--score combined_factor` actually produces a non-zero
IC observation. This test's own fixture deliberately gives the 2
symbols DIFFERENT fundamentals AND different price drift (unlike the
identical-value pattern the neighboring `quality_minus_junk`/
`value_composite` CLI test uses) -- identical values would tie every
score and every forward return, making `spearman_ic` correctly (not a
bug) return `None` for a zero-variance side, silently producing
`observations=0` even with fully correct CLI wiring. This was caught
directly (the test failed with `observations=0` on the first,
identical-fixture attempt) rather than assumed.

Full suite: 2223 passed (up from 2218).

## What this does NOT do

- Does not wire `combined_factor_score` into the walk-forward/PBO/DSR
  pool -- a separate decision after raw IC is seen (see Decision
  above).
- Does not change the selection of which 9 legs are combined based on
  anything discovered while building or testing this function -- the 9
  were fixed by the Phase 33 Addendum's already-published raw IC table
  before this ADR was written.
- Does not touch `idiosyncratic_volatility_score` (ADR-0053) -- that
  candidate's own raw IC has not yet been seen, so it cannot be
  included in a sign-matching selection yet; a future ADR may revisit
  `combined_factor_score`'s leg list once it is.
