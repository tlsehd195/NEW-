# ADR-0185: Correct the 18 documentation-vs-code mismatches (audit Batch H)

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Claude Code (session continued), account owner (asked to
process every remaining P2/P3 finding from the independent audit
report, in batches; this is Batch H -- the §6 "문서 주장 vs 코드/실행
사실 차이" table's 18 items)

## Context

The independent audit's §6 recorded 18 places where a document's claim
diverged from what the code or a real execution actually does. Per the
audit's own evidence standard ("README, ADR, 상태 문서... 그 자체로
증거가 아니다"), each of the 18 items was re-verified directly against
current code before any doc was touched, since several sessions' worth
of work had landed on `main` since the audit's own commit SHA
(`8090748c`) -- some items had already been fixed by earlier work in
this same session's batch pass (A-G), and at least one correction
attempted mid-batch turned out to cite the wrong mechanism and had to
be redone (see item 8 below).

## Per-item disposition

1. **Kill switch "auto-called" claim** (RUNBOOK/PRODUCTION-READINESS-MATRIX) --
   was false when written (zero production callers of
   `evaluate_kill_switch_triggers`); Batch E (ADR-0182) closed the
   mechanism itself. Corrected both docs to state the mechanism is now
   real but still has zero observable production effect, since no real
   Live driver exists to supply a `KillSwitchTriggerContext`.
2. **LIVE-RISK-POLICY "independently-blocking" Toss capability gap** --
   corrected: the gate's broker-capability check only fails for
   capabilities the caller's own `required_capabilities` actually
   lists; a hypothetical caller requiring only `MARKET_ORDER` (already
   `ENABLED`) would not be blocked by this condition. No real caller
   exists yet to make that choice, which is why Live stays blocked
   today -- not a structural guarantee independent of caller choice.
3. **`reconciliation.py`'s "operator records a resolution" claim** --
   no such method exists anywhere in the codebase. Corrected to
   describe the real mechanism: a later `reconcile_order` call
   returning `MATCHED` (requires the broker's real state and internal
   expectation to actually converge), or a session restart that
   discards `_internal_status` entirely rather than resolving it.
4. **README/PHASE-16 spec "11 conditions"** -- actual count from
   `src/broker/live/safety_gate.py`'s own `failed.append(...)` call
   sites is 15. Corrected both locations. (The same stale "11개 조건"
   also appears twice in `docs/PROJECT_STATUS.md` -- left untouched;
   see item 16 below for why.)
5. **`.env.example` decorative variables** -- `APP_ENV`/`LIVE_TRADING`/
   `ALERT_WEBHOOK_URL` are read by no code anywhere in `src/`/`scripts/`
   (confirmed by grep); the real environment/Live switches are
   `BrokerConfig.execution_mode`/`LiveTradingConfig.live_trading_enabled`
   (caller-supplied dataclass fields, not env vars), and the real,
   actually-used alert channel is `DISCORD_WEBHOOK_URL`
   (`scripts/send_discord_notification.py`,
   `paper_trading_cycle.yml`'s own secret). Added explanatory notes and
   the missing `DISCORD_WEBHOOK_URL=` line.
6. **LIVE-RISK-POLICY row #5 (sector limit) "not yet code-applied"** --
   understated Paper production: `paper_trading_cycle.yml` has passed
   `--max-sector-weight 0.25` on every real daily run since ADR-0080.
   Corrected to distinguish "not baked into the bare default config"
   (still true) from "not applied in production" (false).
7. **PHASE-13 "UNKNOWN-capability operations raise `BrokerCapabilityError`"** --
   accurate for Phase 13's original state, stale since Phase 21
   (ADR-0027) implemented all four against real Tier 1 endpoints; none
   of them raise that error today. Appended a correction to the Phase
   13 spec. Also fixed `broker/protocol.py`'s docstring, which listed
   only `MockBrokerAdapter`/`TossBrokerAdapter` as Protocol
   implementations, omitting `PaperBrokerAdapter`.
8. **`run_learning_cycle.py`/PRODUCTION-READINESS-MATRIX "features always None"** --
   stale since ADR-0141 (Session 38). **First correction attempt in
   this batch cited the wrong mechanism** (`OrderIntent.features` /
   ADR-0161's backtest-`Strategy` fixes) before re-tracing the real
   production path and finding `orchestration.paper_runner`'s actual
   decision path (`decision.agent.DecisionAgent`) never goes through an
   `OrderIntent`-producing `Strategy` at all -- the real fix is
   `paper_runner.py`'s own `_decision_features(prediction, regime)`
   helper (ADR-0141), independent of `OrderIntent`/`Strategy` entirely.
   Redone with the correct citation in both files.
9. **PHASE-14 spec "Nine collectors"** -- actual count is ten
   (`collect_account`, added Phase 17, was missing from the list).
   Corrected.
10. **PHASE-14/17/PRODUCTION-READINESS-MATRIX "monitoring wired/PASS"** --
    was false when written (zero production callers of any collector or
    repository, confirmed by grep); Batch F (ADR-0183) closed it for
    `prediction`/`decision`/`sizing`/`risk`/`account` only. Corrected
    all three documents to state the real, bounded scope: those five
    components are now genuinely wired via
    `scripts/run_monitoring_sweep.py`; `broker`/`data_quality`/
    `ai_gateway`/`learning`/`model_evolution`/drift remain unwired, each
    for the specific reason Batch F's own script docstring already
    disclosed.
11. **`data_quality_rescan.yml`/ADR-0145 "protects the Learning Cycle"** --
    false causal claim: `run_learning_cycle.py` never reads the
    market-data catalog (`--paper-store` only) and never calls
    `get_bars()`, so this rescan's timing has no effect on it. Corrected
    the workflow comment, ADR-0145, and a test docstring that repeated
    the same misconception -- the real (still valid) reason for the
    Saturday-before-Saturday ordering is protecting the FOLLOWING WEEK's
    Paper Trading cycles, not the Learning Cycle.
12. **Tier 1 vs. `ENABLED` inconsistency** (`MARKET_ORDER` is `ENABLED`
    on Tier 2 evidence while newer, Tier-1-documented capabilities stay
    `UNKNOWN`) -- confirmed real: `MARKET_ORDER` was marked `ENABLED`
    in Phase 13, before Phase 21 established the stricter "operationally
    verified, not just documented" bar for `ENABLED`, and has never been
    revisited under it. **Deliberately not changed here** -- flipping a
    Live safety-gate input is a production-safety judgment call for the
    account owner, matching this project's own "DECISION REQUIRED"
    convention (`LIVE-RISK-POLICY.md`'s risk-limit items), not something
    to silently change while fixing documentation. Flagged in
    `TOSS-API-GAP-ANALYSIS.md` as a DECISION REQUIRED item instead.
13. **`toss-openapi-spec-v1.2.14.json` "0-path placeholder"** -- already
    accurately disclosed (`TOSS-API-GAP-ANALYSIS.md` already states this
    file is a placeholder and the real ~80KB spec was read directly from
    the conversation transcript, never mechanically serialized). No
    action needed.
14. **ADR-0167 future_dated bug "still present"** -- already fixed by
    Batch A (ADR-0178) earlier in this same session's batch pass;
    confirmed by reading the current `reporting_as_of_time` fix in
    `ingest_real_market_data.py`. No action needed.
15. **2.4-year Paper track record continuity implication** -- the
    underlying facts (1,485 pre-ADR-0154 same-bar fills, only 11 trades
    journaled, 8 status-missing orders) are a data/tooling problem, not
    a documentation claim to correct here -- explicitly deferred to
    Batch I (거래 저널 잔여), which owns the same-execution_time
    partial-fill loss and the pre-ADR-0113 retroactive journaling
    question this item is really about.
16. **`docs/PROJECT_STATUS.md` staleness** ("Session 38 / latest" behind
    git HEAD by 2 days) -- **intentionally not touched.** The account
    owner explicitly instructed (recorded in this repository's own
    `CLAUDE.md`) that this file's existing per-session log format is not
    to be changed and the file itself is not to be edited by a session
    applying this class of cleanup. Recorded here as a deliberate
    exclusion, not a silent omission.
17. **ADR-0019 not marked superseded by ADR-0027** -- confirmed:
    `cancel_order`/`get_order_status`/`get_account`/`get_positions`,
    all `BrokerCapabilityError` stubs in ADR-0019's Phase 13 design,
    were implemented for real in ADR-0027's Phase 21. Added a
    superseded-by annotation to ADR-0019's Status line, matching this
    project's own `ADR-0167 -> ADR-0168` precedent for the same pattern.
18. **`paper_runner` docstring L113-114 "pre-ADR-0113 decision_id
    semantics"** -- already accurately describes the post-ADR-0113,
    CLOSED state (explicit "now CLOSED, superseding ADR-0097's original
    documented gap" language already present). No action needed; the
    audit's line-number reference predates several intervening edits to
    this file.

## Consequences

### Positive
- Every one of the 18 items was independently re-verified against
  current code (not re-asserted from the audit's own text), and three
  turned out to already be resolved by earlier work -- avoiding
  redundant "fixes" to already-accurate text.
- The batch caught and corrected its own error mid-flight (item 8's
  first attempt cited the wrong mechanism) by re-tracing the real
  production code path rather than accepting a plausible-sounding first
  draft, consistent with this session's evidence-first discipline.
- Two items (12, 16) were deliberately left unresolved rather than
  silently "fixed" by a unilateral judgment call or a rule violation --
  both recorded explicitly, matching the honesty standard the
  independent audit itself was checking for.

### Negative / Trade-offs
- Item 12 (the `MARKET_ORDER` Tier 2/`ENABLED` inconsistency) remains a
  real, live safety-relevant asymmetry, now documented but not fixed --
  it still requires the account owner's explicit decision.
- Item 15's underlying data-quality concern (the 2.4-year track
  record's real composition) is not resolved by this batch; it carries
  forward to Batch I in full.
- These are documentation/comment changes only -- no test suite can
  verify that a piece of prose accurately describes reality the way a
  code-behavior test can. Confidence here rests on the direct grep/read
  verification performed per item, recorded above, not on new
  regression tests (there is nothing to regression-test in a docstring
  correction beyond "does the file still parse/import," which the full
  suite run below already confirms for every touched Python/YAML file).

## Tests

No new test files -- this batch is documentation and comments (docstrings,
`.md` files, one workflow comment block, `.env.example`), plus one test
docstring correction (`tests/deploy/test_data_quality_rescan_workflow.py`)
that repeated item 11's same misconception without asserting on it.
Verified every touched Python file still compiles
(`python3 -m py_compile`) and the touched YAML workflow still parses
(`yaml.safe_load`). Ran the full existing suites for every area touched
(`tests/deploy/`, `tests/broker/live/`, `tests/broker/toss/`,
`tests/orchestration/test_run_learning_cycle_cli.py`): 449 passed,
0 failed, before the final full-suite run as the merge gate.

## Status of Implementation at Time of This ADR

Code and docs complete. This is Batch H of a larger, explicitly-requested
pass through every remaining P2/P3 finding in the independent audit
report; Batch I (거래 저널 잔여 -- same-execution_time partial-fill
journal loss, and the pre-ADR-0113 retroactive journaling question item
15 above defers here) is next.
