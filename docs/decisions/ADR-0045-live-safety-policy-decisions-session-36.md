# ADR-0045: Three Live-safety policy decisions -- max_turnover blocking, cancel-on-kill-switch automation, CANDIDATE-evidence gate

**Status:** Accepted

## Context

Asked how far the project's infrastructure/system-building axis was
from "100%" (as distinct from the separate, still-0% axis of "found a
validated profitable strategy"), the assistant identified a short list
of genuinely open items, three of which were structural financial/risk
policy decisions this project's own constitution (`PROJECT_MASTER_
PLAN.md` section 1.6, "AI와 금융 결정의 분리") forbids the AI from
making unilaterally. The user was asked directly and, for two of the
three, explicitly delegated the choice to the assistant's own
recommendation; for the third, gave an explicit instruction. This ADR
records all three decisions and their implementation together, since
they were decided in the same exchange and touch the same safety-gate
code paths.

## Decision 1 -- `RiskConfig.max_turnover=None` now structurally blocks Live, closing the Phase 22 asymmetry

**User's choice**: delegated to the assistant's recommendation
("이것도 모르니까 너가 선택해").

**Recommendation made and adopted**: extend Phase 22's Option B
("`None` on a required Live risk limit is itself a fail-closed
condition, not just \"no automatic circuit breaker\"") from
`max_daily_loss`/`max_order_frequency_per_hour` to `max_turnover` --
the one risk limit Phase 22 deliberately left out because the safety
gate had no structural visibility into `RiskConfig` at all, not
because a different answer was intended.

**Implementation**: `broker.live.safety_gate.SafetyGateContext` gains
a new field, `max_turnover: Optional[float]` -- a plain value, **not**
the whole `RiskConfig` object. `broker.live.safety_gate` must never
import `risk.config` at all
(`tests/broker/live/test_live_boundary.py::
TestNoRiskLimitOrModelApprovalMutation::test_no_risk_config_import`
enforces this structurally by AST scan, discovered when an earlier
draft of this change imported `RiskConfig` directly and the test
correctly failed). The caller sources the value from their own
`RiskConfig.max_turnover` before constructing the context -- the gate
itself only ever sees a primitive `float | None`.

```python
if context.max_turnover is None:
    failed.append("risk_limit_not_configured_max_turnover")
```

3 new regression tests
(`tests/broker/live/test_live_safety_gate.py::
TestMaxTurnoverNoneSemanticsOptionB`), mirroring the 5 that already
covered `max_daily_loss`/`max_order_frequency_per_hour`. 6 existing
test call sites across 5 test files plus the shared
`make_passing_gate_context` fixture updated to supply the new required
field.

## Decision 2 -- cancel-on-kill-switch automation

**User's choice**: explicit ("자동화 진행").

**A correction found while investigating this decision**: every prior
citation of "ADR-0022 decision 8" as the source of the "cancel-on-
shutdown is a deliberate non-automatic choice" framing (repeated across
`PRODUCTION-READINESS-MATRIX.md`, `PROJECT_STATUS.md`,
`TOSS-API-GAP-ANALYSIS.md`, and the PHASE-17 spec) was **wrong** --
`ADR-0022-live-trading.md`'s actual decision 8 is about how a
submission exception maps to `UNKNOWN` order status, and the ADR never
mentions cancel-on-shutdown anywhere. This citation had been copied
forward across multiple documents without ever being verified against
the ADR's real content. There was, in fact, no prior recorded design
rationale for the non-automatic choice beyond the general Phase 16
principle that automated cancellation is exactly the kind of
consequential action requiring deliberate design, not a repeated
citation to a decision that was never actually made.

**Design**: distinguished, on inspection of the actual runbook, between
two different lifecycle events that had been conflated in the user's
own question:

- **General, operator-initiated shutdown** (end of day, planned
  maintenance) -- remains manual. `broker.live.session.
  run_shutdown_checks` is unchanged; deciding whether to cancel each
  open order in this case is still a human call, since a planned
  shutdown is not itself evidence anything is wrong.
- **An automatic kill-switch engagement** -- exactly the emergency
  condition (`broker.live.kill_switch.evaluate_kill_switch_triggers`
  firing on unhealthy broker/risk/monitoring/data state, a breached
  daily-loss limit, or abnormal order frequency) where leaving working
  orders unmanaged while waiting for a human is the wrong default. This
  is where automation was implemented.

**Implementation** (`src/broker/live/session.py`):
`LiveTradingConfig.auto_cancel_on_kill_switch: bool = True` (new
field -- effective only once `live_trading_enabled` is separately
opted into, so the default does not itself make the system less
inert). `LiveTradingSession.engage_kill_switch` now, after recording
the `KillSwitchEvent`, attempts `adapter.cancel_order` for every order
this session does not already know to be `CLOSED`
(`broker.enums.is_closed_status`) -- including `UNKNOWN`-status orders
(a disconnected submission may or may not have gone through;
attempting cancellation is the fail-safe response, not skipping it).
Each attempt's outcome (`OrderCancellationOutcome`: `client_order_id`,
`cancelled`, `broker_status`, `error`) is recorded, never inferred from
"no exception was raised" -- mirrors `submit`'s own refusal to treat
absence-of-error as presence-of-success. `engage_kill_switch`'s return
type changes from the bare `KillSwitchEvent` to
`KillSwitchEngagementResult` (event + cancellation outcomes) -- a
breaking change with exactly one call site in the whole repository
(its own test), which did not use the return value.

**Explicitly not a substitute for reconciliation**: a cancel attempt
can itself fail or return `UNKNOWN`, and even a successful
cancellation does not confirm the broker's own book matches this
session's -- `docs/operations/LIVE-TRADING-RUNBOOK.md` still requires
running the full Reconciliation section after any kill-switch
engagement, unchanged.

5 new tests (`tests/broker/live/test_live_session.py::
TestCancelOnKillSwitch`): an open (`PARTIAL_FILLED`) order is
cancelled and the outcome recorded correctly; a filled order is never
touched; `auto_cancel_on_kill_switch=False` leaves orders untouched;
an `UNKNOWN`-status order is still attempted (and its failure recorded
honestly when the simulated broker is unavailable).

## Decision 3 -- CANDIDATE-level evidence review required before Live activation

**User's choice**: delegated to the assistant's recommendation ("나는
잘 모르겠으니까 너가 추천하는 방법으로 갈게").

**Recommendation made and adopted**: require it as a **necessary, not
sufficient**, precondition for Live activation, motivated directly by
a real observed case from the same session -- `leverage` had just
reached this project's `CANDIDATE` evidence level (all three
walk-forward gates cleared: 60% positive folds, PBO=0.39<0.5,
DSR=0.9674>=0.95) while producing the worst held-out TEST result this
project has ever recorded (-26.43% net, ADR-0043 Decision 7). This is
direct, real evidence that reaching CANDIDATE alone is not a safe
signal to skip past without independently reviewing what actually
happened in the TEST window -- and it is exactly the kind of
in-the-moment temptation ("the tool says CANDIDATE, that's good
enough") a purely discretionary, case-by-case human judgment call is
most likely to miss under time pressure. A structural checkpoint
closes that gap without claiming to solve the underlying problem
(finding a genuinely good strategy) -- it only makes it harder to
accidentally activate Live trading with an unreviewed CANDIDATE.

**Implementation** (`src/broker/live/approval.py`):
`LiveActivationApproval` gains a new required field,
`strategy_evidence_reviewed: bool`, enforced in `__post_init__`
exactly like the existing `checklist_completed` field already is (must
be `True` or the object fails to construct). This is a **structural
attestation, not a computational verification** -- the same category
of mechanism `checklist_completed` and `confirmation_token` already
are in this codebase: it does not itself prove a human reviewed a
CANDIDATE's TEST result, but it makes skipping that review require
deliberately setting the field to `True` while lying, rather than
merely forgetting a step. Building an automated mechanism that reads
`strategy_research.evidence.EvidenceLevel` from a persisted result and
verifies it before allowing approval construction would be materially
more engineering (a persistence/lookup layer this project has not
built) and was not attempted here -- this is an honestly-scoped,
precedent-consistent gate, not a claim of full automated enforcement.

`LiveActivationApproval` still has exactly one family of constructors
in the whole repository (its own tests) -- re-verified by the existing
AST scan
(`tests/broker/live/test_live_boundary.py::TestActivationApprovalIsHumanOnly`),
unaffected by this change.

3 new/updated tests
(`tests/broker/live/test_live_approval.py::TestStrategyEvidenceMustBeReviewed`,
2 new; every other existing construction call site updated to supply
the new required field). `make_approval` (`tests/broker/
live_helpers.py`) defaults `strategy_evidence_reviewed=True` so every
other test's "passing" fixture keeps working unchanged.

## Consequences

- `SafetyGateContext`, `LiveTradingConfig`, and `LiveActivationApproval`
  each gained one new required/defaulted field -- all three are
  additive to existing dataclasses, no field removed or renamed.
  `LiveTradingSession.engage_kill_switch`'s return type changed
  (`KillSwitchEvent` -> `KillSwitchEngagementResult`), the one
  genuinely breaking signature change in this ADR, with a single,
  updated call site.
- Live activation is now blocked on three real, previously-open
  conditions it was not blocked on before this session: an unset
  `max_turnover`, and (once a strategy is actually being activated) an
  unreviewed evidence attestation. Toss's own capability gap
  (`ACCOUNT_BALANCE`/`POSITIONS`/`ORDER_STATUS`/`CANCEL_ORDER` still
  `CapabilityStatus.UNKNOWN`, pending real operational verification)
  remains the independently-blocking reason Live cannot activate today
  regardless of any of these three decisions.
- None of these three decisions required, and none performed, any
  ratification of an actual numeric risk-limit value -- `max_daily_loss`,
  `max_turnover`, and `max_order_frequency_per_hour` all remain `None`
  by `LiveTradingConfig`'s own class-level default, per
  `LIVE-RISK-POLICY.md`'s still-open numeric-value `DECISION REQUIRED`.
  This ADR resolves *whether* an unset limit blocks Live, not *what the
  limit should be*.
- Full suite: 2047 -> see this session's commit for the updated count
  (all new/updated tests pass; no pre-existing test's behavior was
  changed except the required-field additions needed to keep
  constructing valid objects).
