# Live Trading Risk Policy -- Completeness Audit

Phase 17 Production Safety Review, Section 9. This document classifies
every risk-policy item the review instruction names, against the
**actual fields that exist in code today** (`src/broker/live/config.py`
`LiveTradingConfig`, `src/risk/config.py` `RiskConfig`/
`PositionSizingConfig`, `src/broker/live/kill_switch.py`
`KillSwitchTriggerContext`) -- not against what a complete policy
*should* contain. No number below was invented for this document; every
numeric default cited already existed in Phase 8's `RiskConfig`/
`PositionSizingConfig` or Phase 16's `LiveTradingConfig`, both of which
document themselves as "round, illustrative starting points," never a
claim of financial optimality.

## Classification scheme

- **DEFINED** -- a concrete numeric value exists, is enforced in code
  today, and was set with Live capital specifically in mind.
- **INHERITED** -- a concrete numeric value exists and is enforced in
  code today, but it comes from Phase 8's pre-trade Risk Engine
  (designed and defaulted for backtesting/paper trading), never
  re-examined or re-approved for real capital specifically.
- **UNDEFINED** -- the field exists (or a natural place for it exists)
  but no value is configured; `None` means "not enforced," not "zero."
- **BLOCKING** -- no field exists at all, and no upstream data makes
  one possible without a separate scope decision.

## Table

| # | Policy Item | Field | Current Value | Classification | Notes |
|---|---|---|---|---|---|
| 1 | Daily loss limit | `LiveTradingConfig.max_daily_loss` | `None` | **UNDEFINED** | Feeds `evaluate_kill_switch_triggers`'s `daily_loss_limit_breached` check (`src/broker/live/kill_switch.py`) only when set. **TBD — HUMAN DECISION REQUIRED.** |
| 2 | Max drawdown | `RiskConfig.max_drawdown` | `0.20` | **INHERITED** | Phase 8, pre-trade only (blocks new BUYs via `PortfolioRiskEngine.assess`, `docs/decisions/ADR-0014`); not Live-specific, never independently re-approved for real capital. |
| 3 | Max single-position exposure | `PositionSizingConfig.max_position_weight` / `RiskConfig.max_position_weight` | `0.10` / `0.10` | **INHERITED** | Two independent checks (sizing-time and portfolio-risk-time), same Phase 8 default in both. |
| 4 | Total portfolio exposure | `RiskConfig.max_gross_exposure` | `1.0` | **INHERITED** | `1.0` = no leverage permitted by default; Phase 8. |
| 5 | Sector exposure | `RiskConfig.max_sector_weight` | `None` | **BLOCKING** | `data_infra.models.SecurityMaster` has no sector field at all (`RiskConfig`'s own comment: "현재 데이터가 지원하지 않는 constraint는 억지로 구현하지 않는다") -- not a missing decision, a missing data source. Closing this requires a Feature Registry addition, out of this phase's scope. |
| 6 | Turnover limit | `RiskConfig.max_turnover` | `None` | **UNDEFINED** | Enforcement path exists and is active (`src/risk/engine.py` lines 304-310 -- `PortfolioRiskEngine` rejects when computed turnover exceeds `max_turnover`, whenever it is set); only the number itself is unset. **TBD — HUMAN DECISION REQUIRED.** |
| 7 | Order frequency limit | `LiveTradingConfig.max_order_frequency_per_hour` | `None` | **UNDEFINED** | Feeds `evaluate_kill_switch_triggers`'s `abnormal_order_frequency` check only when set. **TBD — HUMAN DECISION REQUIRED.** |
| 8 | Liquidity limit | `RiskConfig.enforce_liquidity_limit` | `True` | **INHERITED, conditional** | Only enforced on calls where the caller supplies a `liquidity_state`; if the caller omits it, the check simply does not run for that call (distinct from the regime axis itself reporting `UNKNOWN`, which always rejects). Whether every Live pre-trade call reliably supplies this is a Live-integration question, not a policy-number question -- tracked as a Known Issue below, not a DECISION REQUIRED. |
| 9 | Minimum cash | `RiskConfig.minimum_cash_ratio` | `0.05` | **INHERITED** | Phase 8; portfolio must retain >= 5% of value as cash after any BUY. |
| 10 | Max order notional | *(no field exists)* | -- | **BLOCKING** | No per-order dollar/won cap exists anywhere in `risk.*`/`broker.live.*` today -- only *weight*-based limits (#3/#4) and *quantity* validation (`broker.validation`). A caller wanting an absolute notional ceiling independent of portfolio size has nowhere to configure one. |
| 11 | Max consecutive failures | *(no field exists)* | -- | **BLOCKING** | Not configurable as a count. Behaviorally *stricter* than a countable threshold today: `LiveTradingSession.submit` treats the **first** `BrokerError` as sufficient to flip the whole session to `OperationalState.RECONCILIATION_REQUIRED`, blocking every further submission (`docs/decisions/ADR-0022` decision 8) -- there is no "N consecutive failures" concept because a single ambiguous failure already halts everything. If a future policy wants to distinguish "one blip" from "sustained failure" as different severities, that is new design work, not a number to fill in here. |
| 12 | Broker failure threshold | `KillSwitchTriggerContext.broker_health` | health-status check (`UNAVAILABLE`/`UNKNOWN` trigger) | **INHERITED, coarse** | Not a *count* of failures -- a health-*status* check fed by whatever computes `broker_health` upstream (Phase 14 `monitoring.collectors.collect_broker`). The numeric failure-rate thresholds behind that status live in `MonitoringConfig` (Phase 14), already DEFINED there, just not restated here as a duplicate number. |
| 13 | Data failure threshold | `KillSwitchTriggerContext.data_health` | health-status check (`UNAVAILABLE`/`UNKNOWN` trigger) | **DEFINED (Phase 17 addition)** | Before this phase, `KillSwitchTriggerContext` had no `data_health` field at all -- `monitoring.collectors.collect_data_quality` (Phase 14) already computed this signal, but nothing wired it into kill-switch evaluation. Added this phase (`src/broker/live/kill_switch.py`, `Optional[ComponentHealthStatus] = None`, additive/backward-compatible) with a regression test (`tests/broker/live/test_live_kill_switch.py::TestEachTriggerIndependently::test_data_health_unavailable_triggers`). The underlying numeric thresholds (invalid-rate, staleness) are Phase 14's `MonitoringConfig`, already DEFINED. |

## Summary

| Classification | Count | Items |
|---|---|---|
| DEFINED | 1 | #13 |
| INHERITED | 6 | #2, #3, #4, #8, #9, #12 |
| UNDEFINED | 3 | #1, #6, #7 |
| BLOCKING | 3 | #5, #10, #11 |

## DECISION REQUIRED entries

```
DECISION REQUIRED
Problem: LiveTradingConfig.max_daily_loss defaults to None ("not
enforced"). No number in this codebase specifies how much realized +
unrealized loss in one day should auto-engage the kill switch for a
real account.
Current Design: evaluate_kill_switch_triggers only checks daily_loss
against max_daily_loss when the latter is explicitly set
(src/broker/live/kill_switch.py). With it unset, no automatic
daily-loss-based halt exists at all.
Option A: Set max_daily_loss as an absolute currency amount (e.g. a
fixed KRW/USD figure), decided by whoever is financially responsible
for the account, independent of position sizing.
Option B: Set it as a fraction of total account equity computed at
each check (would require a small code addition -- currently the field
is an absolute float, not a ratio).
Recommendation: Option A is simpler to reason about and matches how
the field is already typed (Optional[float], absolute); a ratio-based
version can be added later without breaking this one if ever wanted.
No specific number is recommended here -- this is a capital-risk
decision this document is structurally prevented from making
(PROJECT_MASTER_PLAN.md section 13.12).
Impact: Until set, the kill switch has no automatic daily-loss trigger
at all -- a bad day would only be caught by a human watching, not by
this system.
```

```
DECISION REQUIRED
Problem: RiskConfig.max_turnover defaults to None ("not enforced"),
and Live Trading has no order-frequency-based turnover cap beyond the
already-separate max_order_frequency_per_hour count.
Current Design: PortfolioRiskEngine (src/risk/engine.py lines 304-310)
already enforces max_turnover whenever it is set -- only the numeric
value itself is undecided.
Option A: Leave unset for an initial small-capital Live activation,
relying on max_order_frequency_per_hour and manual oversight instead.
Option B: Decide a turnover ratio now, since the enforcement path
already exists and needs no new code to take effect.
Recommendation: Option B -- unlike #1/#7/#10/#11, this is a "flip a
number on already-built enforcement" decision, not new engineering
work, so there is comparatively little cost to deciding it before
first activation.
Impact: Without a set value, an unusually high-turnover trading
pattern (e.g. a bug causing repeated buy/sell churn) is not caught by
this specific check -- only by the order-frequency check (#7, also
UNDEFINED) or the daily-loss check (#1, also UNDEFINED).
```

```
DECISION REQUIRED
Problem: LiveTradingConfig.max_order_frequency_per_hour defaults to
None ("not enforced"). No number specifies what order rate should be
treated as abnormal for a real account.
Current Design: evaluate_kill_switch_triggers checks
orders_in_last_hour against this only when set.
Option A: A small fixed number (e.g. single digits per hour),
appropriate for a small-capital, conservative first Live activation.
Option B: Leave unenforced initially and rely on the daily-loss check
plus manual oversight.
Recommendation: Option A -- a low fixed cap costs nothing when trading
is intentionally infrequent, and catches a runaway-order-loop bug
cheaply. The exact number is a capital/strategy decision this document
does not make.
Impact: Without this, a bug that repeatedly resubmits orders (a
scenario the idempotency/reconciliation design otherwise guards
against, but not perfectly, per Known Issues elsewhere in this review)
has one fewer independent backstop.
```

## Known Issues surfaced while writing this document

- **#8 (liquidity limit) enforcement depends on the caller supplying
  `liquidity_state` on every relevant call.** This document did not
  verify that every Live pre-trade path reliably does so end to end
  (that is a broader Risk Engine integration question, not a policy
  number). Recorded here so it is not silently assumed complete.
- **#5/#10/#11 (BLOCKING items)** are not oversights to "fix" under
  this phase's minimal-additive-change discipline -- #5 needs a data
  model addition (Feature Registry), #10/#11 need new design decisions
  about what an order-notional cap or a failure-count policy should
  even mean on top of the existing weight-based and single-failure-halt
  designs. Recorded as gaps, not implemented speculatively.
