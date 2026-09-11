# PHASE 7 SPECIFICATION — Decision Agent

**Status:** ACTIVE (design confirmed, reference implementation complete)
**Phase:** Phase 7 — Decision Agent
**Depends on:** `PROJECT_MASTER_PLAN.md`, `docs/decisions/ADR-0001`
through `ADR-0012`, Phase 1 (`src/data_infra/*`), Phase 2
(`docs/specifications/PHASE-2-backtesting.md`, `src/backtest/*`), Phase 3
(`src/trade_journal/*`), Phase 4 (`src/storage/*`), Phase 5
(`docs/specifications/PHASE-5-market-regime.md`, `src/regime/*`), Phase 6
(`docs/specifications/PHASE-6-prediction.md`, `src/predict/*`)
**Produces ADRs:** ADR-0013 (decision agent architecture)

---

## 0. Git / Branch Integrity Check (prerequisite, performed before any Phase 7 work)

Per this session's explicit instruction, the repository's Git/branch/
phase lineage was re-verified from scratch — the prior phase's PASS
result was **not** reused — before any Phase 7 code was written.

```
Current Branch: claude/phase-4-baseline-storage-tuavwk
Current HEAD (at verification time): 6c0b0f6 (Phase 6: Prediction)

Ancestry re-checked individually via `git merge-base --is-ancestor <commit> HEAD`:
  Initial commit (c3abad0): YES   Phase 0 (e00cfb1): YES
  Phase 1 (194efc4): YES          Phase 2 (926189a): YES
  Phase 3 (e329716): YES          Phase 4 (44eff48): YES
  Phase 5 (d386420): YES          Phase 6 (6c0b0f6): YES

- Single linear chain, `git log --merges HEAD` empty -- no merge commits.
- origin/main HEAD = c3abad0 = merge-base(HEAD, origin/main): main is a
  true ancestor, 0 commits on main missing from HEAD, current branch 8
  commits ahead of main (Phase 0-6) -- not yet merged, which is expected
  and not treated as a problem.
- All Phase 1-6 files/tests present; 349/349 tests passing; working tree
  clean at verification time.

GIT / BRANCH INTEGRITY: PASS
```

Phase 7 work began only after this fresh PASS result. Full commands and
output are in this session's transcript; the Phase 7 completion report
repeats this check once more against the final Phase 7 HEAD.

---

## 1. Purpose of This Document

`PROJECT_MASTER_PLAN.md` §8.2 defines the Decision layer: it combines
Prediction + Regime + Portfolio State + Risk State into one of
`BUY/SELL/HOLD/EXIT/NO_TRADE`. Phase 7 builds the first version —
deterministic, rule-based, explicitly interchangeable with a future
model-based agent — while keeping Position Sizing, Risk Limit
Enforcement, Order Creation, and Execution entirely out of scope
(instruction §4). The phase exists to answer one question reproducibly:
*given what the system predicted and what regime it observed, what would
it have decided* — not to place a trade.

---

## 2. Scope

### 2.1 In scope for Phase 7

- `DecisionAgent` Protocol + `BaselineRuleDecisionAgent`, a deterministic,
  hand-verifiable rule set combining `PredictionOutput` +
  `CompositeRegimeObservation` + `PortfolioView` (+ an optional,
  currently-unused `risk_state: dict`) into a `DecisionOutput` (§4, §6).
- `DecisionOutput`, reusing `trade_journal.enums.DecisionAction` directly
  (Phase 3's own reservation) and structurally incapable of representing
  an order, a quantity, or a risk-limit bypass (§5, ADR-0013 §2).
- Fail-closed `NO_TRADE` handling for every the instruction's listed
  scenario: low confidence, high prediction uncertainty, `UNKNOWN` regime,
  missing prediction, missing portfolio state, insufficient expected
  return (§6).
- Point-in-time correctness inherited entirely from Phase 5/6's already-
  safe outputs — zero new leakage-guard code (§3).
- A `DecisionRepository` Protocol + `InMemoryDecisionRepository`
  reference implementation, plus a persistent `DuckDBDecisionRepository`
  extending Phase 4's storage layer (§11).
- Full version lineage on every `DecisionOutput`: `data_version` →
  `feature_version` → `regime_version` → `prediction_version` →
  `decision_version`, with `strategy_version`/`risk_version`/
  `model_version` honestly `None` (§9).
- Backtest integration as pure observation, driving the full Regime →
  Prediction → Decision chain at every checkpoint of a live
  `BacktestEngine.run()` loop using its own real `PortfolioView`, proven
  not to alter the strategy's fills (§8).

### 2.2 Out of scope for Phase 7

Per the instruction, none of the following are built in this phase:
Position Sizing, Portfolio Risk Engine, Risk Limit Enforcement, Order
Creation, Order Validation, Broker integration, Toss Securities API,
Paper Trading, Live Trading, Learning Engine, Model Evolution. Also out
of scope, for the same reasons Phase 6 excluded an order-producing
Strategy wrapper (ADR-0012 §7): no `Strategy` implementation converts a
`DecisionOutput` into an `OrderIntent` — `RecordingStrategy`
(test-only, `tests/decision/test_decision_backtest_integration.py`)
computes decisions alongside a real backtest purely as an observer, using
the plain `BuyAndHoldStrategy` underneath for actual order generation.

### 2.3 Changes to Phase 1-6 code

**None.** Phase 7 is fully additive: two new, additive tables in
`storage/schema.py` (`decision_outputs`) — wait, only one new table
(`decision_outputs`) — and additive serialization functions in
`storage/serialization.py`. No existing table's schema changed and no
Phase 1-6 source file was modified (verified: `git diff` against the
prior Phase 6 HEAD touches only `src/storage/schema.py` and
`src/storage/serialization.py`, both pure additions — zero deleted or
changed lines in either).

---

## 3. Point-in-Time Correctness

`DecisionAgent.decide()` takes only already-computed data
(`PredictionOutput`, `CompositeRegimeObservation`, `PortfolioView`) — it
never calls `AsOfDataView` or any repository itself. Point-in-time
correctness is therefore entirely inherited from Phase 6's `Predictor`
and Phase 5's `RegimeDetector`, both of which are already
`AsOfDataView`-safe (ADR-0011 §2, ADR-0012 §2). This phase writes **zero**
new leakage-guard code, continuing the reuse chain unbroken.
`tests/decision/test_decision_point_in_time.py` (the phase's "Leakage
Test" category) verifies end to end: appending future bars to the
repository never changes a decision already computed at an earlier
checkpoint (recomputing Prediction and Regime through the same
`AsOfDataView` and feeding the result to `DecisionAgent` reproduces the
identical decision); replaying the same checkpoint twice is deterministic.

---

## 4. Decision Rules (Deterministic Baseline)

`BaselineRuleDecisionAgent` evaluates a fixed, ordered sequence of
fail-closed gates; the first violated gate produces `NO_TRADE` with a
factual `decision_reason` naming exactly which gate failed. No branch
ever falls through to an unhandled case (`tests/decision/
test_agent_baseline.py::TestDeterministicOutput::
test_never_falls_through_to_an_undeclared_action` verifies every code
path ends in an explicit action).

| Order | Gate | On failure |
|---|---|---|
| 1 | `prediction` missing or has `None` `expected_return`/`confidence` | `NO_TRADE` — `prediction_unavailable` |
| 2 | `prediction.confidence < DecisionConfig.min_confidence` | `NO_TRADE` — `confidence_below_threshold` |
| 3 | `abs(expected_return) <= uncertainty * min_signal_to_uncertainty_ratio` (only checked when `uncertainty` is present) | `NO_TRADE` — `uncertainty_exceeds_signal` |
| 4 | Regime present and Trend axis is `UNKNOWN` | `NO_TRADE` — `regime_trend_unknown` |
| 5 | Regime present and Stress axis is `UNKNOWN` | `NO_TRADE` — `regime_stress_unknown` (ADR-0115: same fail-closed treatment as gate 4 -- an unknown stress reading must not fall through as if it were low/normal stress) |
| 6 | Regime present and Stress axis is `HIGH` | `NO_TRADE` — `regime_stress_high` |
| 7 | `portfolio_state` is `None` | `NO_TRADE` — `portfolio_state_unavailable` (`PROJECT_MASTER_PLAN.md` §1.4: "Position Unknown → 신규 주문 차단") |

Only after all seven gates pass does a directional rule run:
`expected_return >= min_expected_return` → `BUY` (no existing position)
or `HOLD` (already positioned); `expected_return <= exit_return_threshold`
→ `SELL` (existing position) or `NO_TRADE` (`negative_signal_no_position_to_exit`
— no shorting in the baseline agent); otherwise `NO_TRADE` —
`expected_return_below_threshold` (signal too small to act on either
direction, directly implementing the master plan's own NO_TRADE example:
"expected return가 transaction cost보다 낮음").

`DecisionAction.EXIT` is reserved, never produced by this agent
(ADR-0013 §7) — conceptually a risk-driven forced close, which requires
Risk Engine (Phase 8).

Every threshold lives in `decision.config.DecisionConfig`, never
hardcoded, using the same `configuration_version()` content-hash pattern
`RegimeConfig`/`PredictionConfig` already established.

---

## 5. Decision Output Model & Structural Boundary

`DecisionOutput` (frozen dataclass):

```
decision_id, security_id, as_of_time, action, decision_reason,
confidence, time_horizon_days, target_weight_hint,
regime,
prediction_id, prediction_version, regime_version, feature_version,
data_version, model_version, decision_version,
strategy_version, risk_version,
provenance, experiment_id, recorded_at
```

`action` is `trade_journal.enums.DecisionAction` — reused directly, not
redefined (ADR-0013 §1). There is no `quantity`, `order_id`,
`broker_order`, `execution_price`, or risk-limit-bypass field anywhere on
the type; `target_weight_hint` is explicitly named a *hint*, never
`target_weight`, to make clear Position Sizing (Phase 8) owns the
authoritative value. `tests/decision/test_decision_boundary.py` verifies
all of this by reflection — the same structural-verification discipline
Phase 5/6 already used for their own boundaries.

---

## 6. NO_TRADE as a Normal Result

Every scenario the instruction lists — insufficient confidence,
high prediction uncertainty, `UNKNOWN` regime, missing data, insufficient
expected return, unknown system state (missing portfolio state) — is a
named, tested `NO_TRADE` branch, never an exception and never a
disguised BUY/SELL. `tests/decision/test_agent_baseline.py` exercises
every one individually. Regime is checked only when *present* — a
missing `regime` argument does not itself force `NO_TRADE` (Prediction
is the mandatory input; Regime is an additional check layered on top when
available, ADR-0013 §6).

---

## 7. Deterministic Baseline vs. Future AI/ML — the Extension Point

`DecisionAgent` is a `Protocol`; `BaselineRuleDecisionAgent` is the only
implementation Phase 7 ships. A future AI/ML-based agent would implement
the same Protocol (`decide(...) -> DecisionOutput`) and be a drop-in
replacement for any caller — no interface change required. Per the
instruction's deterministic-safety-boundary requirement: nothing about
this Protocol or `DecisionOutput` gives an AI-based implementation any
way to bypass the fail-closed gates structurally enforced elsewhere (Risk
Engine, Phase 8, will independently validate whatever a
`DecisionOutput` proposes — Decision Agent output is data, not an
executed action, so there is nothing here *to* bypass yet).

---

## 8. Backtest Integration — Observation, Not Influence

`RecordingStrategy` (test-only) drives `DriftPredictor` →
`RegimeDetector` → `BaselineRuleDecisionAgent` at every checkpoint of a
live `BacktestEngine.run()` loop, using the loop's own real
`PortfolioView` at each step, then still delegates to the unmodified
`BuyAndHoldStrategy` for actual order generation.
`tests/decision/test_decision_backtest_integration.py::
test_decision_computation_does_not_change_the_strategy_fills` proves the
resulting fills and performance are identical whether or not the
Decision chain was computed alongside the run — the same "compute, don't
influence" discipline Phase 6 established for Prediction (ADR-0012 §7),
now demonstrated for the full three-layer chain at once.

---

## 9. Version Lineage

```
Data Version → Feature Version → Regime Version → Prediction Version
   → Decision Version → Strategy Version → Risk Version → Trade
```

Every link up to `Decision Version` is populated honestly on
`DecisionOutput` today: `data_version`/`prediction_version` are copied
verbatim from the `PredictionOutput` used; `regime_version` is the
`configuration_version` of the Trend axis observation used;
`feature_version`/`decision_version` are this phase's own. `strategy_version`
and `risk_version` are explicitly `None` — Phase 7 has no Strategy
consumer of `DecisionOutput` yet, and Risk Engine is Phase 8 — never a
guessed value (instruction §9: "아직 존재하지 않는 version은 임의의 값을
만들어내지 않는다").

---

## 10. Trade Journal / Experience — What Was, and Was Not, Connected

Unlike Phase 5/6, this phase does **not** add an
`attach_decision_context`-style enrichment into `ExperienceRecord`.
`ExperienceRecord.action` already holds the trade's *real, executed*
action (from `Fill.side`) — overwriting or enriching it with
`BaselineRuleDecisionAgent`'s *hypothetical*, parallel decision would
conflate ground truth with a hypothesis, exactly the fabricated-precision
failure mode this project's Trade Journal design has consistently
rejected (ADR-0009 §4). Instead, Decision↔Prediction↔Regime lineage is
demonstrated the way Phase 6 demonstrated Prediction↔Journal lineage: a
direct SQL join across tables sharing one DuckDB catalog
(`tests/integration/test_decision_lineage.py::
test_regime_prediction_decision_are_sql_joinable_in_one_catalog`), never
a mutation of any Phase 3 record. This is a deliberate design choice, not
an oversight — recorded in full in ADR-0013 §9.

---

## 11. Persistence

`decision_outputs` is a new DuckDB table in Phase 4's existing catalog
file, deliberately named apart from Trade Journal's own `decisions` table
to avoid conflating "what actually happened" (`DecisionSnapshot`) with
"what this agent would have decided" (`DecisionOutput`) (ADR-0013 §8).
`storage.decision_repository.DuckDBDecisionRepository` implements the
exact `decision.repository.DecisionRepository` Protocol the in-memory
reference implementation does — restart safety, natural-key idempotency
(on `(security_id, as_of_time, decision_version, prediction_id,
provenance)`), and a point-in-time `get_as_of` lookup are all verified in
`tests/storage/test_decision_repository.py`.

---

## 12. Test Strategy

| Requirement | Test file |
|---|---|
| Unit: BUY/SELL/HOLD/NO_TRADE, confidence handling, missing data, UNKNOWN regime, invalid prediction, deterministic output | `tests/decision/test_agent_baseline.py` |
| Boundary: no order/quantity/broker/risk-bypass | `tests/decision/test_decision_boundary.py` |
| Leakage: future-data rejection, as-of replay, deterministic replay | `tests/decision/test_decision_point_in_time.py` |
| Integration: Regime → Prediction → Decision alongside a real backtest | `tests/decision/test_decision_backtest_integration.py` |
| Persistence: save, reload, idempotency, as_of query | `tests/storage/test_decision_repository.py` |
| Full-chain persistence + SQL lineage joins | `tests/integration/test_decision_lineage.py` |

All of Phase 1-6's existing tests (349) continue to pass unmodified
(`python3 -m pytest tests/ -q`); Phase 7 adds 40 new tests, for **389
total**.

---

## 13. Research Grounding

No new paper is added (per instruction §14: "새로운 논문이나 연구가
반드시 필요한 경우에만 조사한다"). The "what design decision requires
evidence?" question was asked and answered: the rule set
(confidence/uncertainty/regime gates, then a threshold-based directional
rule) is a transparent, hand-verifiable decision procedure requiring no
academic grounding beyond what `PROJECT_MASTER_PLAN.md` already registers
— the same conclusion Phase 5 and Phase 6 reached for their own baseline
components.

---

## 14. DECISION REQUIRED Review

- **실제 데이터 provider 선정**: Not needed — Phase 7 uses only
  deterministic mock/fixture data.
- **기존 storage schema 변경**: Not applicable — `decision_outputs` is one
  new, additive table; no existing table's schema changed.
- **Phase 3 미결 benchmark 문제 / data_version 문제 / corporate-action
  portfolio 재구성 문제**: Re-reviewed — all three remain unrelated to
  Decision Agent, which reads only `PredictionOutput`/
  `CompositeRegimeObservation`/`PortfolioView` and does not touch
  `BacktestEngine`, `ingest_backtest_result`, or portfolio reconstruction.
  **재검토했으며 이번 Phase와 무관하여 이연.**

**Conclusion**: no `DECISION REQUIRED` item needed resolution to complete
Phase 7's mandate.

---

## 15. Definition of Done for Phase 7

- [x] Git/branch integrity re-verified PASS from scratch before any
      Phase 7 work began (§0)
- [x] Master Plan / prior ADRs / prior specs / current `src/`+`tests/`
      reviewed (§0-2)
- [x] This specification written
- [x] Decision Agent architecture defined, boundary with Position
      Sizing/Risk/Order preserved structurally (§2, §5, ADR-0013 §2)
- [x] Point-in-time correctness inherited, verified independently for
      the decision code path (§3)
- [x] Deterministic rule-based baseline agent implemented, no AI/ML (§4, §7)
- [x] NO_TRADE handled as a normal, individually-tested result for every
      listed scenario (§6)
- [x] Backtest integration as pure observation, proven not to alter
      strategy behavior (§8)
- [x] Full version lineage, honest `None` for not-yet-existing versions (§9)
- [x] Persistence: DuckDB table in the existing catalog, restart-safe,
      idempotent (§11)
- [x] DECISION REQUIRED review completed — none required resolution (§14)
- [x] Full test suite passing: 389/389 (349 prior + 40 new)
- [x] `docs/PROJECT_STATUS.md` updated
- [x] `README.md` updated
- [x] Design + reference implementation committed to git
