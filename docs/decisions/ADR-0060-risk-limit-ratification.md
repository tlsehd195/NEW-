# ADR-0060: risk limit values #1/#6/#7 ratified by the user

**Status:** Accepted
**Session:** 36

## Context

`docs/operations/LIVE-RISK-POLICY.md` had carried `max_daily_loss`,
`max_turnover`, and `max_order_frequency_per_hour` as Claude-proposed,
human-unratified numbers since Phase 20/22 (`0.02`, `2.0`, `6`
respectively after Phase 22's revision). This was a standing
DECISION REQUIRED item -- explicitly not something this project's
discipline permits an AI to decide unilaterally (PROJECT_MASTER_PLAN.md
section 13.12).

The account owner reviewed the three proposals directly this session
and ratified all three, revising `max_daily_loss` upward from Claude's
2% proposal to 5%, based on their own stated investment philosophy: a
price decline in a genuinely good company they already hold is a
buying opportunity, not a loss to react to, so they wanted more room
before the kill switch pauses automated activity.

Before accepting that revision, Claude verified (not assumed) exactly
what `max_daily_loss` triggering does, reading
`LiveTradingSession.engage_kill_switch` (`src/broker/live/session.py`):
it cancels only open/pending orders and pauses further automated order
submission pending human review (`release_kill_switch`) -- it never
sells or liquidates existing filled positions. This confirmed the
user's philosophy and the kill switch's actual behavior do not
conflict at any threshold value, so 5% is the user's own risk-tolerance
choice, not a technical correction of a misunderstanding.

## Decision

Recorded in `docs/operations/LIVE-RISK-POLICY.md` (new "Session 36 --
Risk limit values RATIFIED by the user" section):

- `LiveTradingConfig.max_daily_loss` = **5% of initial capital**
  (ratified value, revised from Claude's 2% proposal at the user's
  explicit request). Still cannot become a concrete `float` until
  initial Live capital is decided -- the field is coded as an absolute
  amount, not a ratio.
- `RiskConfig.max_turnover` = **2.0** (ratified as proposed).
- `LiveTradingConfig.max_order_frequency_per_hour` = **6** (ratified
  as proposed).

## What this deliberately does NOT do

- **Does not change any code default.** `DEFAULT_LIVE_TRADING_CONFIG`
  (`src/broker/live/config.py`) and `RiskConfig`'s own default remain
  untouched (`max_daily_loss=None`, `max_turnover=None`,
  `max_order_frequency_per_hour=None`). No production
  `LiveTradingConfig`/`RiskConfig` instantiation exists anywhere in
  this codebase yet -- both dataclasses' defaults are shared by
  backtesting and paper-trading code paths too, so writing a ratified
  Live-specific number into either default would silently change
  behavior for every non-Live consumer. The ratified values will be
  passed explicitly whenever a real Live config is first constructed,
  not before.
- **Does not decide initial Live capital.** `max_daily_loss` remains a
  ratio (5%) until that separate, still-open decision is made.
- **Does not affect whether Live can activate today.** The Toss
  capability gap (`TOSS-API-GAP-ANALYSIS.md`) independently and
  unconditionally blocks Live activation regardless of this
  ratification.

## Session 36 continued: initial Live capital stated (3,000,000 KRW)

The user then stated their initial Live capital target directly:
3,000,000 KRW. Recorded in `LIVE-RISK-POLICY.md` using the same
"stated target, not a conversion" pattern
`MARKET-DATA-FX-REFERENCE.md` already established for Paper Trading's
`PAPER_CAPITAL_KRW_STATED_TARGET`. Pure arithmetic on the KRW figure
gives `max_daily_loss (5%) = 150,000 KRW` -- but this still cannot
become the concrete USD `float` `LiveTradingConfig.max_daily_loss`
needs, because this codebase's loss computation is USD-denominated
throughout and no verified KRW/USD rate is accessible from this
environment (`MARKET-DATA-FX-REFERENCE.md`, unchanged status since
Phase 20/22). Fabricating a rate to finish the arithmetic was
explicitly rejected, matching that document's own standing refusal to
do so.

**Resolution path recorded, not itself a fabricated number:** once a
real Toss Live account opens and the stated KRW is actually
deposited/converted, the account's own real, broker-reported USD
balance at that time is the correct basis for
`max_daily_loss = 0.05 * (real USD balance)`. `MARKET-DATA-FX-REFERENCE.md`
was updated to note its own "when this would become necessary" trigger
has now occurred, while still leaving its rate table unfilled.

## Tests

None -- this is a documentation-only ratification of a financial
policy value; no code changed. Full suite: unchanged at 2267 passed.
