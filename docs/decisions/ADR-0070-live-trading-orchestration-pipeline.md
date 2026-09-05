# ADR-0070: `orchestration.live_runner.run_cycle`, the Live-side equivalent of `paper_runner`

**Status:** Accepted
**Session:** 36 (continued)

## Context

After ADR-0067/ADR-0068 validated `orchestration.paper_runner.run_cycle`
against real data (both without and with sector/notional limits), the
user confirmed the agreed sequencing: "live 쪽 동등 파이프라인은 c 한
후에" (the Live-side equivalent pipeline comes after C). This ADR builds
that equivalent.

## Two structural differences from Paper, both forced by what Live actually is

1. **Portfolio state comes from the broker, not a local ledger.**
   `PaperTradingSession.account_summary()` has no Live counterpart --
   `LiveTradingSession` has no such method, because a real account's
   cash/positions genuinely live at the broker. `_live_portfolio_view`
   reads `session.adapter.get_account()`/`get_positions()` directly and
   **raises** rather than fabricating a $0 balance when the broker
   reports the account unavailable (`BrokerAccountSnapshot.available=False`)
   -- a `PortfolioView` this module hands to Decision/Sizing/Risk must
   never encode a false "resting on $0."

2. **`SafetyGateContext` is a REQUIRED, caller-supplied base parameter --
   this module never assembles one.** Before writing this module, a
   repo-wide check found that NOTHING in `src/` currently computes real
   values for most of `evaluate_safety_gate`'s inputs (`risk_health`/
   `account_state_known`/`position_state_known`/`model_state_valid`/
   `configuration_integrity_valid`/`max_turnover`/`approval`) -- every
   existing caller is a test fixture (`tests/broker/live_helpers.py::
   make_passing_gate_context`) that hardcodes a "passing" context.
   Building real, honest computations for each of those fields (wiring
   `monitoring.health`'s existing evaluators, deciding what
   "model_state_valid" means against the Candidate approval boundary
   this project deliberately keeps automation-free) is real, separate,
   safety-critical work this module does not attempt -- the same "found
   a bigger gap, documented it honestly rather than fabricating a fix"
   precedent ADR-0067 already set for `value_history`. `run_cycle` will
   neither build a `SafetyGateContext` from scratch nor accept `None`
   for it.

   One field IS this module's own to set: `order_validation_status`.
   `tests/integration/test_live_trading_lineage.py` (the one existing
   real example of assembling a `SafetyGateContext`) populates it from
   that specific order's own `build_validated_order(...).status` -- a
   value only known once Risk/Validation has actually run for that
   security, and it differs security to security within one cycle.
   `run_cycle` derives the context handed to `session.submit()` via
   `dataclasses.replace(gate_context, order_validation_status=
   validation.status, as_of_time=as_of_time)` -- every other field
   passes through exactly as the caller supplied it.

## No cross-import with Paper

`orchestration.live_runner` does not import `broker.paper.*`,
`orchestration.paper_runner`, or `broker.toss.*`, and does not
instantiate `PaperTradingSession`/`TossBrokerAdapter` -- `broker.paper`/
`broker.live` remain two structurally separate implementations by
design (`tests/broker/live/test_live_boundary.py`), and this module
follows the same discipline even though `orchestration` itself sits
outside that import restriction. `LiveRunnerState`/`LiveCycleOutcome`
duplicate `PaperRunnerState`/`CycleOutcome`'s shape rather than
importing them, for the same reason.

## What this is NOT

Not "a real, running Trading Engine loop" (no timer/scheduler) -- same
scope boundary as `paper_runner`. Not connected to a real broker --
every test uses `broker.mock.MockBrokerAdapter`, the only `BrokerAdapter`
this repository's own tests may ever call. Not a resolution of the
`SafetyGateContext` gap described above -- that remains open, and no
code anywhere may call this module against `broker.toss.adapter.
TossBrokerAdapter` with a real, honestly-computed `SafetyGateContext`
until that separate work is done.

## Tests

`tests/orchestration/test_live_runner.py` (11 tests): full-chain
lineage, a warranted BUY actually submits and fills via
`MockBrokerAdapter`, a second cycle sees the first's real broker-side
fill, sector limit REJECTs without a mapping and passes with one,
`value_history` accumulates and unlocks `max_drawdown`, all five
repositories persist, an unavailable broker account raises rather than
fabricating $0 cash, and -- the design's central guarantee -- a
caller's deliberately WRONG placeholder `order_validation_status` is
proven overridden by the real per-security result before reaching
`session.submit()`.

`tests/orchestration/test_live_orchestration_boundary.py` (5 tests, AST-
level, mirroring `test_orchestration_boundary.py`): no `broker.paper`/
`orchestration.paper_runner`/`broker.toss` import, no
`PaperTradingSession`/`TossBrokerAdapter` instantiation, no
`CandidateModelStatus.APPROVED`/`DEPLOYED` reference, and this module
never constructs a `SafetyGateContext` itself (only `dataclasses.replace`s
a caller-supplied one).

Full suite: 2331 passed (up from 2315).
