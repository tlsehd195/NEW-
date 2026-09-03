# ADR-0052: Increase evaluation portfolio breadth (top_n 5 -> 10) uniformly, for all candidates

**Status:** Accepted
**Session:** 36

## Context

ADR-0051's real 28-candidate walk-forward/PBO/DSR run (see
PROJECT_STATUS.md) found `size` reaching `CANDIDATE` evidence level with
a strong held-out TEST return (+85.26%). Pulling the existing
`compute_contribution_report_from_fills` concentration report for that
TEST run showed the return was almost entirely one security: SLB
(Schlumberger, an oilfield-services company) accounted for 76.3% of
total PnL (`top_1_share_of_positive_pnl=63.8%`,
`top_3_share_of_positive_pnl=94.1%`, Herfindahl index 0.348 against a
0.10 equal-weight-of-10 baseline). The held-out TEST window
(2020-08-28 to 2023-04-28) overlaps the real 2022 oil-price
supercycle (Russia-Ukraine war). This reads far more plausibly as "held
one energy-sector name during an energy-sector event" than as evidence
of a genuine cross-sectional size effect.

## An initial, incorrect framing -- corrected here

The first framing considered for fixing this was "align the research
evaluation's position sizing with Production's `risk.config.
RiskConfig.max_position_weight` (0.10, Phase 8)". This is wrong and
was corrected before implementation: `risk_controlled_momentum.py`'s
own docstring already states, citing instruction section 17 directly,
that a research strategy's internal position-construction parameters
must NOT be conflated with Production's separate risk limit -- they
solve different problems (does a ranking signal carry information, vs.
capping real capital at risk) and intentionally do not share
configuration or code path. Treating `RiskConfig.max_position_weight`
as this evaluation script's target would have repeated exactly the
confusion that rule exists to prevent.

## Decision

The real, defensible problem is a RESEARCH-METHODOLOGY one, independent
of Production risk limits: **every strategy this project has ever
walk-forward-tested defaults to `top_n=5`** (`FactorStrategyParameters`,
`LeverageParameters`, `LongTermMomentumParameters`,
`RiskControlledMomentumParameters`, `RankAverageEnsembleParameters`,
`MLStrategyParameters` -- all six top_n-bearing `*Parameters`
dataclasses in this codebase). Holding only 5 of 63 universe names at
once leaves too little breadth for a cross-sectional ranking signal's
OWN research evidence to average out a single name's idiosyncratic
outcome -- exactly what happened to `size`. This is true regardless of
which candidate is examined; it is not a property of `size`
specifically.

`scripts/run_long_horizon_validation.py` gets a single new module-level
constant, `_TOP_N_FOR_EVALUATION = 10` (roughly 1/6 of the 63-symbol
`RESEARCH_UNIVERSE_STAGE3`, twice the prior default), passed explicitly
to every candidate's `Parameters` construction in this script only --
the six `*Parameters` dataclasses' own class-level defaults (`top_n=5`)
are UNCHANGED, so any other caller (this project's own unit tests
included) is unaffected. Applied identically to all 28 candidates
(`buy_and_hold` has no top_n; `trend_volatility` holds every
qualifying name and has no top_n concept either -- both correctly
untouched).

## Why this is not a RULE 0.8 violation

The value was chosen once, applied uniformly to every candidate
regardless of that candidate's prior result, and its effect on any
specific candidate's evidence level is not yet known at the time of
this decision -- the whole point of writing this ADR before re-running
is that whether `size`, `altman_z`, or anything else clears the
CANDIDATE bar under `top_n=10` is an open question this ADR does not
answer. If `size` still shows the same concentration problem at
`top_n=10`, that stands as real evidence against it, not a result to
tune away further.

## Tests

No new automated tests -- this is a constant-value change to CLI
wiring already covered by
`tests/strategy_research/test_run_long_horizon_validation_wiring.py`/
`test_run_long_horizon_validation_factor_wiring.py`'s existing
placement/closure checks, which do not assert on the specific `top_n`
value passed. Those existing tests DID catch a real bug in this
change's first draft: `FactorStrategyParameters` was referenced inside
the new factory functions without being imported, an oversight the
AST-only sibling file cannot catch (it never imports the script) but
the real-import factory-wiring tests immediately failed on with
`NameError`. Fixed by adding the missing import. Full suite: 2213
passed (unchanged from ADR-0051's count -- no test count change, since
this ADR only changes a constant value + fixes the import it exposed).

## What this does NOT do

- Does not change any `*Parameters` dataclass's own class-level
  default -- `top_n=5` remains the default for any direct caller
  outside this script (e.g. a smaller ad-hoc test or a different
  script).
- Does not touch Production's `risk.config.RiskConfig.
  max_position_weight` or any Live/Paper trading code path -- this ADR
  changes only how many names `run_long_horizon_validation.py`'s
  research candidates hold, per instruction section 17's explicit
  separation.
- Does not re-run the walk-forward evaluation itself -- still requires
  the user's own environment (real network access); see
  PROJECT_STATUS.md for the re-run command.
- Does not add a discrete, validated `TOP_N_RANGE` the way
  `rebalance_months`/`vol_threshold`/`max_position_weight` already have
  in this codebase -- `top_n` remains only `>= 1`-validated. Left as a
  known, separate, smaller gap for a future session.
