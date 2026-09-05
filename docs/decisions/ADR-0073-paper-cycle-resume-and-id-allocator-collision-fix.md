# ADR-0073: `--resume` for `run_paper_trading_cycle.py`, and a real cross-process ID collision bug it surfaced

**Status:** Accepted
**Session:** 36 (continued)

## Context

The user asked to proceed to the second item on the post-C list: an
always-on scheduler for the Paper Trading pipeline. `PHASE-15-paper-
trading.md` section 1.1 and `paper_runner.py`'s own docstring both
already framed this correctly: the missing piece is not a scheduler
Claude Code should build (a real external cron, or equivalent, invoking
`run_paper_trading_cycle.py` repeatedly, remains genuinely out of
scope) -- it is making repeated invocation of that script actually
SAFE, which nothing had verified before.

## Decision 1 -- `--resume`

`run_paper_trading_cycle.py` gained `--resume`: when set, checkpoints
already recorded in `--paper-store` (detected via the latest `as_of_time`
any one representative security has a persisted prediction for -- every
security is processed uniformly every cycle, so one security's history
is a faithful proxy) are skipped rather than reprocessed, and
`PaperRunnerState.value_history` is reconstructed from real, already-
persisted `RiskCheckedPosition.risk_state.portfolio_value` records --
never guessed or gap-filled.

`PaperTradingSession.restore()` -- an existing, already-tested classmethod
this script had never called -- is now used unconditionally instead of
the plain constructor (it replays whatever the store already has, which
is nothing on a fresh store, so this is strictly more correct in every
case, not only under `--resume`).

## Decision 2 -- the real bug `--resume`'s own tests surfaced

Building `--resume`'s tests (re-invoking the script against the same
`--paper-store`, something no prior test had ever done) immediately hit
`_duckdb.ConstraintException: Duplicate key "prediction_id: PRED-000001"`.
The cause: `DriftPredictor`/`RegimeDetector`/`BaselineRuleDecisionAgent`/
`DeterministicPositionSizer`/`DeterministicPortfolioRiskEngine` each
allocate their own record IDs from a private counter that starts at 1
in every fresh process -- and every one of the five repositories
enforces a real PRIMARY KEY constraint on that ID (not merely on
`natural_key`, which is only checked first as a content-based dedup
before the ID-keyed INSERT). **This was not a `--resume`-specific bug --
it means this script (and anything built on `orchestration.paper_runner`
the same way) was never actually safe to invoke a second time against a
non-empty `--paper-store`, resume or not**, since even genuinely new,
non-overlapping checkpoints would eventually collide with an ID a prior
invocation already used.

Fixed at the source: each of the five classes above gained an optional,
keyword-only `starting_id`/`starting_composite_id` (+`starting_observation_id`
for `RegimeDetector`, whose `record_composite` also persists each axis's
own `RegimeObservation` in a SEPARATE, separately primary-keyed table --
both of its counters needed seeding, not just the composite's) parameter,
default `1` (preserves every existing caller's behavior exactly -- all
206 existing tests across `tests/predict`/`tests/regime`/`tests/decision`/
`tests/risk` passed unchanged). `run_paper_trading_cycle.py` now queries
each repository's own real persisted max ID (across every security --
these counters are shared per cycle, not per-security, so checking only
one security's records would undercount) and seeds every component with
it, unconditionally -- same "always correct, not only under --resume"
choice as `restore()`.

## What this does NOT fix

`orchestration.live_runner`'s own components would hit the identical
bug if invoked a second time against a persisted store with the same
five component classes -- not fixed here (Live has no equivalent
"resume a CLI" concept yet, and doing so touches real-money safety
review this session did not undertake). A future Live-side scheduler
would need the same `starting_id` seeding this ADR added.

## Tests

4 new in `tests/orchestration/test_run_paper_trading_cycle_cli.py`
(`TestResume`): resuming skips exactly the already-processed
checkpoints and never double-counts persisted predictions; resuming a
fully-already-done range reports 0 new checkpoints without crashing;
`value_history` reconstructs across invocations (sum, never reset).
Full suite: 2347 passed (up from 2344).
