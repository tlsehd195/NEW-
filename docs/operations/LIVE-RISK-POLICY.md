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

```
DECISION REQUIRED (Phase 18 addition)
Problem: Items #1/#6/#7 above are all UNDEFINED (None). Phase 16's own
design treats None as "not enforced" -- evaluate_safety_gate does not
read any of these three fields at all; they only feed
evaluate_kill_switch_triggers, a separate mechanism an operator must
also remember to invoke.
Current Design: Live can structurally activate (pending the separate,
independently-blocking Toss capability gap) with zero automatic daily-
loss/turnover/order-frequency circuit breakers, if an operator never
sets values for #1/#6/#7.
Option A: Keep None = not enforced. Simpler; relies on manual oversight
plus the other 11 safety-gate conditions until an operator explicitly
opts into automatic limits.
Option B: Change evaluate_safety_gate so any of #1/#6/#7 being None
becomes itself a blocking condition, structurally requiring all three
to be explicitly decided before Live can activate at all.
Recommendation: None given -- this is a financial-policy decision, not
a technical one, and changing Phase 16's documented design
unilaterally is exactly what this project's discipline forbids an AI
from doing on its own.
Impact: See docs/specifications/PHASE-18-paper-performance-and-validation.md
section 5 for the full analysis. No code was changed as a result of
raising this.
```

### Phase 19 analysis of Option A vs. Option B (still no decision made)

Phase 19's instruction required weighing both options explicitly before
concluding this must stay a human decision, rather than re-raising the
same DECISION REQUIRED without further analysis. That weighing:

**In favor of Option A (keep `None` = not enforced):**
- It is Phase 16's own considered, documented design
  (`LiveTradingConfig`'s own comment: an operator must set these
  explicitly for them to have any effect), not an oversight.
- The other 11 `evaluate_safety_gate` conditions already require
  affirmative, verified-healthy signals (capability ENABLED, approval
  present and valid, risk/account/position state known, kill switch
  not engaged) -- these three fields are the only ones designed as
  opt-in *extras* layered on top of an already-fail-closed base, not
  the base itself.
- Forcing a mandatory numeric default would require *this project* to
  invent one to keep the system usable, which is exactly what section
  6/20 of this phase's own instructions forbid.

**In favor of Option B (None blocks Live outright):**
- A daily loss limit specifically is, in most real trading operations,
  considered a baseline capital-protection control, not an optional
  extra -- its absence is a materially different risk category than
  "we don't yet know the account balance" (a state-uncertainty
  problem); it is closer to "we have decided not to cap the damage."
- `PROJECT_MASTER_PLAN.md`'s fail-closed principle is stated broadly
  enough that a reasonable reading could extend it to "an unset risk
  boundary is itself an unknown-risk state."

**Why this remains undecided rather than resolved by this analysis:**
Both readings are internally consistent; picking between them is a
statement about how much automatic protection this specific operator
wants versus how much they trust manual oversight for an initial
activation -- a risk-tolerance question, not a correctness question.
`evaluate_safety_gate`'s current behavior is not a bug (it does exactly
what its own tests and documentation say it does); changing it is a
policy change. It is also currently inert either way: the Toss
capability gap independently blocks Live regardless of which option is
chosen, so no immediate safety consequence follows from leaving this
open through Phase 19.

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

## Phase 20 — Proposed initial values for #1 / #6 / #7 (NOT a decision)

Phase 19 deliberately stopped short of proposing numbers for items
#1/#6/#7 ("The exact number is a capital/strategy decision this
document does not make"). Phase 20's instruction explicitly asks for a
*reasonable proposed* initial value for each, framed as Claude's
proposal for human review — not a decision this document is making
unilaterally. **None of the values below take effect on their own; a
human must set them in `LiveTradingConfig`/`RiskConfig` before they do
anything, per the None-semantics section below.** They are grounded in
this system's actual, current scope: US equities, long-term/low-
turnover, the 16-symbol pilot universe (`MARKET-DATA-PROVIDER.md`), and
small experimental capital (per Phase 20's user-set policy) — not
picked as generic round numbers.

### #1 — `LiveTradingConfig.max_daily_loss`

**Proposal: 2% of whatever initial capital is eventually set**, not an
absolute dollar figure. The field itself is coded as an absolute
`float` (Option A of Phase 17's own analysis; a ratio-based variant
would need new code), so this proposal cannot be reduced to a concrete
number yet — initial Live capital is explicitly not being decided this
phase (per the user's own stated policy: only after the Toss capability
gap is resolved and real account state is visible). Once capital is
set, `max_daily_loss = 0.02 * initial_capital`.

**Rationale**: 2% is a conservative, commonly used single-day loss
threshold for equity portfolios generally. For a long-term, low-
turnover strategy that should not structurally produce large single-day
drawdowns, 2% is tight enough to catch a genuine problem (a bug, a bad
fill, a data error) while loose enough not to nuisance-trip on
ordinary US equity volatility (single-day moves of 1-2% on individual
names, and sometimes the broad market, are unremarkable).

### #6 — `RiskConfig.max_turnover`

**Proposal: 3.0** (i.e. cumulative trade notional may reach up to 3x
the account's average historical portfolio value before this check
rejects a new order).

**Important nuance surfaced while proposing this**: `max_turnover` is
checked against `PortfolioAccounting.turnover()`
(`src/backtest/portfolio.py`), which is **cumulative since account
inception** (`sum(trade notionals) / average historical portfolio
value`), not a period-normalized "annual turnover %". It is
monotonically non-decreasing over the account's life. A fixed cap
therefore does not mean the same thing at month 1 as it does at year 3
— this is a real property of the existing metric, not something this
proposal invents.

**Rationale for 3.0 specifically**: building out the initial ~16-symbol
pilot-universe position from cash contributes roughly 1.0x turnover on
its own (each symbol bought once, against a still-small average
portfolio value early in its history). A small number of full or
partial rebalances over the following one to two years of Live
operation could plausibly add another 1.0-2.0x without anything being
wrong. 3.0 gives headroom for that ordinary behavior while still
rejecting a genuinely runaway pattern (a bug causing repeated buy/sell
churn would blow past 3.0 quickly). **Because the metric is
non-stationary, this number should be explicitly re-reviewed
periodically (e.g. at each quarterly/human policy review), not treated
as a permanent constant** — that review cadence is itself part of this
proposal, not a separate decision.

### #7 — `LiveTradingConfig.max_order_frequency_per_hour`

**Proposal: 30**.

**Rationale**: the existing DECISION REQUIRED block already recommended
"a small fixed number (e.g. single digits per hour)" without computing
one against this system's actual scope. A single-digit cap would be
too tight: a legitimate full rebalance across the 16-symbol pilot
universe (`MARKET-DATA-PROVIDER.md`) could submit up to 16 orders in
one pass, and partial-fill follow-ups or a retry after a transient
broker error could add a few more. 30 gives roughly 2x headroom over
that realistic worst-case legitimate burst, while remaining far below
what a genuine runaway-order-loop bug would produce (such a bug would
typically generate many orders per *minute*, not per hour, and would
still trip this check well within the first hour).

### None-semantics — made explicit (not changed)

Per instruction section 17's request to make this "explicit and
consistent," restated plainly rather than re-decided (Phase 19 already
established Option A vs. B remains a human decision, not resolved
here):

- **`None` on any of `LiveTradingConfig.max_daily_loss`,
  `RiskConfig.max_turnover`, or
  `LiveTradingConfig.max_order_frequency_per_hour` means "this specific
  check does not run" — not "zero," not "unlimited-but-flagged," and
  not a fail-closed state on its own.** `evaluate_kill_switch_triggers`
  (`src/broker/live/kill_switch.py`) simply skips the daily-loss and
  order-frequency triggers when their fields are `None`;
  `PortfolioRiskEngine.assess` (`src/risk/engine.py` lines 303-311)
  simply skips the turnover check when `max_turnover` is `None`. This
  is consistent across all three fields and both modules — verified
  again while writing this section, not merely asserted.
- **This is different from the "configured means fail-closed on
  missing data" pattern that already exists once a value *is* set** —
  e.g. `if config.max_turnover is not None: ... if turnover is None:
  reject "turnover_unknown"` (`src/risk/engine.py`). Setting a value
  turns on fail-closed behavior for missing *inputs* to that check; it
  is `None` on the *limit itself* that means "check not active at all."
  Both facts hold simultaneously and are not in tension — this section
  exists so that is stated once, plainly, rather than left implicit.
- **Live activation remains disallowed regardless of what values are
  set for #1/#6/#7** — the independently-blocking Toss capability gap
  (`docs/operations/TOSS-API-GAP-ANALYSIS.md`) means none of this
  changes whether Live can activate today.

**DECISION REQUIRED: risk limit values for #1/#6/#7 — awaiting user
ratification.** The three proposals above are Claude's reasoned
starting points for review, not approved policy. A human financially
responsible for the account must explicitly set (or explicitly
reject/revise) each value in `LiveTradingConfig`/`RiskConfig` before it
has any effect; until then all three remain `None` and unenforced, per
the None-semantics above.

## Phase 22 — Revised (more conservative) proposed values, and Option B adopted for #1/#7

Phase 22's instruction directed two concrete changes on top of Phase
20's proposals, both implemented in code this phase (`ADR-0028` section
36 covers the full rationale; this section restates only the policy-
document-facing consequences).

### Revised numeric proposals — still not ratified

| # | Field | Phase 20 proposal | Phase 22 proposal (more conservative) |
|---|---|---|---|
| 1 | `LiveTradingConfig.max_daily_loss` | `0.02 * initial_capital` | **`0.02` fraction of capital (unchanged ratio)** — `LiveTradingConfig.max_daily_loss` is still coded as an absolute `float` (`src/broker/live/config.py`; Option A of Phase 17's own analysis), so this ratio still cannot become a concrete number until initial Live capital is set; `max_daily_loss = 0.02 * initial_capital` at that point, exactly as Phase 20 proposed — instruction section 17 restates the 2% figure as the value to carry forward, not to tighten further |
| 6 | `RiskConfig.max_turnover` | `3.0` | **`2.0`** — tighter cumulative-turnover headroom; still enough to cover initial 16-symbol universe construction (~1.0x) plus one to two ordinary rebalances, per the same non-stationary-metric caveat Phase 20 already recorded (still applies unchanged — re-review at each policy cycle, not a permanent constant) |
| 7 | `LiveTradingConfig.max_order_frequency_per_hour` | `30` | **`6`** — roughly Phase 20's own worst-case legitimate burst estimate (a full 16-symbol rebalance pass) divided by more than 2x; a genuine runaway-order-loop bug still trips this well within the first hour, and Paper Trading's own long-term/low-frequency orientation makes anything above single-digit hourly orders already anomalous for this system's intended use |

These remain **INITIAL CONSERVATIVE SYSTEM DEFAULT** proposals, not
financial truth, and not self-ratifying — identical status to Phase
20's numbers, just tighter. **No code auto-applies these to a real Live
account.** A human financially responsible for the account must still
explicitly set (or reject/revise) each value before it has any Live
effect. `us_longterm_config.build_us_longterm_paper_config` (Paper
Trading only) does not set any of #1/#6/#7 — Paper Trading has no
Live-style kill switch/safety gate to enforce them against.

### Option B adopted for #1 and #7 (not #6) — supersedes the Phase 17-20 "still open" framing for those two fields only

Phase 19's analysis (above) weighed Option A ("`None` = not enforced,
Live can activate anyway") against Option B ("`None` on a required
Live risk limit is itself a `SAFETY GATE FAILURE`") and left the choice
open as a risk-tolerance decision. Phase 22's instruction directs
Option B explicitly for this phase, implemented in
`evaluate_safety_gate` (`src/broker/live/safety_gate.py`):

```python
if context.config.max_daily_loss is None:
    failed.append("risk_limit_not_configured_max_daily_loss")
if context.config.max_order_frequency_per_hour is None:
    failed.append("risk_limit_not_configured_max_order_frequency_per_hour")
```

Both conditions are covered by regression tests
(`tests/broker/live/test_live_safety_gate.py::
TestRiskLimitNoneSemanticsOptionB`, 5 tests) proving each field
independently blocks, both together report both reasons, both set does
not block on this condition, and the default (unset) `LiveTradingConfig`
blocks by default — matching the fail-closed framing this document has
used throughout.

**`RiskConfig.max_turnover` (#6) is NOT part of this change** and
remains genuinely **UNDEFINED / Option A vs. B still open**, exactly as
Phase 19 left it. `evaluate_safety_gate` reads only
`SafetyGateContext.config` (a `LiveTradingConfig`); `max_turnover` lives
on the separate `RiskConfig` object, which the safety gate has no
structural reference to today. Making #6 participate in the same
Option-B fail-closed pattern would require adding a new field or
parameter to `SafetyGateContext`/`evaluate_safety_gate` itself — new
plumbing, not a semantics flip on an existing check — and was
deliberately left out of this phase's additive, minimal-change scope
rather than done speculatively. This is a real, still-open gap, not an
oversight papered over: a Live account with `max_daily_loss` and
`max_order_frequency_per_hour` both set (satisfying the new Option-B
gate condition) could still have `max_turnover=None`, silently
unenforced, exactly as before.

**Practical effect today**: because Toss capability verification
independently and unconditionally blocks Live activation
(`TOSS-API-GAP-ANALYSIS.md`), this change has no observable effect on
whether Live can activate right now — it changes what *would* additionally
block activation once the Toss gap is someday resolved, tightening the
gate ahead of that eventuality rather than after it.
