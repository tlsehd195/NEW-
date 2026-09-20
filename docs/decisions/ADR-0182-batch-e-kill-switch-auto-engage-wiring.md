# ADR-0182: Wire real kill-switch auto-engage into live_runner.run_cycle (audit Batch E)

**Status:** Accepted
**Date:** 2026-09-20
**Deciders:** Claude Code (session continued), account owner (asked to
process every remaining P2/P3 finding from the independent audit
report, in batches; this is Batch E -- kill switch production wiring)

## Context

The independent audit's Step 9 (`src/broker/live/`) found: "Kill
switch: engage 기계+트리거는 완전 구축·테스트되었으나... **프로덕션
배선 0 -- 자동 engage가 존재하지 않고 실 live 실행에서 일일손실/빈도/
건강 트리거는 발동 안 함. 문서의 중심 '자동 중단' 주장은 실제 실행에서
거짓.**" Confirmed real, directly: `broker.live.kill_switch.
evaluate_kill_switch_triggers`/`LiveTradingSession.engage_kill_switch`
are both real, deterministic, and already covered by their own tests
(`tests/broker/live/test_live_kill_switch.py`) -- but a repo-wide grep
found zero callers of `evaluate_kill_switch_triggers` outside its own
test file, and `orchestration.live_runner.run_cycle` never called
`engage_kill_switch` either. `PROJECT_MASTER_PLAN.md` section 12.1's
"다음 상황에서는 신규 주문을 자동으로 중단할 수 있어야 한다" was
therefore never actually true of any real execution path.

This is the same "mechanism exists but is wired to nothing" pattern
already found and fixed once this session for a different subsystem
(ADR-0176, the point-in-time universe) -- and, like that fix and
Batch C's `live_runner.py` turnover finding, this specific gap sits
entirely inside the LIVE trading path, which has zero production
callers today (no real live driver exists in `src/`/`scripts/`,
independently confirmed earlier this session). Wiring it now has no
observable production effect today, but closes the gap for whichever
future session first builds a real live driver -- leaving it open
would mean that driver inherits a documented "automatic circuit
breaker" that silently does nothing, exactly the trap this audit step
exists to catch.

## Decision

`orchestration.live_runner.run_cycle` gained a new, entirely optional
`kill_switch_context: Optional[KillSwitchTriggerContext] = None`
parameter (default `None` preserves this function's exact pre-existing
behavior for every current caller/test). When supplied, it is treated
as the BASE `KillSwitchTriggerContext` for this cycle -- `as_of_time`,
`config`, `account_state_known`, `position_state_known` are always
overridden by `run_cycle` itself first, mirroring exactly how
`gate_context`'s own four always-overridden fields already work (both
reuse the same underlying fact: reaching this point already means
`_live_portfolio_view` obtained a real account/positions snapshot).
`broker_health`/`risk_health`/`monitoring_pipeline_health`/
`data_health`/`daily_loss`/`orders_in_last_hour` remain entirely the
caller's responsibility -- `run_cycle` still performs no Monitoring or
broker health query itself, consistent with every other opt-in
parameter this function already has (ADR-0074's `risk_health`/
`model_state_valid`/`configuration_integrity_valid` pattern).

If `evaluate_kill_switch_triggers` returns a trigger reason and the
kill switch is not already engaged, `session.engage_kill_switch` is
called BEFORE this cycle's own `security_ids` loop runs. No other
change to the loop itself was needed: `kill_switch_engaged` (already
read once, right after, and already used to override every order's own
gate context) is re-read AFTER the auto-engage attempt, so every order
this cycle is correctly gated exactly as if the kill switch had
already been engaged before the call started -- the exact same
mechanism `TestGateContextDerivedFieldsOverrideCallerPlaceholders`
already proves works for a kill switch engaged by some earlier,
external means.

## Consequences

### Positive
- Closes a real, independently-confirmed gap between this project's
  own documented safety claim and its actual code -- the next session
  that builds a real live driver can now genuinely rely on the
  auto-engage mechanism working, rather than discovering it silently
  does nothing.
- Zero risk to any existing caller: the new parameter is opt-in,
  defaults to `None`, and every existing test in
  `tests/orchestration/test_live_runner.py` passed unmodified.
- Reuses the exact override pattern (`gate_context`) this function
  already established for the same underlying reason -- no new design
  vocabulary introduced.

### Negative / Trade-offs
- Has zero observable effect in production today, since nothing in
  `src/`/`scripts/` currently constructs a `LiveTradingSession` or
  calls `live_runner.run_cycle` at all (confirmed structurally
  unreachable, same finding as Batch C's `live_runner.py` turnover
  item and this session's own earlier independent P0 audit
  cross-check). This ADR closes the gap in the code path that WOULD
  matter, not a gap affecting any real, currently-running system.
- Still requires a real caller to actually compute and supply
  `broker_health`/`risk_health`/`monitoring_pipeline_health`/
  `data_health`/`daily_loss`/`orders_in_last_hour` from real Monitoring/
  broker data -- this ADR does not build that caller (that is the same,
  larger "build a real live driver" undertaking Batch C's ADR-0180
  already declined to attempt unilaterally). A future live driver must
  still assemble a real `KillSwitchTriggerContext` from real data before
  this wiring does anything.
- `daily_loss`/`orders_in_last_hour`-based triggers specifically remain
  untested end-to-end through `run_cycle` (only the `broker_health`
  trigger path is exercised by the new tests) -- `evaluate_kill_switch_
  triggers` itself already has its own direct unit coverage for every
  trigger condition (`tests/broker/live/test_live_kill_switch.py`), so
  this is a coverage gap in the NEW wiring specifically, not in the
  underlying trigger logic.

## Tests

`tests/orchestration/test_live_runner.py`'s new `TestKillSwitchAutoEngage`
class (4 tests): omitting `kill_switch_context` never auto-engages
(backward compatibility); a fully-healthy context does not auto-engage;
a real trigger condition (`broker_health=UNAVAILABLE`) auto-engages
BEFORE this same cycle's own order submission, correctly blocking it;
an already-engaged kill switch is never re-evaluated. Verified the
core positive-trigger test is a real regression guard by reverting the
`live_runner.py` wiring and confirming it fails first (`session.
is_kill_switch_engaged()` stayed `False`) before restoring the fix.

`tests/orchestration/`: 145 passed. Full suite: 3504 passed.

## Status of Implementation at Time of This ADR

Code and tests complete. This is Batch E of a larger, explicitly-
requested pass through every remaining P2/P3 finding in the
independent audit report; Batch F (monitoring package production
wiring) is next.
