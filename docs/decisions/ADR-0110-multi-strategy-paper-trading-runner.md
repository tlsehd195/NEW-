# ADR-0110: Multi-strategy Paper Trading runner

**Status:** Accepted
**Session:** 36 (continued)

## Context

Earlier this session, answering the account owner's own question
("지금까지 쌓은 B&H 트랙레코드가 나중에 다른 전략에 어떻게 적용되는지"),
this session established: `broker.paper.session.PaperTradingSession`
is a one-account-per-strategy structure, no strategy's track record
transfers to another, and running more than one strategy in Paper
Trading would need a new multi-session orchestrator that did not yet
exist. That answer was recorded as a future-work note in
`docs/PROJECT_STATUS.md` ("45개 전략을 한 번에 페이퍼 트레이딩으로 돌릴
수 있는 멀티 전략 러너를 나중에 설계·구현하기로 함"). The account owner
then asked to build it ("멀티 전략 ㄱㄱ").

A second question from the same conversation ("Tiingo 한도 때문에 안
되는거 아니야?") was already answered honestly then (paper trading reads
an already-ingested local DuckDB catalog, never calling Tiingo itself)
-- this ADR's design makes that answer concretely true in code, not
just asserted: the catalog is fetched once and shared read-only across
every strategy this runner drives.

**What this is NOT**: none of the 45 factor-research candidates
(`strategy_research.factor_scores`) are wired into this runner. RULE
0.8 forbids selecting or constructing a strategy after seeing any
result, and none of the 45 has a real validated walk-forward result yet
(`docs/research/STRATEGY-VALIDATION-REPORT.md`'s own "Outstanding real
results not yet received" list, unchanged by this ADR). This is pure
infrastructure, buildable and buildable-tested independent of that
open question, exactly as the future-work note said.

**Investigating the actual current architecture surfaced one thing
worth being transparent about**: the account owner had been told
earlier this session that the live daily GitHub Actions Paper Trading
schedule runs pure Buy & Hold. Re-reading `scripts/run_paper_trading_
cycle.py` end to end for this task shows that is not quite right -- the
script that actually runs daily calls `orchestration.paper_runner.
run_cycle` with `DriftPredictor` + `BaselineRuleDecisionAgent` +
`DeterministicPositionSizer` + `DeterministicPortfolioRiskEngine`, a
real (if simple, rule-based) per-checkpoint decision pipeline, not a
buy-once-and-never-trade-again allocation. `broker.paper.us_longterm_
runner.run_buy_and_hold_paper_session` -- the actual pure Buy & Hold
allocator -- exists and is fully built, but was never wired into the
daily schedule at all before this ADR. This is corrected going forward
(both are now named, runnable strategies, see Decision below) and
disclosed here rather than left silently as it was.

## Decision

**`orchestration.paper_strategies`** (new module): a registry,
`STRATEGIES: dict[str, PaperStrategySpec]`, of exactly three strategies
-- all built ONLY from components this project already had, already
tested, already used elsewhere for exactly this purpose (no new
forecasting/decision logic invented for this ADR):

1. `baseline_rule` -- `DriftPredictor` + `BaselineRuleDecisionAgent` +
   `DeterministicPositionSizer` + `DeterministicPortfolioRiskEngine`.
   The exact configuration `run_paper_trading_cycle.py` ran inline
   before this ADR; the one strategy actually live in the daily
   schedule. Behavior UNCHANGED by this ADR (see Tests).
2. `random_walk_baseline` -- identical to `baseline_rule` except
   `RandomWalkPredictor` (`predict.predictor`'s own documented
   "null-hypothesis baseline: no forecastable drift", already built,
   already used as Prediction's own benchmark elsewhere) replaces
   `DriftPredictor`. A real statistical control: any strategy that
   cannot beat this one's own real paper-trading track record is not
   adding forecasting value.
3. `buy_and_hold` -- `broker.paper.us_longterm_runner.run_buy_and_hold_
   paper_session`, wired to a strategy name for the first time (see
   Context).

Two execution shapes, `PaperStrategyKind.RUN_CYCLE` (a per-checkpoint
`run_cycle` loop) and `PaperStrategyKind.BUY_AND_HOLD` (one allocation
on the first checkpoint, then per-checkpoint mark-to-market only) are
kept explicitly separate rather than forced into one interface --
`buy_and_hold` has no `Predictor`/`DecisionAgent` at all, and unifying
would either fabricate one or strip `run_cycle`'s own real Decision
pipeline down to fit a shape it does not have.

`orchestration.paper_runner.compute_portfolio_snapshot` (new, public):
a thin wrapper around the same mark-to-market snapshot `run_cycle`
itself already takes every checkpoint (`_portfolio_view`, unchanged) --
`buy_and_hold`'s own per-checkpoint valuation loop needed exactly this,
not a second, competing implementation.

**`scripts/run_multi_strategy_paper_trading_cycle.py`** (new CLI): runs
N named strategies (`--strategies`, comma-separated, default = every
registered name) over one `[--start, --end]` window against ONE shared,
read-once market-data catalog. Each strategy gets its own subdirectory
under `--paper-store-root/<name>/` -- own `PaperTradingSession`, own
cash/positions/orders/fills, and (RUN_CYCLE-kind only) own Prediction/
Regime/Decision/Sizing/Risk/Trade-Journal repositories. `--resume` is
safe per strategy independently (a RUN_CYCLE strategy's own last-
processed checkpoint; a BUY_AND_HOLD strategy's own "has this store's
order repository already recorded the one buy" check -- idempotent,
never a second buy).

`scripts/run_paper_trading_cycle.py` itself is refactored, NOT
replaced: its own inline component construction now calls
`orchestration.paper_strategies.build_run_cycle_components("baseline_
rule", ...)` instead of constructing the same five objects inline --
still the only script the daily GitHub Actions schedule invokes,
unchanged CLI, unchanged behavior (see Tests).

## What this does NOT do

Does not add any factor-derived strategy to `STRATEGIES` (see Context
-- RULE 0.8). Does not change `.github/workflows/paper_trading_cycle.yml`
-- the daily schedule still calls the single-strategy script with its
one `baseline_rule` configuration; wiring the new multi-strategy script
into a real schedule is a separate decision the account owner has not
asked for yet. Does not give `buy_and_hold` the same rich per-checkpoint
persistence (Prediction/Regime/Decision/Sizing/Risk repositories) that
RUN_CYCLE strategies get -- it never calls a `Predictor`/`DecisionAgent`
at all after its one initial allocation, so there is nothing of that
kind to persist; its own value-history is recomputed fresh each
invocation (cheap, read-only, safe) rather than persisted, since it
submits no orders whose duplication would need preventing beyond the
one already-guarded initial buy. Does not change `RiskConfig`/position-
sizing defaults for any strategy -- the same risk-policy flags apply
uniformly across every strategy this run covers, matching this
project's existing "risk policy is a project-level decision, not a
per-strategy one" precedent (`LIVE-RISK-POLICY.md`).

## Tests

`tests/orchestration/test_paper_strategies.py` (11 tests): registry
contents, `build_run_cycle_components` per name, starting-ID
independence, fail-closed on an unregistered or BUY_AND_HOLD-kind name.
`tests/orchestration/test_run_multi_strategy_paper_trading_cycle_cli.py`
(7 tests, end to end against a seeded local DuckDB catalog, no network):
unknown-strategy CLI failure; all three registered strategies producing
genuinely isolated on-disk stores; `baseline_rule` and `random_walk_
baseline` producing DIFFERENT order counts over the same synthetic
price series (proving they are not secretly identical); `buy_and_hold`
buying exactly once and never again across a `--resume`'d second
invocation; and -- the regression-safety proof for the
`run_paper_trading_cycle.py` refactor -- running `baseline_rule` alone
through the new multi-strategy script over identical inputs produces
IDENTICAL `checkpoints_run`/`total_orders_submitted`/
`total_orders_with_a_fill`/`final_cash`/`final_positions` to the
pre-existing single-strategy script's own direct output.
`tests/orchestration/test_run_paper_trading_cycle_cli.py`'s own 10
pre-existing tests re-run unchanged and still pass, confirming the
refactor changed nothing observable about that script. Full suite
re-run, all tests pass.
