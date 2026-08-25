# PHASE 8 SPECIFICATION — Position Sizing + Portfolio Risk Engine

**Status:** ACTIVE (design confirmed, reference implementation complete)
**Phase:** Phase 8 — Position Sizing + Portfolio Risk Engine
**Depends on:** `PROJECT_MASTER_PLAN.md`, `docs/decisions/ADR-0001`
through `ADR-0013`, Phase 1 (`src/data_infra/*`), Phase 2
(`src/backtest/*`), Phase 3 (`src/trade_journal/*`), Phase 4
(`src/storage/*`), Phase 5 (`src/regime/*`), Phase 6 (`src/predict/*`),
Phase 7 (`docs/specifications/PHASE-7-decision-agent.md`,
`src/decision/*`)
**Produces ADRs:** ADR-0014 (position sizing + portfolio risk engine architecture)

---

## 0. Git / Branch Integrity Check (prerequisite, performed before any Phase 8 work)

Per this session's explicit instruction, the repository's Git/branch/
phase lineage was re-verified from scratch — the prior phase's PASS
result was **not** reused — before any Phase 8 code was written.

```
Current Branch: claude/phase-4-baseline-storage-tuavwk
Current HEAD (at verification time): 6a1c937 (Phase 7: Decision Agent)

Ancestry re-checked individually via `git merge-base --is-ancestor <commit> HEAD`:
  Initial (c3abad0): YES        Phase 0 (e00cfb1): YES
  Phase 1 (194efc4): YES        Phase 2 (926189a): YES
  Phase 3 (e329716): YES        Preserve-Phase0-prompt (4583707): YES
  Phase 4 (44eff48): YES        Phase 5 (d386420): YES
  Phase 6 (6c0b0f6): YES        Phase 7 (6a1c937): YES

- Single linear chain, `git log --merges HEAD` empty -- no merge commits.
- origin/main HEAD = c3abad0 = merge-base(HEAD, origin/main): main is a
  true ancestor, 0 commits on main missing from HEAD, current branch 9
  commits ahead of main (Phase 0-7) -- not yet merged, expected and not
  a problem.
- origin/claude/autonomous-ai-investment-system-wvscwe HEAD = 4583707: a
  true ancestor, 0 commits on wvscwe missing from HEAD, current branch 4
  commits ahead of wvscwe (Phase 4-7).
- All Phase 0-7 files/tests present; 389/389 tests passing; working tree
  clean at verification time.

GIT / BRANCH INTEGRITY: PASS
```

Phase 8 work began only after this fresh PASS result. The Phase 8
completion report repeats this check once more against the final Phase
8 HEAD.

---

## 1. Purpose of This Document

`PROJECT_MASTER_PLAN.md` §8.3/§8.4 splits what Phase 7's Decision Agent
explicitly excludes into two further deterministic layers: **Position
Sizing** (turns a BUY/SELL/HOLD/EXIT/NO_TRADE decision into a concrete,
risk-aware `target_weight`/`target_quantity`) and **Portfolio Risk
Engine** (independently re-checks that proposal against portfolio-level
hard limits and is the pipeline's final authority). Together they are
the deterministic safety boundary §1.5/§1.6 require: no AI-based
Decision Agent, present or future, can size its own position or bypass
a hard risk limit — both remain a wholly separate, non-LLM layer.

---

## 2. Scope

### 2.1 In scope for Phase 8

- `PositionSizer` Protocol + `DeterministicPositionSizer`, a
  deterministic, hand-verifiable rule set combining `DecisionOutput` +
  `PredictionOutput` + `CompositeRegimeObservation` + `PortfolioView`
  (+ an already-fetched `current_price`, + a `risk_budget` fraction)
  into a `PositionSizingResult` (§5, §6).
- `PortfolioRiskEngine` Protocol + `DeterministicPortfolioRiskEngine`,
  independently re-checking a `PositionSizingResult` against
  portfolio-level hard limits (single position, gross exposure,
  concentration, cash minimum, drawdown, portfolio volatility,
  turnover, liquidity) and producing a `RiskCheckedPosition` (§7, §8).
- `PositionSizingResult`/`RiskCheckedPosition`, both structurally
  incapable of representing an order, a broker call, or an execution
  price — Order Creation/Validation/Broker remain a later phase's
  responsibility (§5, ADR-0014 §1).
- `RiskCheckStatus` (`PASS`/`REDUCE`/`REJECT`/`UNKNOWN`), shared across
  both layers (§8, ADR-0014 §2).
- Fail-closed handling for every scenario the instruction lists:
  missing decision/portfolio state, invalid/NaN/infinite numeric input,
  cash shortage, high volatility, low/unknown liquidity, drawdown/
  volatility/turnover data unavailable when the corresponding limit is
  configured (§9).
- Point-in-time correctness inherited entirely from Phase 5/6/7's
  already-safe outputs plus a caller-supplied `current_price` — zero
  new leakage-guard code (§3, ADR-0014 §3).
- `PositionSizingRepository`/`RiskRepository` Protocols +
  `InMemory*` reference implementations, plus persistent
  `DuckDBPositionSizingRepository`/`DuckDBRiskRepository` extending
  Phase 4's storage layer (§11).
- Full version lineage on every result: `data_version` ->
  `feature_version` -> `regime_version` -> `prediction_version` ->
  `decision_version` -> `sizing_version` -> `risk_version`, with
  `strategy_version` honestly `None` (§16, §9 of this doc).
- Backtest integration as pure observation, driving the full
  Prediction -> Decision -> Sizing -> Risk chain at every checkpoint of
  a live `BacktestEngine.run()` loop, proven not to alter the
  strategy's fills (§13).
- A dedicated regression test for the Phase 2 cash-exhaustion bug
  (instruction §11, ADR-0014 §7).

### 2.2 Out of scope for Phase 8

Per the instruction, none of the following are built in this phase:
Order Creation, Order Validation, Broker Adapter, Toss Securities API,
Paper Trading, Live Trading, Prediction model training, Learning
Engine, Model Evolution, AI Gateway, Model Registry, Drift Detection.
No `Strategy` implementation converts a `RiskCheckedPosition` into an
`OrderIntent` — `RecordingStrategy` (test-only,
`tests/risk/test_risk_backtest_integration.py`) computes sizing and risk
alongside a real backtest purely as an observer, using the plain
`BuyAndHoldStrategy` underneath for actual order generation, the same
"compute, don't influence" discipline ADR-0012 §7 / ADR-0013 established.

### 2.3 Changes to Phase 1-7 code

**None.** Phase 8 is fully additive: two new, additive tables in
`storage/schema.py` (`position_sizing_results`, `risk_assessments`) and
additive serialization functions in `storage/serialization.py`. No
existing table's schema changed and no Phase 1-7 source file was
modified (verified: `git diff` against the prior Phase 7 HEAD touches
only `src/storage/schema.py` and `src/storage/serialization.py`, both
pure additions — zero deleted or changed lines in either).

---

## 3. Point-in-Time Correctness

Neither `PositionSizer.size()` nor `PortfolioRiskEngine.assess()` calls
`AsOfDataView` or any repository — both take only already-computed data
plus an already-fetched `current_price` supplied by the caller
(ADR-0014 §3). Point-in-time correctness is therefore entirely
inherited from Phase 5/6/7's outputs and from whoever fetched that
price. This phase writes **zero** new leakage-guard code.
`tests/risk/test_risk_point_in_time.py` verifies end to end: appending
future bars to the repository never changes a sizing/risk result
already computed at an earlier checkpoint through the full
Regime -> Prediction -> Decision -> Sizing -> Risk chain; replaying the
same checkpoint twice is deterministic.

---

## 4. Decision Rules (Deterministic Baseline) — Position Sizing

`DeterministicPositionSizer.size()` evaluates a fixed, ordered sequence
of fail-closed gates; the first violated gate produces a factual
`reason` naming exactly which gate failed. Every one of the five
`DecisionAction` members is handled explicitly.

| Order | Gate | On failure |
|---|---|---|
| 1 | `decision` is `None` | `UNKNOWN` — `decision_unavailable` |
| 2 | `decision.action` is `HOLD`/`NO_TRADE` | `PASS` — pass-through, no new sizing (`no_new_sizing_for_hold`/`no_new_sizing_for_no_trade`) |
| 3 | `portfolio_state` is `None` | `UNKNOWN` — `portfolio_state_unavailable` |
| 4 | `portfolio_value`/`cash` not finite or `portfolio_value <= 0` | `UNKNOWN` — `invalid_portfolio_value` |
| 5 | `decision.action` is `SELL`/`EXIT` | `PASS` — `full_exit` (weight=quantity=0.0) |
| 6 | (BUY) existing position nonzero | `UNKNOWN` — `unexpected_existing_position_for_buy` |
| 7 | `confidence` missing/invalid | `UNKNOWN` — `invalid_confidence` |
| 8 | `risk_budget` not in (0, 1] | `UNKNOWN` — `invalid_risk_budget` |
| 9 | `expected_volatility` missing | `REJECT` — `volatility_unavailable` |
| 10 | `expected_volatility` invalid/negative | `REJECT` — `invalid_volatility` |
| 11 | `expected_volatility >= max_volatility_for_full_size` | `REJECT` — `volatility_exceeds_limit` |
| 12 | Liquidity axis present and `UNKNOWN` | `REJECT` — `liquidity_unknown` |
| 13 | `current_price` missing/invalid | `REJECT` — `missing_price_data` |
| 14 | quantity floors to 0 after all scaling/caps | `REJECT` — `sized_to_zero` |
| 15 | cash or risk_budget bound the result below the natural weight | `REDUCE` — `cash_shortage`/`risk_budget_exceeded` |
| otherwise | — | `PASS` — `normal_sizing` |

`base_weight = max_position_weight * confidence * vol_scale *
liquidity_scale`, where `vol_scale` inversely scales down when
`expected_volatility` exceeds `reference_volatility` (floored at
`min_volatility_scale`) and `liquidity_scale` halves the weight when
the Liquidity axis reports `LOW`. The final weight is additionally
bounded by `(1 - cost_safety_margin) * cash / portfolio_value` and by
`risk_budget * max_position_weight` — whichever binds determines the
`REDUCE` reason (ADR-0014 §7). `DecisionOutput.target_weight_hint` is
never read anywhere in this computation (§5, ADR-0014 §8).

---

## 5. Position Sizing Output Model & Structural Boundary

`PositionSizingResult` (frozen dataclass) carries `status`, `reason`,
`decision_id`/`decision_action`, `proposed_target_weight`/
`proposed_target_quantity`, `current_weight`/`current_quantity`, and the
lineage fields (§9 below). Unlike `DecisionOutput`, this type *does*
carry `target_weight`/`target_quantity` — computing those is this
layer's authoritative responsibility per
`PROJECT_MASTER_PLAN.md` §8.3. What it does **not** have, structurally,
is any `order_id`, `broker_order`, `execution_price`, `side`, or other
order/execution-shaped field.
`tests/risk/test_risk_boundary.py` verifies this by reflection, the
same discipline Phase 5/6/7 already used, and additionally re-verifies
that Phase 7's own `DecisionOutput` boundary remains untouched.

---

## 6. NO_TRADE / HOLD as Pass-Through, Never a Rejection

`HOLD` and `NO_TRADE` decisions never enter Position Sizing's risk
gates at all — they pass straight through as `PASS` with the current
position unchanged (§4 rows 2). This mirrors Phase 7's own principle
(NO_TRADE is a normal result, never an error) one layer further:
maintaining an existing position, or taking no position, is never
something Position Sizing can "reject."

---

## 7. Portfolio Risk Engine — Hard Limits

`DeterministicPortfolioRiskEngine.assess()` first computes a
`PortfolioRiskState` snapshot (`portfolio_value`, `cash`,
`gross_exposure`, `net_exposure`, `position_weights`, `concentration`,
`drawdown`/`max_drawdown`/`portfolio_volatility` when `value_history` is
supplied and long enough, `turnover` when the caller supplies it,
`risk_budget_usage`) — `sector_exposure` is always `None` (§9 below).
It then evaluates, only for a proposed new `BUY`, in order:
`cash_minimum` -> `single_position_limit` (independent of
`PositionSizer`'s own cap, ADR-0014 §4) -> `gross_exposure_limit` ->
`concentration_limit` -> `drawdown_limit` -> `portfolio_volatility_limit`
-> `turnover_limit` -> `liquidity_limit`. `HOLD`/`NO_TRADE`/`SELL`/`EXIT`
(never risk-increasing) always pass through as `PASS` —
`no_new_risk_limit_applicable`; Risk Limit Enforcement only gates new
risk-taking.

A limit left `None` in `RiskConfig` is simply not evaluated ("not
configured"); a limit that *is* configured but whose required data is
unavailable for this call (e.g. `max_drawdown` set but `value_history`
too short) always `REJECT`s — never silently passes (§9, ADR-0014 §5).

---

## 8. Risk Limit Enforcement Outcome Vocabulary

`RiskCheckStatus` — `PASS` / `REDUCE` / `REJECT` / `UNKNOWN` — is shared
by `PositionSizingResult.status` and `RiskCheckedPosition.status`
(ADR-0014 §2). `UNKNOWN` means the check could not run at all (missing
decision, missing portfolio state, invalid numeric input); it is never
treated as safe. `RiskCheckedPosition` is the pipeline's final,
authoritative output for this phase — `final_target_weight`/
`final_target_quantity` are what a later Order Creation phase should
treat as already risk-checked.

---

## 9. Fail-Closed

Every scenario the instruction lists maps to a named, tested `UNKNOWN`
or `REJECT` result, never an exception and never a silently-approved
trade: portfolio state unknown, cash unknown, position unknown, risk
calculation unavailable, invalid prediction/decision, missing required
data, invalid configuration (raised at `PositionSizingConfig`/
`RiskConfig` construction time via `__post_init__` validation), risk
limit unknown (a configured-but-uncomputable check), required liquidity
information unknown, NaN/infinite numeric values. See ADR-0014 §5 for
the "not configured" vs. "configured but uncomputable" distinction this
fail-closed handling depends on.

---

## 10. Drawdown Protection

`PortfolioRiskState.drawdown`/`max_drawdown` are computed from an
optional `value_history` sequence (chronological, including the current
point) via `backtest.metrics.compute_max_drawdown` — reused, not
reimplemented (the same function Phase 2's own performance reporting
already uses). `drawdown = (last - peak) / peak` over that same series.
`RiskConfig.max_drawdown` (default `0.20`, illustrative only) gates new
BUYs; when configured but `value_history` is absent or shorter than
`min_history_for_volatility`, the check `REJECT`s
(`drawdown_unknown`) rather than skipping.

---

## 11. Cash Minimum

`RiskConfig.minimum_cash_ratio` (default `0.05`) is the portfolio-level
hard floor Risk Engine enforces after any new BUY — independent of and
in addition to `PositionSizingConfig.cost_safety_margin` (default
`0.02`), which `PositionSizer` itself reserves as headroom for
transaction costs (ADR-0014 §7). `tests/risk/test_sizing.py::
TestCashSafetyRegression` is the dedicated regression test the
instruction requires, verifying directly that Position Sizing never
proposes spending past `(1 - cost_safety_margin)` of available cash —
the exact class of bug `BuyAndHoldStrategy.COST_SAFETY_MARGIN` was
originally added to fix in Phase 2.

---

## 12. Portfolio Constraints — What Is and Is Not Implemented

Implemented, configurable, independently testable: single position
limit, gross/net exposure limit, concentration limit, drawdown limit,
portfolio volatility limit, cash minimum, turnover limit, liquidity
limit. **Not implemented**: sector limit, factor limit — no sector/
factor field exists anywhere in `data_infra.models.SecurityMaster`
(Phase 1), so there is no data to check either against.
`RiskConfig.max_sector_weight`/`max_factor_exposure` are prepared,
default-`None` extension points a future Feature Registry addition can
populate without a schema change (§9, ADR-0014 §9) — never
force-implemented against fabricated data.

---

## 13. Connection to Phase 7 Decision Agent — Full Pipeline

```
PredictionOutput -> DecisionOutput -> PositionSizingResult -> RiskCheckedPosition
```

`RecordingStrategy` (test-only,
`tests/risk/test_risk_backtest_integration.py`) drives `DriftPredictor`
-> `RegimeDetector` -> `BaselineRuleDecisionAgent` ->
`DeterministicPositionSizer` -> `DeterministicPortfolioRiskEngine` at
every checkpoint of a live `BacktestEngine.run()` loop, using the loop's
own real `PortfolioView` and an accumulating portfolio-value history,
then still delegates to the unmodified `BuyAndHoldStrategy` for actual
order generation.
`test_position_sizing_and_risk_computation_do_not_change_the_strategy_fills`
proves the resulting fills and performance are identical whether or not
the full chain was computed alongside the run. Phase 7's own boundary
(no quantity/order field on `DecisionOutput`, no order-submission
method on `BaselineRuleDecisionAgent`) is re-verified untouched
(`tests/risk/test_risk_boundary.py::TestPhase7DecisionAgentBoundaryIsUntouched`).

---

## 14. Order / Broker — Not Built in This Phase

Per the instruction, Phase 8 never implements Order Creation, Broker
submission, Toss Securities API, Paper Broker, Live Broker, Paper
Trading, or Live Trading. `RiskCheckedPosition` is the final artifact
this phase produces — "the safe position/risk assessment right before
an order would be created," never the order itself.

---

## 15. Trade Journal / Experience Connection

Following ADR-0013 §9's precedent exactly: no `attach_sizing_context`/
`attach_risk_context` enrichment is added into `ExperienceRecord`.
`ExperienceRecord.action` already holds the trade's real, executed
action; overwriting it with this phase's hypothetical, parallel
sizing/risk computation would conflate ground truth with a hypothesis.
Lineage between `risk_assessments`, `position_sizing_results`,
`decision_outputs`, `predictions`, and `regime_composites` is instead
demonstrated via a five-way SQL join across tables sharing one DuckDB
catalog (`tests/integration/test_risk_lineage.py::
test_full_chain_is_sql_joinable_in_one_catalog`), never a mutation of
any Phase 3 record.

---

## 16. Version Lineage

```
Data Version -> Feature Version -> Regime Version -> Prediction Version
   -> Decision Version -> Position Sizing Version -> Risk Version -> Trade
```

Every link up to `Risk Version` is populated honestly:
`data_version`/`prediction_version`/`regime_version`/`decision_version`
are copied verbatim from the `DecisionOutput` used;
`sizing_version`/`feature_version` are `PositionSizer`'s own;
`risk_version` is `PortfolioRiskEngine`'s own. `strategy_version`
remains explicitly `None` on `RiskCheckedPosition` — Phase 8 has no
Strategy consumer yet, same honesty Phase 7 already applied to its own
reserved fields (instruction §16: "아직 존재하지 않는 version은 임의의
값을 만들어내지 않는다").

---

## 17. Persistence

`position_sizing_results` and `risk_assessments` are two new DuckDB
tables in Phase 4's existing catalog file. `risk_state` is embedded
inside `risk_assessments.payload_json` rather than a separate table
(ADR-0014 §6). `storage.risk_repository.
{DuckDBPositionSizingRepository,DuckDBRiskRepository}` implement the
exact `risk.repository.{PositionSizingRepository,RiskRepository}`
Protocols the in-memory reference implementations do — restart safety,
natural-key idempotency, and a point-in-time `get_as_of` lookup are all
verified in `tests/storage/test_risk_repository.py`.

---

## 18. Test Strategy

| Requirement | Test file |
|---|---|
| Unit: normal/zero-confidence/high-vol/low-liquidity/cash-shortage/existing-position/max-limit/risk-budget/hint-ignored/invalid-numeric/negative/boundary | `tests/risk/test_sizing.py` |
| Unit: normal/concentration/cash/drawdown/exposure/turnover/liquidity/unknown-state/unknown-input/invalid-config/NaN/infinite | `tests/risk/test_engine.py` |
| Boundary: no order/broker/execution field; Phase 7 boundary untouched | `tests/risk/test_risk_boundary.py` |
| Leakage: future-data rejection, as-of replay, deterministic replay | `tests/risk/test_risk_point_in_time.py` |
| Integration: Prediction -> Decision -> Sizing -> Risk alongside a real backtest | `tests/risk/test_risk_backtest_integration.py` |
| Persistence: save, reload, idempotency, as_of query | `tests/storage/test_risk_repository.py` |
| Full-chain persistence + SQL lineage joins | `tests/integration/test_risk_lineage.py` |

All of Phase 1-7's existing tests (389) continue to pass unmodified
(`python3 -m pytest tests/ -q`); Phase 8 adds 94 new tests, for **483
total**.

---

## 19. Research Grounding

No new paper is added. The "what design decision requires evidence?"
question was asked and answered: inverse-volatility position scaling
and hard portfolio-level limit checks are standard, transparent,
hand-verifiable risk-management mechanics requiring no academic
grounding beyond what `PROJECT_MASTER_PLAN.md` §8.3/§8.4 already
registers — the same conclusion Phase 5/6/7 reached for their own
deterministic baseline components.

---

## 20. DECISION REQUIRED Review

- **Phase 3 미결 3건 (benchmark return type / per-decision data_version /
  corporate-action-aware portfolio_state)**: re-reviewed — all three
  remain unrelated to Position Sizing/Risk Engine, which read only
  `DecisionOutput`/`PredictionOutput`/`CompositeRegimeObservation`/
  `PortfolioView` and do not touch `BacktestEngine`,
  `ingest_backtest_result`, or portfolio reconstruction.
  **재검토했으며 이번 Phase와 무관하여 이연.**
- **기존 storage schema 변경**: not applicable — two new, additive
  tables only; no existing table's schema changed.

**Conclusion**: no new `DECISION REQUIRED` item was raised this phase.
The `average_cost`-proxy limitation for multi-position exposure (§7,
ADR-0014 §10) is a documented, inherited architectural limitation, not
an open decision requiring a choice between alternatives — it is
recorded as a Known Issue in `docs/PROJECT_STATUS.md`.

---

## 21. Definition of Done for Phase 8

- [x] Git/branch integrity re-verified PASS from scratch before any
      Phase 8 work began (§0)
- [x] Master Plan / prior ADRs / prior specs / current `src/`+`tests/`
      reviewed
- [x] This specification written
- [x] Position Sizing + Portfolio Risk Engine architecture defined,
      boundary with Order Creation/Broker preserved structurally (§2, §5)
- [x] Point-in-time correctness inherited, verified independently (§3)
- [x] Deterministic rule-based Position Sizer + Risk Engine implemented,
      no AI/ML (§4, §7)
- [x] Fail-closed handling for every listed scenario, individually
      tested (§9)
- [x] Cash-exhaustion regression test added (§11)
- [x] Backtest integration as pure observation, proven not to alter
      strategy behavior (§13)
- [x] Full version lineage, honest `None` for not-yet-existing versions (§16)
- [x] Persistence: two new DuckDB tables, restart-safe, idempotent (§17)
- [x] DECISION REQUIRED review completed — none required resolution (§20)
- [x] Full test suite passing: 483/483 (389 prior + 94 new)
- [x] `docs/PROJECT_STATUS.md` updated
- [x] `README.md` updated
- [x] Design + reference implementation committed to git
