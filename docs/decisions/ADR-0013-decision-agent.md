# ADR-0013: Decision Agent Architecture

**Status:** Accepted
**Date:** 2026-08-24
**Deciders:** Claude Code (Phase 7 session), pending project owner review
**Related documents:** `PROJECT_MASTER_PLAN.md` §8.2, §1.4, §3, ADR-0009
(Trade Journal data model & reuse), ADR-0011 (market regime detection),
ADR-0012 (prediction layer), `docs/specifications/PHASE-7-decision-agent.md`

---

## Context

`PROJECT_MASTER_PLAN.md` §8.2 defines the Decision layer: it combines
Prediction + Regime + Portfolio State + Risk State into one of
`BUY/SELL/HOLD/EXIT/NO_TRADE`, optionally with `target_weight`,
`confidence`, `time_horizon` — and explicitly does **not** decide position
size or validate orders (§3's boundary table: "하지 않는 것: 포지션 크기
계산, risk limit 적용, 주문 전송"). Phase 3 already reserved
`trade_journal.enums.DecisionAction` for exactly this phase. This ADR
records how Phase 7 builds that layer while keeping Position Sizing
(Phase 8), Risk Engine (Phase 8), Order Creation, and Execution entirely
out of scope, per this phase's explicit instruction.

## Decision

### 1. `DecisionOutput.action` reuses `trade_journal.enums.DecisionAction`, not a new enum

Phase 3's `DecisionAction` (`BUY | SELL | HOLD | EXIT | NO_TRADE`) was
already built and documented as reserved for this phase. Reusing it
directly — rather than defining a parallel `decision.enums.Action` with
the same five values — is the identical "reuse an existing type instead
of a parallel schema" discipline ADR-0009/ADR-0011/ADR-0012 already
established, this time closing a loop Phase 3 explicitly opened rather
than starting a new one.

### 2. `DecisionOutput` has no order/position-sizing/risk-bypass field, structurally

`DecisionOutput` carries `action`, `confidence`, `time_horizon_days`,
`target_weight_hint`, plus lineage fields — no `quantity`, `order_id`,
`broker_order`, or risk-limit-override field anywhere on the type.
Critically, the weight field is named `target_weight_hint`, not
`target_weight` — a deliberate naming choice signaling it is not Position
Sizing's authoritative output (Phase 8 owns that). `BaselineRuleDecisionAgent.decide()`
has no parameter through which quantity, a broker, or a risk-limit
override could be threaded in, and exposes no method beyond `decide()`
itself. This is the identical structural-boundary technique ADR-0011 §1
and ADR-0012 §1 already used for `RegimeObservation`/`PredictionOutput`,
verified by reflection (`tests/decision/test_decision_boundary.py`), not
left as a documented convention alone.

### 3. `DecisionAgent.decide()` takes already-computed inputs; it fetches nothing itself

`decide(security_id, as_of_time, prediction: Optional[PredictionOutput],
regime: Optional[CompositeRegimeObservation], portfolio_state:
Optional[PortfolioView], risk_state: Optional[dict] = None, ...)` is pure
data-in/data-out — it never calls `AsOfDataView`, a repository, or any
other data-fetching interface. Point-in-time correctness is therefore
entirely inherited from whoever produced `prediction` and `regime`
(Phase 6's `Predictor`, Phase 5's `RegimeDetector`, both already
`AsOfDataView`-safe) — Decision adds **zero** new leakage-guard code,
continuing the exact reuse chain ADR-0011 §2 started and ADR-0012 §2
continued.

### 4. Portfolio State and Risk State are accepted as optional parameters, not produced by this phase

Phase 7 does not build a Portfolio State or Risk State *producer* —
those remain, respectively, an artifact of whatever loop calls
`decide()` (a live `BacktestEngine` run's own `PortfolioView`, in this
phase's integration tests) and Phase 8's future Risk Engine
(`risk_state` is accepted but unused by the baseline agent's rules,
always `None` in every test). This mirrors exactly how Phase 3's own
`DecisionSnapshot.portfolio_state`/`risk_state` were already `Optional`,
populated `None` whenever the producing module did not yet exist
(ADR-0009 §4) — Phase 7 continues that same honesty rather than
fabricating a placeholder Portfolio/Risk State module out of scope.

### 5. Missing `portfolio_state` is fail-closed to `NO_TRADE`, directly citing the master plan's own table

`PROJECT_MASTER_PLAN.md` §1.4's Fail-Closed table has a row: "Position
Unknown → 신규 주문 차단." `BaselineRuleDecisionAgent` implements this
literally: `portfolio_state is None` → `NO_TRADE`, reason
`"portfolio_state_unavailable"`, checked *before* any directional rule
runs. This is not a new safety principle invented for Phase 7 — it is a
direct, traceable application of a rule the master plan already states.

### 6. Regime is a gate only when present; Prediction is mandatory

An entirely missing `regime` argument does not by itself force
`NO_TRADE` — only a *present* regime whose Trend axis is `UNKNOWN` or
whose Stress axis is `HIGH` does. A missing or incomplete `prediction`
(any of `expected_return`/`confidence` being `None`) always forces
`NO_TRADE`, unconditionally. This asymmetry is deliberate: Prediction is
the layer that gives a directional signal any meaning at all (no
expected return, nothing to act on); Regime is an additional, valuable
but not strictly required check layered on top, consistent with the
master plan module table listing Prediction and Regime as separate,
independently-useful inputs rather than co-mandatory ones.

### 7. `EXIT` is reserved, never produced by the baseline agent

`DecisionAction.EXIT` exists on the enum (inherited from Phase 3) but no
rule in `BaselineRuleDecisionAgent` ever returns it — `EXIT` is
conceptually a risk-driven forced close (Risk Engine, Phase 8), while
this agent's rules are entirely signal-driven (Prediction + Regime only).
This mirrors exactly how Phase 2 never produced
`OrderStatus.CANCELLED` despite the enum member existing, reserved for a
future async broker (Phase 3 spec §5.3) — an enum member existing ahead
of its first producer is an established, accepted pattern in this
codebase, not an oversight.

### 8. Persistence: a DuckDB table (`decision_outputs`), deliberately not named `decisions`

Phase 3's Trade Journal already has a table literally named `decisions`
(`DecisionSnapshot` storage, ADR-0010). Phase 7's own persisted type is a
different thing — a standalone, potentially-hypothetical agent output
computed alongside a backtest, not (yet) tied to an executed order the
way a `DecisionSnapshot` is. Naming the new table `decision_outputs`
avoids any ambiguity between the two, while both live in the same DuckDB
catalog file (the same point-lookup/filter/join-heavy criterion ADR-0010
§1 / ADR-0011 §4 / ADR-0012 §8 already applied to Benchmark, Regime, and
Prediction data). No existing table's schema changed.

### 9. No lineage-enrichment function into the Trade Journal — a genuine, documented gap

Phase 5 and Phase 6 each added a non-invasive `attach_*_context` function
populating a Phase-3-reserved field on `ExperienceRecord`
(`market_regime`, `expected_outcome`). Phase 7 does **not** add an
equivalent `attach_decision_context`, because there is no analogous
empty, honestly-reserved field to fill: `ExperienceRecord.action` is
already populated with the trade's *real, executed* action (derived from
the actual `Fill.side`), and overwriting or "enriching" it with
`BaselineRuleDecisionAgent`'s *hypothetical* parallel decision would
silently conflate ground truth with a hypothesis — exactly the kind of
fabricated-precision failure mode ADR-0009 §4 already rejects. Instead,
lineage between Decision, Prediction, and Regime is demonstrated the same
way Phase 6 demonstrated Prediction↔Journal lineage at the storage layer
— a direct SQL join across tables in one catalog
(`tests/integration/test_decision_lineage.py::
test_regime_prediction_decision_are_sql_joinable_in_one_catalog`) — not a
mutation of any Phase 3 record.

## Alternatives Considered

- **A `DecisionInformedStrategy` wrapper that converts a `DecisionOutput`
  into an order**: Rejected — Phase 7's own instruction explicitly
  excludes Order Creation, Position Sizing, and Risk Limit Enforcement
  from this phase's scope (section 4 of the instruction), and doing so
  would additionally require inventing a quantity-decision rule this
  phase has no mandate to build. `RecordingStrategy` in
  `tests/decision/test_decision_backtest_integration.py` instead drives
  the full chain as a pure observer, proving it runs correctly inside a
  live backtest loop without ever influencing it — the same pattern
  ADR-0012 §7 already used for Prediction.
- **Embedding Decision Agent output fields directly onto
  `DecisionSnapshot`**: Rejected — `DecisionSnapshot` is Phase 3's record
  of what actually happened, populated from Phase 2's `Order`/`Fill`
  objects; a `DecisionOutput` computed by this phase's agent is not (yet)
  necessarily the thing that produced any given historical order (no
  Strategy consumes it). Keeping them as separate, joinable tables avoids
  overloading one record type with two different epistemic statuses
  ("what we decided to record as fact" vs. "what this agent would have
  decided").
- **Treating a missing Regime the same as a missing Prediction (both
  force `NO_TRADE`)**: Rejected — see point 6; would make Regime a
  co-mandatory input despite the master plan not stating that, and would
  make it impossible to exercise the agent in a context where Regime
  genuinely is not yet wired up (e.g., a future minimal deployment)
  without every decision degrading to `NO_TRADE`.

## Consequences

### Positive

- Zero new point-in-time-guard code, for the same reason Phase 5/6
  needed none: their outputs are consumed as already-safe data.
- `DecisionOutput`'s full lineage chain (`data_version` → `feature_version`
  → `regime_version` → `prediction_version` → `decision_version`, with
  `strategy_version`/`risk_version`/`model_version` honestly `None` until
  their producing phases exist) gives Phase 8+ a concrete, already-tested
  shape to extend rather than design from scratch.
- The `DecisionAgent` Protocol (satisfied today only by
  `BaselineRuleDecisionAgent`) is the same kind of interchangeable-by-
  Protocol seam `Predictor`/`Strategy` already are — a future model-based
  agent is a drop-in replacement, never a caller-side change.

### Negative / Trade-offs

- No live loop yet actually consumes `DecisionOutput` to size and submit
  an order — it is entirely observational until Phase 8 (Position Sizing)
  and later phases exist. This is an accepted, explicit scope boundary
  (Phase 7 spec section 2.2), not an oversight.
- The signal-to-uncertainty and confidence thresholds in
  `DecisionConfig` are round, illustrative defaults, not fit against any
  performance data (no overfitting risk from this phase's own testing
  process, but also no claim they are calibrated for a real deployment).

## Status of Implementation at Time of This ADR

Implemented in `src/decision/` (`config.py`, `models.py`, `agent.py`,
`repository.py`) and `src/storage/decision_repository.py` (+
`storage/schema.py`, `storage/serialization.py` additions). Exercised by
`tests/decision/`, `tests/storage/test_decision_repository.py`, and
`tests/integration/test_decision_lineage.py`.
