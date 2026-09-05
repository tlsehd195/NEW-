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
| 5 | Sector exposure | `RiskConfig.max_sector_weight` | `None` (RATIFIED value: **0.25**, not yet code-applied) | **UNDEFINED, RATIFIED (Session 36 continued, ADR-0062/ADR-0080)** | `data_infra.models.SecurityMaster` still has no sector field, but `PortfolioRiskEngine.assess` now accepts an opt-in `sector_by_security: Optional[dict[str, str]]` parameter the caller supplies per call (e.g. sourced from `data_infra.universe`'s own real, provider-confirmed sector data, ADR-0058) -- enforcement path exists and is active whenever BOTH `max_sector_weight` is set AND the caller supplies the mapping; either without the other REJECTs `sector_unknown` (fail-closed, mirroring `max_turnover`'s own pattern). `orchestration.paper_runner`/`orchestration.live_runner` now both wire this parameter through (ADR-0067/ADR-0070) whenever a caller passes `--max-sector-weight` (Paper CLI) or the equivalent. The account owner ratified the proposed 25% value -- same "ratified but not baked into the default config" treatment as #1/#6/#7/#11 (ADR-0060/ADR-0065): a human passes `max_sector_weight=0.25` explicitly whenever a real Live `RiskConfig` is constructed. |
| 6 | Turnover limit | `RiskConfig.max_turnover` | `None` | **UNDEFINED** | Enforcement path exists and is active (`src/risk/engine.py` lines 304-310 -- `PortfolioRiskEngine` rejects when computed turnover exceeds `max_turnover`, whenever it is set); only the number itself is unset. **TBD — HUMAN DECISION REQUIRED.** |
| 7 | Order frequency limit | `LiveTradingConfig.max_order_frequency_per_hour` | `None` | **UNDEFINED** | Feeds `evaluate_kill_switch_triggers`'s `abnormal_order_frequency` check only when set. **TBD — HUMAN DECISION REQUIRED.** |
| 8 | Liquidity limit | `RiskConfig.enforce_liquidity_limit` | `True` | **INHERITED, conditional** | Only enforced on calls where the caller supplies a `liquidity_state`; if the caller omits it, the check simply does not run for that call (distinct from the regime axis itself reporting `UNKNOWN`, which always rejects). Whether every Live pre-trade call reliably supplies this is a Live-integration question, not a policy-number question -- tracked as a Known Issue below, not a DECISION REQUIRED. |
| 9 | Minimum cash | `RiskConfig.minimum_cash_ratio` | `0.05` | **INHERITED** | Phase 8; portfolio must retain >= 5% of value as cash after any BUY. |
| 10 | Max order notional | `RiskConfig.max_order_notional` | `None` (RATIFIED value: **$1,000**, not yet code-applied) | **UNDEFINED, RATIFIED (Session 36 continued, ADR-0063/ADR-0080)** | An absolute per-order dollar/currency-unit cap now exists in `PortfolioRiskEngine.assess` (recomputed from the final, already-weight-clamped position; clamps further if it would exceed the cap) -- closes the previous "no field exists" gap. `None` still means "not enforced." The account owner ratified the proposed $1,000 value, explicitly as an operational fat-finger ceiling rather than a portfolio-construction limit -- flagged for revisiting once the account's real USD balance is confirmed. Same "ratified but not baked into the default config" treatment as #1/#5/#6/#7/#11: a human passes `max_order_notional=1000.0` explicitly whenever a real Live `RiskConfig` is constructed. |
| 11 | Max consecutive failures | `LiveTradingConfig.max_consecutive_failures` | `None` (RATIFIED value: **5**, not yet code-applied) | **UNDEFINED, RATIFIED (Session 36, ADR-0063/ADR-0065)** | `LiveTradingSession.consecutive_failure_count` (ADR-0063) is a real, tested observability counter, incremented on each `BrokerError` and reset on success. The user was then asked directly whether to keep the original halt-on-first-failure default or explicitly loosen it, and chose to set the threshold to **5** -- `LiveTradingConfig.max_consecutive_failures` (ADR-0065) now makes this a real, enforced threshold: `submit` halts to `OperationalState.RECONCILIATION_REQUIRED` once the count reaches the configured value, defaulting to `None` (= 1, the ORIGINAL strictest behavior) when unset, so an existing caller that never sets this sees no change. Same "ratified but not baked into `DEFAULT_LIVE_TRADING_CONFIG`" treatment as #1/#6/#7/#10 (ADR-0060) -- a human passes `max_consecutive_failures=5` explicitly whenever a real Live config is constructed. |
| 12 | Broker failure threshold | `KillSwitchTriggerContext.broker_health` | health-status check (`UNAVAILABLE`/`UNKNOWN` trigger) | **INHERITED, coarse** | Not a *count* of failures -- a health-*status* check fed by whatever computes `broker_health` upstream (Phase 14 `monitoring.collectors.collect_broker`). The numeric failure-rate thresholds behind that status live in `MonitoringConfig` (Phase 14), already DEFINED there, just not restated here as a duplicate number. |
| 13 | Data failure threshold | `KillSwitchTriggerContext.data_health` | health-status check (`UNAVAILABLE`/`UNKNOWN` trigger) | **DEFINED (Phase 17 addition)** | Before this phase, `KillSwitchTriggerContext` had no `data_health` field at all -- `monitoring.collectors.collect_data_quality` (Phase 14) already computed this signal, but nothing wired it into kill-switch evaluation. Added this phase (`src/broker/live/kill_switch.py`, `Optional[ComponentHealthStatus] = None`, additive/backward-compatible) with a regression test (`tests/broker/live/test_live_kill_switch.py::TestEachTriggerIndependently::test_data_health_unavailable_triggers`). The underlying numeric thresholds (invalid-rate, staleness) are Phase 14's `MonitoringConfig`, already DEFINED. |
| 14 | Withdrawal (cash-out) policy | *(no field exists, by policy)* | -- | **RESOLVED (Session 36 continued)** | The account owner decided: **no withdrawals, ever -- every realized gain (and any capital, for that matter) stays in the account and is reinvested.** This is not Option A/B/C from the design pass below; it is the option that makes A/B/C all moot, since there is never a withdrawal event for any of them to govern. No field, mechanism, or approval type is added to `src/` -- there is nothing to build, since the resolved policy is the ABSENCE of a withdrawal capability, not a particular shape of one. See "Session 36 continued -- #14 RESOLVED" below. |
| 15 | Rebalancing cash buffer, Live-specific | `RiskConfig.minimum_cash_ratio` (same field as #9) | `0.05` | **RESOLVED, interim (Session 36 continued)** | The account owner decided: keep the inherited `0.05` (5%) floor as-is for now (Option A) -- explicitly a placeholder, not a final answer. A concrete follow-up is on record: once a real Live track record accumulates, revisit with a regime-conditional buffer (Option C, `regime.enums`'s existing LIQUIDITY/VOLATILITY axes) that increases the cash floor in unfavorable market conditions. Deliberately NOT built now -- designing that mapping ahead of any real Live data would be exactly the premature, unvalidated policy-tuning RULE 0.8 warns against. See "Session 36 continued -- #15 RESOLVED (interim)" below. |
| 16 | Reentry cooldown | `RiskConfig.reentry_cooldown_days` | `None` (PROPOSED value: **5 trading days**, not yet ratified) | **UNDEFINED, PROPOSED (Session 36 continued, ADR-0093)** | Found comparing this project against an external repository (dragon1086/prism-insight). Enforcement path exists and is active in `PortfolioRiskEngine.assess` via a new opt-in `last_exit_time_by_security: Optional[dict[str, datetime]]` parameter -- REJECTs a new BUY only when the caller supplies a recent exit for that security AND it falls within `reentry_cooldown_days`; a security absent from the mapping (the ordinary case -- never exited, or exited outside the window) is unaffected, mirroring `enforce_liquidity_limit`'s own "opt-in per call, simply skipped if omitted" pattern rather than `max_sector_weight`'s fail-closed-on-missing-entry pattern (see `RiskConfig.reentry_cooldown_days`'s own docstring for why). A new `TradeRecord.exit_reason: Optional[str] = None` field (additive) now lets a producer record WHY a position was exited, plumbed through `InMemoryTradeJournalRepository`/`DuckDBTradeJournalRepository`/both Paper and Live `build_trade_record` bridges -- but no caller yet populates `last_exit_time_by_security` from real trade history at any orchestration layer (`orchestration.paper_runner`/`orchestration.live_runner`); that wiring, and the choice of which `exit_reason`s should even count toward the cooldown, is future work. **TBD -- HUMAN DECISION REQUIRED** on the number itself. |

## Summary

| Classification | Count | Items |
|---|---|---|
| DEFINED | 1 | #13 |
| INHERITED | 6 | #2, #3, #4, #8, #9, #12 |
| UNDEFINED | 7 | #1, #5, #6, #7, #10, #11, #16 |
| RESOLVED | 2 | #14, #15 |

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

## Items #14/#15 — raised conversationally, listed only, not analyzed or proposed yet

The user asked (outside any specific phase instruction): once the
system is generating real returns and rebalancing on its own, when
should money ever be withdrawn, and how much cash should it hold in
reserve? Recorded here as two separate open items per the user's own
request to track them, not to resolve them now -- no option analysis,
no proposed numbers, unlike #1/#6/#7's Phase 20 treatment above.

```
DECISION REQUIRED
Problem: #14 -- No withdrawal mechanism, field, or policy exists
anywhere in this codebase. If Live activates and generates real
returns, there is currently no way for the system to distinguish
"capital the account owner wants pulled out" from any other cash
state, and no schedule, trigger, or approval flow for it.
Current Design: N/A -- nothing built. broker.live.* only models
order submission/execution/reconciliation; no capital-withdrawal
concept exists in that layer or in risk.*.
Why this should very likely stay a human decision, not an AI one
(surfaced in conversation, not yet formally analyzed): withdrawal
timing is a personal financial-planning question independent of
strategy performance -- the account owner's own cash needs, tax
timing, and diversification goals, none of which this system observes
or should infer. It also interacts with sequence-of-returns risk:
withdrawing during a drawdown converts a paper loss into a realized
one, so "the AI decides when to withdraw based on market state" is a
materially different (and riskier) design than "a human sets a
schedule/rule the system merely executes."
Options: not yet enumerated -- this needs its own design pass
(e.g. a fixed schedule the system executes, vs. a rule-based policy a
human pre-approves, vs. purely manual/out-of-band withdrawal that
never touches this system at all) before Option A/B framing like the
other DECISION REQUIRED blocks above is meaningful.
Recommendation: none yet -- explicitly deferred, per the user's own
"just add it to the list" request.
Impact: none today -- Live is independently blocked by the Toss
capability gap regardless, so this has no immediate safety
consequence. Recorded so it is not forgotten before any real
withdrawal need arises.
```

```
DECISION REQUIRED
Problem: #15 -- separate from #14's withdrawal-timing question, how
much cash should the strategy proactively hold for liquidity and
rebalancing flexibility once Live capital and eventual withdrawals are
real? RiskConfig.minimum_cash_ratio (0.05) already exists and already
gates Live via the same field as #9, but it was chosen for Phase 8
backtesting, not decided with Live withdrawal needs in mind.
Current Design: PortfolioRiskEngine enforces minimum_cash_ratio as a
floor after any BUY (src/risk/engine.py) -- a single static ratio, not
a policy that considers anticipated withdrawals, market regime, or
anything else. risk_controlled_momentum's own real bug (ADR-0038-era
finding, Section H of STRATEGY-VALIDATION-REPORT.md) already showed
uninvested cash from position-cap overflow is not currently
redistributed -- cash buffer today is partly a strategy side effect,
not a deliberately engineered policy.
Options: not yet enumerated -- needs its own design pass (e.g. a
static floor as today vs. a buffer sized off anticipated withdrawal
schedule from #14 vs. something regime-conditional) before this can be
proposed the way #1/#6/#7 were.
Recommendation: none yet -- explicitly deferred, per the user's own
"just add it to the list" request. Whatever is eventually decided
should be reconciled with #14 (a cash buffer sized for zero
anticipated withdrawals is a different number than one sized to cover
several months of planned withdrawals without forced selling).
Impact: none today -- same independent Toss-gap blocker as #14.
```

## Session 36 — Design pass for #14/#15 (options enumerated, still NO decision)

The user asked to proceed on #14/#15 specifically as a design-only
pass -- "생각이 많이 필요함" (this needs a lot of thought), i.e. the
opposite of something to rush. What follows enumerates real options
with their real tradeoffs, exactly what the placeholders above said
was still missing. **No option is recommended, no number is proposed,
and no code changes as a result of this section** -- both remain
open, financially consequential, human decisions
(`PROJECT_MASTER_PLAN.md` section 13.12), and both remain moot today
regardless, since Live is independently blocked by the Toss capability
gap.

### #14 — Withdrawal policy: three real shapes, not variations of one

**Option A — Fixed schedule, system-executed.** A human sets a rule
like "withdraw 2% of portfolio value on the first trading day of each
quarter" once, and the system executes it automatically from then on,
no per-withdrawal approval needed.
- *For*: genuinely "set and forget"; matches how some real retirement
  drawdown strategies work (a fixed or fixed-percentage rule, decided
  in advance specifically to avoid emotional/timing decisions).
- *Against*: this project's own architecture has never given any
  automated component authority to move capital OUT of an account
  without a human decision in the loop (every existing gate --
  `LiveActivationApproval`, the kill switch, Model Candidate promotion
  -- requires a human to approve the *thing that changes*, not just
  the initial policy that permits it). A fixed schedule is exactly
  "the AI decides withdrawal timing was pre-approved," which is a
  different, weaker safeguard than "a human approves this specific
  withdrawal." It also directly collides with sequence-of-returns
  risk exactly as the existing placeholder above already named: a
  fixed schedule withdraws the same amount whether the portfolio is up
  or deep in a drawdown that quarter, converting a paper loss into a
  realized one on a schedule, not a judgment call.

**Option B — Rule-based policy, human pre-approves the RULE, system
proposes, human approves each EXECUTION.** A human sets bounds (e.g.
"never withdraw if portfolio is more than 10% below its high-water
mark"; "never withdraw more than N% of a single quarter's realized
gain"), the system computes whether a withdrawal is currently within
those bounds and, if so, surfaces a proposal -- but doesn't move
anything until a human separately approves that specific proposal.
- *For*: matches this project's existing governance pattern closely
  (`LiveActivationApproval`'s own two-layer shape: a policy exists,
  but a specific action still needs its own human sign-off). Directly
  addresses sequence-of-returns risk -- a high-water-mark or drawdown
  condition is exactly the mechanism that would refuse to propose a
  withdrawal during a bad stretch.
- *Against*: real new design and engineering work -- there is no
  "Withdrawal Proposal" concept, approval type, or persisted record
  anywhere in this codebase today; this would need its own small
  module (something like `LiveActivationApproval`'s own shape, but for
  a withdrawal event instead of an activation event), not a field
  added to an existing config.

**Option C — Purely manual, out-of-band, the system does nothing.** A
human decides to withdraw and does so directly against the real Toss
account (or wherever Live capital eventually lives) -- this codebase
never observes or participates in the withdrawal at all.
- *For*: zero new code, zero new risk surface introduced by this
  project. Matches how most individual investors actually manage
  withdrawals from a self-directed account today, without any
  algorithmic system in the loop for that specific action.
- *Against*: this system's own `PortfolioAccounting`/`PortfolioView`
  would then reflect a stale, too-high cash/portfolio-value figure
  immediately after any such withdrawal until the next real balance
  sync -- a data-freshness gap, not a decision-authority gap, but a
  real operational consideration: every risk check that reads
  `portfolio_state.cash`/`portfolio_value` (cash_minimum,
  gross_exposure, concentration, the new sector/notional checks) would
  be computing against a wrong number until synced.

**A fourth axis, independent of A/B/C**: WHERE the withdrawal decision
lives is separate from HOW MUCH/WHEN. Any of A/B/C could be paired
with a fixed amount, a fixed percentage of the account, or a
percentage of realized gains only (never touching principal) -- that
sizing question is its own sub-decision, not analyzed further here.

### #15 — Cash buffer: three real shapes, and why #14 gates two of them

**Option A — Keep the current static floor (`minimum_cash_ratio`,
`0.05`), unchanged.** No new work; the existing Phase 8 default
continues to gate every BUY.
- *Against*: as the existing placeholder already noted, `0.05` was
  chosen for backtesting, not for a Live account that might someday
  need to fund real withdrawals without forced selling. It is also,
  per the referenced `risk_controlled_momentum` finding, partly a
  strategy side effect today (uninvested cash from position-cap
  overflow is not redistributed) rather than a deliberately sized
  reserve.

**Option B — A buffer sized off #14's actual withdrawal schedule.**
Whatever #14 resolves to (a fixed schedule, a rule-based policy, or
purely manual) implies an expected near-term cash need; the buffer
could be set to cover N withdrawal cycles without needing to sell a
position.
- *Directly gated by #14*: this option cannot be meaningfully sized
  until #14 has an actual shape -- "enough cash for the next
  withdrawal" is undefined if there is no defined withdrawal
  mechanism yet. This is the dependency the original placeholder
  already flagged ("should be reconciled with #14").

**Option C — Regime-conditional buffer**, e.g. holding a larger cash
reserve when `regime.enums`' existing LIQUIDITY/VOLATILITY axes report
a less favorable state, smaller otherwise.
- *For*: this project already has a real, tested regime-detection
  subsystem (Phase 5) that `RiskConfig`'s own `enforce_liquidity_limit`
  already partially consumes (`liquidity_state`) -- reusing that
  existing signal rather than inventing a new one would be consistent
  with this project's own reuse discipline.
- *Against*: genuinely new design work -- there is no established
  mapping from "which regime state" to "what buffer size," and
  inventing one now, before either #14 is decided or any real Live
  track record exists, risks exactly the kind of premature, unvalidated
  policy-tuning RULE 0.8 warns against in the strategy-research context
  and that same caution applies here.

**Not mutually exclusive**: B and C could combine (a withdrawal-sized
floor that additionally widens in an unfavorable regime) -- flagged
here as a real possibility, not analyzed further.

### What this section does NOT do

- Does not pick an option for #14 or #15.
- Does not change `RiskConfig.minimum_cash_ratio` or add any new
  withdrawal-related field, model, or module to `src/`.
- Does not claim any option above is complete -- each would need its
  own full design pass (data model, approval flow if any, tests) once
  actually chosen, matching how #1/#6/#7's own proposals (Phase 20)
  were themselves later still just proposals until the user explicitly
  ratified them (Session 36, `ADR-0060`).

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

### Option B adopted for #1, #6, and #7 — supersedes the Phase 17-20 "still open" framing

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

**Session 36 update: `RiskConfig.max_turnover` (#6) now participates in
the same Option-B fail-closed pattern**, closing the gap this section
used to describe. The user, asked directly whether `max_turnover=None`
should also structurally block Live (mirroring #1/#7), delegated the
choice; the recommendation made and adopted was to close the asymmetry
for the same reasons Phase 22 gave #1/#7 in the first place — see
ADR-0045. `evaluate_safety_gate` still never imports `risk.config`
(`tests/broker/live/test_live_boundary.py::
TestNoRiskLimitOrModelApprovalMutation` structurally forbids it) — the
new `SafetyGateContext.max_turnover: Optional[float]` field is a plain
value the caller sources from their own `RiskConfig.max_turnover`, not
the whole config object:

```python
if context.max_turnover is None:
    failed.append("risk_limit_not_configured_max_turnover")
```

Covered by `tests/broker/live/test_live_safety_gate.py::
TestMaxTurnoverNoneSemanticsOptionB` (3 tests), mirroring #1/#7's own
regression coverage. A Live account with `max_daily_loss`, `max_order_
frequency_per_hour`, AND `max_turnover` all unset is now blocked on all
three conditions simultaneously, not just two.

**Practical effect today**: because Toss capability verification
independently and unconditionally blocks Live activation
(`TOSS-API-GAP-ANALYSIS.md`), this change has no observable effect on
whether Live can activate right now — it changes what *would* additionally
block activation once the Toss gap is someday resolved, tightening the
gate ahead of that eventuality rather than after it.

## Phase 24 confirmation — no change to numbers or architecture

Instruction section 21 asked this phase to keep Phase 22's proposed
values as-is and confirm their status rather than pick new numbers.
Confirmed, unchanged:

- `max_daily_loss=0.02`, `max_turnover=2.0`,
  `max_order_frequency_per_hour=6` remain **PROPOSED / AWAITING USER
  RATIFICATION** — not applied to any real account, not this project's
  final investment policy, and no different value was substituted this
  phase.
- Option B None-semantics (`max_daily_loss`/
  `max_order_frequency_per_hour` → `SAFETY GATE FAILURE` when unset)
  remains implemented exactly as the Phase 22 section above describes.
  `RiskConfig.max_turnover`'s None-semantics gate-visibility gap
  (`evaluate_safety_gate` reads only `LiveTradingConfig`, never
  `RiskConfig`) was re-checked this phase against the current code
  (`src/broker/live/safety_gate.py`) and found unchanged and still
  consistent with the description above — no new plumbing was added,
  per the instruction's explicit "불필요하게 risk architecture를
  재설계하지 않는다."
- This phase's own work (`src/data_infra/universe.py`,
  `strategy_research`) never reads or writes any field in this
  document's scope — Universe/strategy-research expansion has no
  interaction with Live risk policy at all.

## Phase 25 confirmation — no change to numbers or architecture

Instruction explicitly forbids touching `RiskConfig` numbers, the Toss
adapter, or any Live activation code this phase. Confirmed, unchanged:

- `max_daily_loss=0.02`, `max_turnover=2.0`,
  `max_order_frequency_per_hour=6` remain **PROPOSED / AWAITING USER
  RATIFICATION** — no different value was substituted this phase.
- `evaluate_safety_gate` (`src/broker/live/safety_gate.py`) was not
  modified this phase.
- This phase's own work (`src/strategy_research/walk_forward_evaluation.py`,
  `src/strategy_research/evidence.py`,
  `scripts/run_long_horizon_validation.py`) never reads or writes any
  field in this document's scope — walk-forward/evidence-classification
  infrastructure has no interaction with Live risk policy at all.

## Session 36 — Risk limit values RATIFIED by the user (#1/#6/#7)

The account owner reviewed Phase 22's revised proposals directly and
ratified all three, with one revision:

| # | Field | Phase 22 proposal | **RATIFIED value** |
|---|---|---|---|
| 1 | `LiveTradingConfig.max_daily_loss` | `0.02` (2%) | **`0.05` (5%) of initial capital** — the user explicitly requested a looser figure than Claude's 2% proposal |
| 6 | `RiskConfig.max_turnover` | `2.0` | **`2.0`, accepted as proposed** |
| 7 | `LiveTradingConfig.max_order_frequency_per_hour` | `6` | **`6`, accepted as proposed** |

**Why #1 moved from 2% to 5%, recorded for future reference (not a
technical decision, a stated investment-philosophy one):** the user's
own reasoning was that a price decline in a genuinely good company they
already hold is, in their view, a buying opportunity rather than a loss
to react to — so a tight daily-loss trigger felt, to them, like it
might work against that philosophy. Before ratifying, Claude verified
against `LiveTradingSession.engage_kill_switch`
(`src/broker/live/session.py`) exactly what triggering `max_daily_loss`
does: it cancels only open/pending (not-yet-filled) orders and pauses
further *automated* order submission until a human reviews and calls
`release_kill_switch` — it never sells or liquidates any existing
filled position. This means the trigger does not conflict with the
user's stated philosophy at any value (existing holdings are never
force-sold), so 5% was accepted as the user's own risk-tolerance
choice, not something Claude talked them out of or into. The looser
number simply means the automated system pauses new automated activity
(including any automated additional buying it might otherwise have
attempted that day) at a somewhat larger single-day paper/realized loss
than Claude's original conservative proposal — a manual-review
speed bump on that specific day, not a forced loss.

**Status: RATIFIED (financial-policy decision), not yet CODE-APPLIED.**
No production `LiveTradingConfig`/`RiskConfig` instantiation exists yet
in this codebase — `DEFAULT_LIVE_TRADING_CONFIG` (`src/broker/live/
config.py`) is deliberately left as `LiveTradingConfig()` (all three
fields `None`, `live_trading_enabled=False`), and `RiskConfig`'s own
default likewise leaves `max_turnover=None`, because both are shared
defaults consumed by backtesting/paper-trading code paths as well —
changing either dataclass's default would silently change behavior for
every non-Live consumer, not just a future Live account. There is
still no concrete number for `max_daily_loss` specifically (it is coded
as an absolute `float`, not a ratio — Option A of Phase 17's own
analysis), because **initial Live capital has still not been decided**;
`max_daily_loss = 0.05 * initial_capital` once it is. `max_turnover=2.0`
and `max_order_frequency_per_hour=6` are concrete integers already and
need no further capital decision — they will be passed explicitly at
whatever future point a real `LiveTradingConfig`/`RiskConfig` is first
constructed for actual Live use (still independently blocked today by
the Toss capability gap, `TOSS-API-GAP-ANALYSIS.md`, regardless of this
ratification).

**Remaining open item (resolved below):** initial Live capital amount
— was not decided at the time the table above was written; the user
subsequently stated it in the same session.

### Initial Live capital stated: 3,000,000 KRW

The user stated their initial Live capital target as **3,000,000 KRW**
(300만원). Recorded here using the same pattern
`docs/operations/MARKET-DATA-FX-REFERENCE.md` already established for
Paper Trading's `PAPER_CAPITAL_KRW_STATED_TARGET` — the user's actual
stated figure, in the currency they actually stated it in, never
silently converted.

**Pure arithmetic on the stated KRW figure** (no currency conversion
involved): `max_daily_loss (5%) = 0.05 * 3,000,000 = 150,000 KRW`.

**Why this still does not produce a concrete
`LiveTradingConfig.max_daily_loss` value:** `LiveTradingConfig.max_daily_loss`
is compared against loss computed inside this system's own
`PortfolioAccounting`/risk-evaluation code, which is USD-denominated
throughout (the pilot/research universe is US equities — every price,
position value, and P&L figure this codebase computes is in USD; see
`MARKET-DATA-FX-REFERENCE.md`). Converting "150,000 KRW" into a USD
figure right now would require a real, sourced KRW/USD exchange rate,
which `MARKET-DATA-FX-REFERENCE.md` has documented since Phase 20 as
**not available from this environment** (every FX source checked was
unreachable) — writing in a guessed rate here would be exactly the
fabrication that document already refused to do, and this section does
not do it either.

**Recommended resolution path (not itself a fabricated number):** once
a real Toss Live account actually exists and the stated 3,000,000 KRW
is actually deposited/converted, the account's own real, broker-reported
USD balance at that time is the correct basis for
`max_daily_loss = 0.05 * (that real USD balance)` — not a
speculative conversion computed today with an unverifiable rate. This
also means the exact USD number cannot be finalized until Live account
opening, independently still blocked by the Toss capability gap
(`TOSS-API-GAP-ANALYSIS.md`) regardless.

`docs/operations/MARKET-DATA-FX-REFERENCE.md` is updated alongside this
section to note that its own "when this would actually become
necessary" trigger point — a human reasoning about a real Live capital
figure in KRW terms — has now occurred, without fabricating the rate it
still does not have.

## Session 36 continued — #14 RESOLVED: no withdrawal, full reinvestment

The account owner made the actual decision the design pass above
deliberately did not make: **the account never withdraws capital.
Every realized gain (and, for that matter, the original principal) is
reinvested indefinitely; there is no cash-out event of any kind to
govern.**

This is not a selection among Options A/B/C from the design pass above
— it is the choice that makes all three moot simultaneously, since
each of A/B/C exists to answer "how does a withdrawal happen," and
under this policy a withdrawal never happens at all:

- **Option A's** automated-execution risk (an unattended system moving
  capital OUT on a fixed schedule, including during a drawdown) —
  moot, since nothing is ever scheduled.
- **Option B's** proposal/approval machinery (a new `WithdrawalProposal`
  type, its own approval flow) — moot, since there is nothing to
  propose.
- **Option C's** stale-balance concern (a real withdrawal happening
  out-of-band, leaving `PortfolioAccounting` briefly wrong) — moot,
  since no real withdrawal ever occurs for the accounting to fall
  behind on.

**No code changes as a result.** There is no field, model, or approval
type to add, remove, or wire — the resolved policy is the continued
ABSENCE of a withdrawal capability, exactly what this codebase already
has today. `RiskConfig`/`LiveTradingConfig` are untouched. If this
policy is ever revisited (e.g. the account owner later decides to
withdraw after all), it re-opens exactly the Option A/B/C analysis
already on file above — nothing here forecloses that, it just states
what is actually intended for now.

## Session 36 continued — #15: clarified for the account owner's decision

**What this item actually is, since it's easy to conflate with #9 or
with #14:** #9 (`RiskConfig.minimum_cash_ratio=0.05`) already forces
every BUY to leave at least 5% of portfolio value in cash — but that
number was picked for backtesting realism (Phase 8), never re-examined
for what a real Live account specifically needs cash for. #14 is now
resolved as "never withdraws" — so #15 is NOT "how much cash to keep
on hand to fund withdrawals" (that was Option B below, and #14's
resolution makes it inapplicable). What #15 actually asks is: **does a
real Live account need to hold MORE (or less, or differently-timed)
cash than the backtesting-inherited 5%, for real-world reasons
backtesting never has to deal with** — covering trade settlement
lag, unexpected broker fees, a corporate action cash requirement,
or simply having enough uninvested cash to react to a bad situation
(e.g. a manual emergency exit) without being forced to sell a position
at a bad moment first?

With #14 resolved, only two of the design pass's three options remain
live choices (Option B, tied to a withdrawal schedule, no longer
applies):

- **Option A — keep `0.05` (5%) as-is.** Simplest: no new work, the
  existing Phase 8 default continues to gate Live exactly as it
  already gates Paper/Backtest. The tradeoff already on file still
  applies even without withdrawals: `0.05` was never actually chosen
  WITH a real Live account's own liquidity needs in mind, it just
  happens to also apply there because it is the same field.
- **Option C — a regime-conditional buffer**, holding more cash when
  `regime.enums`'s existing LIQUIDITY/VOLATILITY axes report a less
  favorable state, less otherwise. This reuses an existing, already-
  tested signal (no new data source) but is real, unbuilt design work
  (there is no existing mapping from "which regime state" to "what
  buffer size" anywhere in this codebase) — and, per RULE 0.8's own
  logic applied here, choosing a mapping now, before any real Live
  track record exists to inform it, risks being an unvalidated,
  invented policy dressed up as a design.

**No recommendation is made here** — this remains the account owner's
decision, same as #14 was until just now. See the question asked back
in the same turn as this document update.

## Session 36 continued — Proposed values for #5/#10 (NOT a decision)

Mirroring Phase 20's own framing for #1/#6/#7: what follows is Claude's
reasoned proposal for the account owner to ratify or revise, not a
value this document is deciding unilaterally. **Neither number takes
effect on its own** — a caller must explicitly pass it (`--max-sector-weight`/
`--max-order-notional` on the Paper CLI, or the equivalent `RiskConfig`
fields for Live) before either check enforces anything; both already
default to `None` (disabled) everywhere in this codebase.

### #5 — `RiskConfig.max_sector_weight`

**Proposal: 25% (0.25) of portfolio value in any single sector.**

Grounded in something this project directly observed, not a generic
round number: `size` (a raw-IC-screened factor candidate) briefly
reached `CANDIDATE` evidence level earlier this session before a
concentration-report check found its held-out TEST return was 76.3%
in a single security — an oil-price-supercycle-era energy name. The
universe was subsequently widened (`RESEARCH_UNIVERSE_STAGE4`, ADR-0056)
specifically to thicken the sectors that made that concentration
possible (Energy/Industrials/Utilities/Real Estate/Materials, each to
at least 4 names). 25% is loose enough to allow a real sector tilt
(this is a factor-driven long-only strategy, not an index fund forced
into ~9% equal-sector-weight neutrality across ~11 GICS sectors) while
still structurally ruling out the kind of single-sector concentration
already observed once in this project's own research history.

### #10 — `RiskConfig.max_order_notional`

**Proposal: $1,000 (USD), framed explicitly as an operational
"fat-finger" ceiling, not a portfolio-construction limit.**

This is a different kind of number than #1/#5/#6/#7, which are all
genuine portfolio-risk parameters properly expressed relative to
capital. A per-order absolute-dollar cap serves a narrower purpose:
catching a sizing bug or data error that tries to place one
catastrophically large order, regardless of what the rest of the
portfolio looks like. With initial Live capital stated as a small
3,000,000 KRW (Session 36, above) and the exact USD figure still
pending real FX conversion, $1,000 is proposed as a ceiling clearly
ABOVE any single order this account's real starting size should ever
plausibly place -- so it should essentially never bind in ordinary
operation, only if something is actually wrong. Explicitly flagged for
revisiting once the account's real USD balance is confirmed (same
"revisit once real capital exists" treatment #1 already has above) --
a fixed dollar figure that never binds for a $2,000 account could
easily be far too loose for a much larger one later.

## Session 36 continued — #15 RESOLVED (interim): keep 5%, revisit with real data

The account owner decided: **Option A for now (keep `minimum_cash_ratio=0.05`
unchanged) -- explicitly not a final answer.** On record as a concrete
follow-up, not a vague "someday": once a real Live track record
accumulates, revisit with **Option C, a regime-conditional buffer**
that automatically increases the cash floor when `regime.enums`'s
existing LIQUIDITY/VOLATILITY axes report a less favorable state.

**Deliberately not built now.** Designing the actual mapping from
"which regime state" to "how much extra cash" before any real Live
data exists to inform it would be exactly the premature, unvalidated
policy-tuning RULE 0.8 warns against in the strategy-research context
-- the same caution applies here. The trigger for revisiting this is
explicit: real Live operating history, not a fixed calendar date or
this session ending.

## Session 36 continued — Risk limit values RATIFIED by the user (#5/#10)

The account owner reviewed the proposed values above directly and
ratified both, unchanged:

| # | Field | Proposed | **RATIFIED value** |
|---|---|---|---|
| 5 | `RiskConfig.max_sector_weight` | 25% | **25% (0.25)** |
| 10 | `RiskConfig.max_order_notional` | $1,000 | **$1,000** |

**Status: RATIFIED (financial-policy decision), not yet CODE-APPLIED.**
Same treatment as #1/#6/#7/#11 (ADR-0060/ADR-0065): `RiskConfig`'s own
default remains untouched (still shared with backtest/paper code
paths) -- a human passes `max_sector_weight=0.25`/
`max_order_notional=1000.0` explicitly whenever a real Live `RiskConfig`
is constructed. `max_order_notional`'s own "revisit once real capital
is confirmed" caveat (ADR-0076) still stands -- ratifying the number
now does not freeze it against that future revisit.

## Session 36 continued — Proposed value for #16 (NOT a decision)

Fourth of the 5 items identified from comparing this project against
`dragon1086/prism-insight` (see ADR-0093 for the full technical
account). Mirroring the exact framing #1/#5/#6/#7/#10 already
established: what follows is Claude's reasoned proposal for the
account owner to ratify or revise, not a value this document is
deciding unilaterally. **This number takes effect on nothing by
itself** -- `RiskConfig.reentry_cooldown_days` defaults to `None`
(disabled), and even once set, the check only ever fires on a call
where the caller also supplies `last_exit_time_by_security` -- which no
orchestration code does yet (see the table row above).

### #16 — `RiskConfig.reentry_cooldown_days`

**Proposal: 5 trading days.**

The underlying idea (from `prism-insight`'s own use of a cooldown after
an exit) is to avoid immediately re-buying a security this system just
sold, before enough new information has actually arrived to justify
reversing course -- a guard against whipsaw churn, not a claim that 5
days is empirically optimal for this project's own data (no such study
exists, nor should one be run before ratification -- that would be the
same post-hoc-tuning RULE 0.8 forbids). 5 trading days (roughly one
calendar week) is proposed as a round, conservative starting point:
long enough that a same-day or next-day reversal driven by noise rather
than a genuine new signal is blocked, short enough that it does not
meaningfully constrain a strategy that trades on a `test_window_months`-
scale cadence (this project's walk-forward candidates rebalance every 1-2
months, so a 5-day cooldown is a small fraction of the normal holding
period, not a structural obstacle to any of them). Unlike #1/#5/#6/#7/
#10, this limit is not yet wired to any real trade history at any
orchestration layer -- ratifying the number does not, by itself, make
the check active in Paper or Live trading; that wiring is separate,
future work.
