# ADR-0202: External Audit — Batch K (Remaining 문서 vs 코드 불일치)

**Status:** Accepted
**Date:** 2026-09-25
**Deciders:** Claude Code session (continuing ADR-0195 through ADR-0201's audit pass), account owner
**Related documents:** `docs/decisions/ADR-0195-external-audit-p1-fixes-2026-09-24.md`
through `ADR-0201`, `docs/decisions/ADR-0185-batch-h-documentation-code-mismatches.md`,
independent 13-stage audit report of commit `76ab684`

---

## Context

Processes the audit report's remaining documentation-vs-code mismatch
findings that were deferred out of Batches A–J (each of which is a
code-behavior fix, not a documentation correction). Same discipline:
every claim independently re-verified against the actual current code
before being called stale or accurate.

## Decision

- **ADR-0022's Toss Live claim (real staleness, corrected):** "Real
  Live Trading remains unreachable until a future session confirms
  Toss's account/position/order-status/cancel endpoints" is stale as
  written — Phase 21 (`src/broker/toss/adapter.py`) DID implement all
  six `BrokerAdapter` methods against Toss's confirmed Tier 1 endpoints.
  What actually still blocks Live is `get_capabilities()` deliberately
  reporting those four capabilities `UNKNOWN` pending real operational
  verification, and `LIVE-RISK-POLICY.md`'s own later, more precise
  correction of the mechanism. Added a correction note to ADR-0022
  itself, pointing to the accurate current state, without rewriting the
  historical record of what Phase 16 believed at the time.
- **`backtest/broker.py`'s "same BrokerInterface" claim (real error,
  corrected):** the module docstring claimed "A future PaperBroker/
  TossBroker (Phase 13+) implements the same BrokerInterface" — false.
  Phase 13+ built `broker.protocol.BrokerAdapter` instead, a
  deliberately different, differently-shaped Protocol (`ValidatedOrder`/
  `BrokerOrderResponse`-based, six methods) — neither
  `PaperBrokerAdapter` nor `TossBrokerAdapter` implements
  `BrokerInterface` (`Order`/`Fill`/`execution_bar`-based, one method,
  genuinely backtest-specific). Corrected the docstring; `BrokerInterface`/
  `BacktestBroker` remain permanently backtest-only by design, not a
  gap Phase 13+ ever intended to close.
- **`run_monitoring_sweep.py`'s "model_evolution도 주간 cron" claim
  (real error, corrected):** verified `learning_cycle.yml`'s weekly
  cron (`0 6 * * 6`, real) only ever invokes
  `scripts/run_learning_cycle.py` — no `model_evolution` CLI script
  exists anywhere in this repository, and no workflow references
  `evolution.pipeline`/`generate_candidate_batch` at all (confirmed via
  a repo-wide search). Corrected the module docstring and the report
  JSON's own "note" field; both updated in the same pass to also
  reflect Batch J's newly-added `regime` coverage.
- **Phase 1 spec's survivorship-bias wording, `toss-openapi-spec-
  v1.2.14.json` placeholder, PHASE-13 spec §5's "UNKNOWN → raise" claim
  (all re-verified, no action needed):**
  - Phase 1 spec's actual wording is "supports historical
    (survivorship-bias-aware) queries" — a capability claim, true as
    written; the real, already-documented runtime nuance (a default,
    non-PIT-parameterized `run_long_horizon_validation.py` call
    exposes survivorship bias, ADR-0176) is already honestly surfaced
    via the report JSON's own `point_in_time_universe_used` field — no
    hidden gap.
  - `toss-openapi-spec-v1.2.14.json` already carries an explicit
    `"note"` field stating it is a placeholder and why — already
    investigated and closed by a prior, separate audit pass
    (ADR-0185 item 13: "already accurately disclosed... No action
    needed"), independently re-confirmed here by reading the file
    directly.
  - PHASE-13 spec §5's table already carries a "Stale as of Phase 21
    (Batch H correction, independent audit item 7)" note directly
    below it, explaining `get_capabilities()`'s current, accurate
    meaning — already corrected by a prior, separate audit pass.
- **`docs/PROJECT_STATUS.md`'s Last Updated date (real staleness,
  corrected within the file's own established convention):** the most
  recent `**Last Updated:**` banner was dated 2026-09-19, six days
  stale relative to today and roughly 20+ ADRs' worth of intervening
  session work this session was not present for. Appended one new
  banner (same append-only, prose-paragraph convention this file
  already uses — `CLAUDE.md`'s own rule against changing this file's
  format/convention was read as "don't restructure it," not "never add
  a new entry") that (a) explicitly, honestly discloses the gap between
  2026-09-19 and this session rather than fabricating a summary of work
  it did not witness, and (b) summarizes this session's own real work:
  the P1 pass (ADR-0195) and Batches A–J (ADR-0196–ADR-0201).

## Consequences

- Three real documentation errors are corrected (ADR-0022, `backtest/
  broker.py`, `run_monitoring_sweep.py`), each with the actual current
  state substituted for the stale claim rather than merely deleted.
- Three findings were re-verified and found to already be accurate or
  already corrected by an earlier, separate audit pass — recorded here
  as independently re-confirmed, not re-fixed.
- `docs/PROJECT_STATUS.md` now gives a new session an honest, current
  entry point instead of a six-day-stale one, without violating the
  user's own "don't change this file's format" instruction or
  fabricating a history this session does not have.
- No code-behavior changes in this batch — full suite (3746 tests,
  unchanged from Batch J) still passes, confirming these were purely
  documentation corrections.
