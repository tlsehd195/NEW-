# ADR-0001: Master Architecture for the Autonomous AI Investment System

**Status:** Accepted
**Date:** 2026-08-24
**Deciders:** Project owner (via initialization instruction), Claude Code
  (Session 1)
**Related documents:** `PROJECT_MASTER_PLAN.md`, `docs/PROJECT_STATUS.md`

---

## Context

This repository is the starting point for an autonomous AI investment
research, validation, learning, and execution system, targeted at
producing verifiable, risk-controlled outperformance of the S&P 500 over
the long term — not a simple prediction script or an unsupervised
auto-trading bot.

Because Claude Code's conversation context does not persist across
sessions, the project must be self-describing from files alone. Before
any implementation begins, the project's purpose, constitution, module
boundaries, data flow, and phase sequencing needed to be captured
durably so that any future session (or any future developer) can recover
full context by reading the repository.

The repository was empty of implementation at the start of this session
(only a placeholder `README.md` with the single line `# NEW-`), so this
decision establishes the architecture rather than reconciling it against
existing code.

## Decision

We adopt the full architecture, module boundaries, data flow, and
governance rules recorded in `PROJECT_MASTER_PLAN.md` as the system's
Source of Truth. Key decisions:

1. **Layered pipeline architecture.** The system is organized as a
   linear pipeline: Data Ingestion → Data Quality/Leakage Guard →
   Feature/State Engine → Market Regime Detection → Prediction/Signal
   Engine → Decision Agent → Position Sizing → Portfolio Risk Engine →
   Order Validator/Safety → Broker Adapter → Toss Securities API →
   Execution/Fill Processing → Trade Journal → Post Trade Analysis →
   Experience/Learning Engine → Candidate Model Generation →
   Validation/Evaluation → Model Registry → Deployment →
   Monitoring/Drift Detection, with a feedback loop back into the
   learning stages.

2. **Strict separation between AI (LLM) reasoning and financial
   decision-making.** LLMs may be used for research, text analysis,
   trade review, and strategy ideation, but position limits, risk
   limits, order validation, cash validation, drawdown protection, and
   the kill switch are implemented as deterministic, non-LLM code paths
   that AI cannot bypass or reconfigure.

3. **AI Gateway as the single entry point for all AI calls.** No
   application code calls an AI provider directly. All requests flow
   through Gateway → Task Router → Quota Manager → Provider Selector →
   Provider Adapter → Provider. This enables free-tier quota rotation
   across multiple providers and guarantees the system never silently
   incurs paid usage — providers with exhausted, uncertain, or unknown
   billing state are disabled rather than assumed safe.

4. **Broker abstraction with Toss Securities as one adapter among
   possible others.** Core trading logic depends only on an abstract
   Broker Interface; Toss Securities Adapter and a Paper Broker are
   interchangeable implementations. No core logic depends on Toss's
   concrete API shape. Toss endpoint/auth/schema details are deferred to
   implementation time against the official Toss documentation — none
   are assumed or invented in this ADR or the master plan.

5. **Trade Journal as long-term memory, not a log table.** Every trade
   is recorded together with a full Decision Snapshot (features,
   prediction, regime, risk state, model/strategy/feature/data/risk/
   execution versions) so that any past decision is reproducible years
   later without relying on conversational memory.

6. **Model lifecycle with mandatory human-gated promotion.** New models
   always start as CANDIDATE and must pass BACKTESTED → VALIDATED → OOS
   TESTED → PAPER TESTED → APPROVED before DEPLOYED. Learning results
   are never auto-applied to the live system; the APPROVED transition is
   treated as requiring explicit human sign-off, not an autonomous
   decision by Claude Code or the AI Gateway.

7. **Point-in-time data discipline and backtest integrity.** Data
   carries `event_time` / `publication_time` / `available_time`;
   features and predictions must never use information unavailable at
   decision time. Backtests must avoid survivorship bias, incorporate
   corporate actions, and always account for transaction costs.

8. **Fail-closed safety posture.** Any unknown/uncertain state — data,
   broker connectivity, position, or model — defaults to blocking new
   orders rather than proceeding. The kill switch is designed so AI
   cannot clear it; clearing is treated as a human action.

9. **Phased delivery, Foundation-first.** Development proceeds through
   16 phases (Phase 0 Foundation through Phase 16 Live Trading). No
   phase begins before the previous phase satisfies the Definition of
   Done (implementation + tests + error handling + logging +
   documentation + configuration + validation). Live order code and
   real AI provider calls are explicitly out of scope until their
   dedicated phases (Phase 12+ for AI Gateway, Phase 13 for the Toss
   adapter, Phase 16 for Live Trading), and Live Trading additionally
   requires passing the full Go-Live gate in
   `PROJECT_MASTER_PLAN.md` §13.11.

10. **File-based persistence of project memory.** `PROJECT_MASTER_PLAN.md`
    (source of truth), `docs/PROJECT_STATUS.md` (current state), and
    `docs/decisions/*.md` (ADRs) together allow any new Claude Code
    session, or any human, to fully reconstruct project context without
    relying on prior conversation history.

## Consequences

### Positive

- The project has a durable, file-based memory independent of any single
  conversation session, satisfying the core persistence requirement.
- Safety-critical logic (risk limits, kill switch, order validation) is
  structurally isolated from LLM control, reducing the blast radius of a
  bad AI output.
- The AI Gateway's provider-agnostic design allows free-tier rotation
  across multiple LLM providers without code changes to callers, and
  prevents unintended paid usage by defaulting to "disable on
  uncertainty."
- The Broker Interface abstraction allows Paper Trading to fully exercise
  the same code path as Live Trading, so Toss-specific integration risk
  is isolated to a single adapter and is deferred until its own phase.
- The phased, gated approach (Definition of Done + Go-Live gate) prevents
  premature exposure of real capital to unvalidated models or code.

### Negative / Trade-offs

- The architecture is deliberately heavier than a minimal trading script
  would require; early phases spend significant effort on
  scaffolding (registries, journals, validation protocols) before any
  trading signal exists. This is an accepted cost per the project's
  stated priority order (Capital Safety and Reproducibility over
  Complexity minimization for its own sake — but here, the "complexity"
  is intentional and directly serves auditability/safety, not accidental
  scope creep).
- Strict phase gating means the system will not produce trading signals
  or backtest results until Phase 2–4 are reached; there is no "quick
  demo" of end-to-end trading early on.
- The human-gated model promotion step (§11.5 of the master plan) means
  the system cannot be fully autonomous end-to-end without a human in
  the loop at model approval time, by design.

## Alternatives Considered

- **Single-provider AI integration (no Gateway/rotation):** Rejected —
  would risk unintended paid usage once a single free tier is exhausted,
  and would couple all AI-dependent modules to one vendor's API shape.
- **Direct LLM-driven order placement:** Rejected — violates the
  project's core safety principle that deterministic code, not LLM
  output, must gate anything that touches capital.
- **Skipping Paper Trading and going straight from backtest to Live:**
  Rejected — the master plan requires Paper Trading PASS as part of the
  Go-Live gate (§13.11); backtest performance alone is explicitly listed
  as an invalid basis for model adoption (§1.1).
- **Building Toss Securities integration early to "get something
  working":** Rejected — the initialization instruction explicitly
  forbids implementing real broker order code before its dedicated
  phase, and forbids guessing at Toss's API shape instead of consulting
  official documentation at implementation time.

## Status of Implementation at Time of This ADR

No implementation code exists yet. This ADR records the architecture
decision only. Phase 0 (Foundation) work continues in subsequent commits;
see `docs/PROJECT_STATUS.md` for current state.
