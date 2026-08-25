# ADR-0014: Position Sizing + Portfolio Risk Engine Architecture

**Status:** Accepted
**Date:** 2026-08-25
**Deciders:** Claude Code (Phase 8 session), pending project owner review
**Related documents:** `PROJECT_MASTER_PLAN.md` §1.4, §1.5, §1.6, §3,
§4.2, §8.3, §8.4, ADR-0009 (Trade Journal), ADR-0010 (storage), ADR-0013
(Decision Agent), `docs/specifications/PHASE-8-position-sizing-and-risk.md`

---

## Context

`PROJECT_MASTER_PLAN.md` §8.3/§8.4 splits what Phase 7's Decision Agent
deliberately does *not* do into two further deterministic layers:
Position Sizing (`target_weight`/`target_quantity`, risk-aware) and
Portfolio Risk Engine (portfolio-level hard limits: single position,
sector/factor, gross/net exposure, drawdown, cash minimum, turnover,
liquidity, concentration). §1.5/§1.6 make these two layers, together,
the deterministic boundary an AI-based Decision Agent can never bypass.
This ADR records how Phase 8 builds both layers while keeping Risk
Limit *values* honest (never claimed optimal), Order Creation/
Validation/Broker entirely out of scope, and Phase 7's own boundary
untouched.

## Decision

### 1. One package, two modules -- `src/risk/sizing.py` and `src/risk/engine.py`

Position Sizing and Portfolio Risk Engine are two distinct
responsibilities per the master plan's own module table, but they share
one lineage chain, one config-versioning discipline, and one downstream
consumer pipeline (`DecisionOutput -> PositionSizingResult ->
RiskCheckedPosition`). Rather than two separate top-level packages, they
live as two modules inside one `src/risk/` package -- the same
multi-concern-single-package pattern Phase 3's `trade_journal` already
established (`models.py`/`repository.py`/`analysis.py`/`experience.py`/
`backtest_adapter.py` under one package). `sizing.py` and `engine.py`
remain independently importable and independently testable; nothing
about the package boundary blurs the module boundary the master plan
defines.

### 2. `RiskCheckStatus` (`PASS`/`REDUCE`/`REJECT`/`UNKNOWN`) is shared across both layers

The instruction's required vocabulary for Risk Limit Enforcement
(section 8) is reused, unmodified, as `PositionSizingResult.status` too,
rather than inventing a second, differently-named outcome enum for
sizing. Both modules express the same kind of outcome (grant in full,
grant reduced, refuse, or "the check itself could not run") -- a single
canonical vocabulary avoids the drift risk two overlapping enums would
create, the same "reuse instead of parallel schema" discipline
ADR-0009/ADR-0011/ADR-0013 already established for other types.

### 3. `PositionSizer.size()` / `PortfolioRiskEngine.assess()` are pure data-in/data-out -- `current_price` is supplied by the caller

Neither module calls `AsOfDataView` or any repository, exactly like
`DecisionAgent.decide()` (ADR-0013 §3). `PositionSizer` needs a market
price to convert a weight into a quantity but does not fetch one itself
-- `current_price` is a required keyword argument the caller must
already have (typically fetched the same way `BuyAndHoldStrategy`
already fetches it, via `AsOfDataView.get_bars(...).close`, one layer
up). This keeps Position Sizing's point-in-time safety fully inherited,
adding no new `AsOfDataView` call site anywhere in `risk.*`
(`tests/risk/test_risk_point_in_time.py` verifies the guarantee end to
end, one layer beyond Phase 7's own leakage test).

### 4. `PortfolioRiskEngine` re-checks `single_position_limit` independently of `PositionSizer` -- deliberate defense in depth

`PositionSizingConfig.max_position_weight` and
`RiskConfig.max_position_weight` are two separate, independently
configurable values. `PositionSizer` already caps its own proposal at
its own configured weight; `PortfolioRiskEngine` re-applies its own cap
regardless of what was proposed, never trusting the upstream result.
This duplication is intentional, not an oversight: instruction section
31's closing principle ("AI의 판단보다 Risk Engine이 우선한다") is
implemented literally here -- Risk Engine is the pipeline's *final*
authority, so it must not skip a check just because an earlier layer
claims to have already applied it.

### 5. "Not configured" vs. "configured but currently uncomputable" -- two different fail-closed outcomes

`RiskConfig` distinguishes two states that could otherwise be conflated:
a limit left `None` (e.g. `max_turnover`, `max_sector_weight`) means
"not enforced -- no configured limit," and that check is simply skipped
for every call. A limit that *is* configured (e.g. the default
`max_drawdown=0.20`) but whose required input is unavailable for a
specific call (e.g. `value_history` too short) always `REJECT`s
("drawdown_unknown") -- per instruction section 8's "Risk check
unavailable -> REJECT/NO_TRADE" and section 9's "UNKNOWN -> DO NOT
TRADE." Conflating the two would either make every unconfigured,
data-unsupported constraint (sector/factor limits -- see decision 9)
permanently block all trading, or let an active, configured drawdown
check silently pass when it cannot actually verify anything -- both
wrong for different reasons. This distinction only applies to
risk-*increasing* actions (new BUYs); HOLD/NO_TRADE/SELL/EXIT are never
gated by it (decision 11).

### 6. `risk_state` is embedded inside `risk_assessments.payload_json`, not a separate table

`PortfolioRiskState` (portfolio_value, cash, gross/net exposure,
position_weights, drawdown, etc.) is always 1:1 with the
`RiskCheckedPosition` that computed it -- it is never independently
queried or joined against on its own. Rather than a third table plus a
join, it is embedded inline, the same choice `decision_outputs` already
made for its `regime` context dict (Phase 7 spec section 5) instead of
requiring a join to Regime's own tables for something that is always
computed fresh alongside the record that used it.

### 7. Cash safety: `PositionSizingConfig.cost_safety_margin` directly reuses `BuyAndHoldStrategy.COST_SAFETY_MARGIN`'s value and purpose

Instruction section 11 names the exact bug this must not regress:
Phase 2's baseline strategies originally spent 100% of available cash,
leaving nothing for the broker's commission estimate and causing a
spurious `REJECTED` order -- fixed by `BuyAndHoldStrategy.
COST_SAFETY_MARGIN = 0.02`. `PositionSizer` reserves the identical 2%
buffer by default, and `tests/risk/test_sizing.py::
TestCashSafetyRegression` asserts directly that a fully-sized BUY never
proposes spending past `(1 - cost_safety_margin)` of available cash,
regardless of `max_position_weight`. `RiskConfig.minimum_cash_ratio` is
a second, independent, portfolio-level cash floor (decision 4's
defense-in-depth reasoning applied to cash specifically) -- the two
serve different purposes (transaction-cost headroom vs. a standing
portfolio-level cash reserve) and are configured separately.

### 8. `DecisionOutput.target_weight_hint` is never read by `PositionSizer`

Phase 7 named the field a "hint" specifically so a future reader would
not treat it as authoritative (ADR-0013 §2). Phase 8 makes that literal:
`PositionSizer.size()`'s signature has no path through which
`target_weight_hint` could reach the computation at all --
`tests/risk/test_sizing.py::TestTargetWeightHintIsNotAuthoritative`
proves an oversized hint changes nothing about the computed weight.

### 9. `max_sector_weight` / `max_factor_exposure` are configured `None` -- not implemented, not faked

`data_infra.models.SecurityMaster` (Phase 1) has no sector or factor
field. Rather than fabricate a placeholder classification to exercise
"sector_limit," `RiskConfig` leaves both `None` (meaning "not enforced,"
per decision 5) and `PortfolioRiskState.sector_exposure` is always
`None`. This is the identical, already-established pattern Phase 5 used
for its own unimplemented Correlation/Stress 3-axis combination
(ADR-0011 "Alternatives Considered") -- a documented extension point,
not a silent gap.

### 10. Position-level market values, for positions other than the one under review, use the `average_cost` proxy -- an inherited, not new, limitation

Because `PositionSizer.size()`/`PortfolioRiskEngine.assess()` are called
once per security (the same per-security call shape Phase 5's
`RegimeDetector.compute_composite`, Phase 6's `Predictor.predict`, and
Phase 7's `DecisionAgent.decide` already use), only the security under
review has a caller-supplied `current_price`; every other held position
in the portfolio is valued at `average_cost`, the identical fallback
`PortfolioAccounting.mark_to_market` already uses when a live price is
missing (Phase 2 spec section 8.3). `gross_exposure`/`position_weights`/
`concentration` are therefore approximate for a multi-position portfolio
whenever prices have moved since those other positions' average cost --
a documented, inherited limitation of the per-security call
architecture this project has used since Phase 5, not something Phase 8
introduces or could resolve without changing that shared call shape
(out of this phase's scope; see Known Issues in
`docs/specifications/PHASE-8-position-sizing-and-risk.md`).

### 11. `EXIT` is sized identically to `SELL` -- a full close, never partial

`BaselineRuleDecisionAgent` never produces `EXIT` (ADR-0013 §7), but
`PositionSizer` still handles it defensively and identically to `SELL`
(`target_weight = target_quantity = 0.0`, `reason="full_exit"`) so a
future risk-driven `EXIT` producer (Phase 8's own Risk Engine forcing a
close is exactly the scenario `EXIT` is reserved for) has correct
downstream behavior with zero changes to `risk.sizing`.

### 12. `turnover` must be supplied by the caller, never recomputed inside `risk.*`

`backtest.portfolio.PortfolioAccounting` already tracks trade notionals
and exposes `turnover()`; `risk.engine.PortfolioRiskEngine.assess()`
accepts an optional `turnover: Optional[float]` parameter instead of
re-deriving it from a `PortfolioView` snapshot (which does not carry
trade-notional history). When a caller does not have this figure
available (e.g. a `Strategy`-level observer, which only sees
`PortfolioView`, not the underlying `PortfolioAccounting`), `turnover`
is honestly `None` and `RiskConfig.max_turnover` stays unconfigured
(`None`) by default so that absence is never silently misread as a
violation (decision 5).

## Alternatives Considered

- **Have `PositionSizer` fetch its own price via `AsOfDataView`**:
  Rejected -- would duplicate a data-access responsibility Phase 2
  already gave `Strategy`/the backtest loop, and would be the first new
  `AsOfDataView` call site introduced since Phase 2, breaking the
  "point-in-time safety is entirely inherited, never re-implemented"
  chain ADR-0011/ADR-0012/ADR-0013 built.
- **A single merged `PositionRiskAgent` doing both sizing and limit
  enforcement in one pass**: Rejected -- collapses two distinct,
  separately-configurable responsibilities the master plan's own module
  table keeps apart, and removes the defense-in-depth re-check (decision
  4) that is the entire point of Risk Engine being the *final*, not the
  *only*, authority.
- **Silently treating an unconfigured limit (`None`) the same as a
  configured-but-unknown one (fail-closed REJECT)**: Rejected -- see
  decision 5; would make the system either permanently un-tradeable
  (every unimplemented constraint blocks everything) or silently unsafe
  (an active, configured check with missing data quietly passes).
- **Building a synthetic sector/factor classification to exercise
  `sector_limit`/`factor_limit` now**: Rejected -- instruction section 12
  explicitly forbids force-implementing a constraint the current data
  model does not support; see decision 9.

## Consequences

### Positive

- Zero new point-in-time-guard code, for the same reason Phase 5/6/7
  needed none: `risk.*` consumes only already-safe data plus an
  already-fetched price.
- The full lineage chain (`data_version` -> `feature_version` ->
  `regime_version` -> `prediction_version` -> `decision_version` ->
  `sizing_version` -> `risk_version`) is populated honestly end to end,
  with `strategy_version` still `None` -- Phase 8 has no Strategy
  consumer of `RiskCheckedPosition` yet, same honesty Phase 7 applied to
  its own `strategy_version`/`risk_version` fields.
- `PositionSizer`/`PortfolioRiskEngine` are Protocols (satisfied today
  only by their `Deterministic*` reference implementations) -- a future
  model-based sizer or a more sophisticated risk engine is a drop-in
  replacement, never a caller-side change, the same seam
  `Predictor`/`DecisionAgent` already are.
- Order Creation/Validation/Broker (a later phase) receives a
  fully-checked, already-bounded `RiskCheckedPosition` as its natural
  starting input, with no further design needed on this phase's part.

### Negative / Trade-offs

- No live loop yet actually consumes `RiskCheckedPosition` to build an
  order -- entirely observational until Order Creation exists. An
  accepted, explicit scope boundary (Phase 8 spec section 2.2), not an
  oversight.
- Multi-position portfolio exposure/concentration accuracy is bounded by
  the `average_cost` proxy limitation (decision 10) -- inherited, not
  introduced, and already documented in Phase 2's own `mark_to_market`.
- `PositionSizingConfig`/`RiskConfig` defaults are round, illustrative
  starting points, not fit against any performance data (no overfitting
  risk from this phase's own testing process, but also no claim they
  are calibrated for a real deployment) -- identical caveat ADR-0013
  already applied to `DecisionConfig`.

## Status of Implementation at Time of This ADR

Implemented in `src/risk/` (`enums.py`, `config.py`, `models.py`,
`sizing.py`, `engine.py`, `repository.py`) and
`src/storage/risk_repository.py` (+ `storage/schema.py`,
`storage/serialization.py` additions). Exercised by `tests/risk/`,
`tests/storage/test_risk_repository.py`, and
`tests/integration/test_risk_lineage.py`.
