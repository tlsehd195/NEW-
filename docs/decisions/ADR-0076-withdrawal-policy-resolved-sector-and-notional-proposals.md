# ADR-0076: #14 resolved (no withdrawal); proposed values for #5/#10

**Status:** Accepted (policy documentation; no code change)
**Session:** 36 (continued)

## Context

ADR-0064 enumerated real options for #14 (withdrawal policy) and #15
(Live cash buffer) without picking one, per the user's own "생각이
많이 필요함" framing at the time. This session, the user made the
actual decision for #14, asked for #15 to be explained (not decided
for them), and asked for the remaining open items (#5/#10 numeric
values, plus the architecture questions behind `model_state_valid`/
`configuration_integrity_valid`) to be executed.

## Decision 1 — #14 resolved: no withdrawal, ever

The account owner decided: **the account never withdraws capital; all
realized gains are reinvested indefinitely.** This isn't a selection
among ADR-0064's Options A/B/C -- it is the choice that makes all
three moot at once, since each of them exists to answer "how does a
withdrawal happen," and under this policy no withdrawal ever happens.

No code changes: there is no field, model, or approval type to add --
the resolved policy is the continued ABSENCE of a withdrawal
capability, which is exactly what this codebase already has today.
`docs/operations/LIVE-RISK-POLICY.md` classification for #14 changes
from BLOCKING to RESOLVED.

## Decision 2 — #15 clarified, not decided

`LIVE-RISK-POLICY.md` gained a clarifying explanation (what #15
actually asks, now that #14's resolution removes Option B from
contention) and the two remaining real choices (A: keep the inherited
0.05 floor; C: a regime-conditional buffer reusing existing
LIQUIDITY/VOLATILITY axes) -- still no recommendation, still the
account owner's decision, asked directly in the same turn as this ADR.

## Decision 3 — proposed values for #5/#10, mirroring the Phase 20 pattern

Neither #1/#6/#7's own "Claude proposes, human ratifies" treatment had
ever been extended to #5/#10 (added later, Session 36's ADR-0062/
ADR-0063, as mechanism-only). This ADR extends the same treatment:

- **#5 `max_sector_weight`: proposed 25%** -- grounded directly in this
  project's own research history, not a generic number: `size`
  reached `CANDIDATE` evidence level with a 76.3% single-security
  concentration before a concentration-report check caught it, in the
  same energy sector `RESEARCH_UNIVERSE_STAGE4` was later widened
  specifically to thicken (ADR-0056).
- **#10 `max_order_notional`: proposed $1,000**, explicitly framed as
  an operational fat-finger ceiling (catching a sizing bug or data
  error), not a portfolio-construction limit -- deliberately flagged
  for revisiting once the account's real USD balance is confirmed,
  the same "revisit once real capital exists" treatment #1 already
  has.

Neither number takes effect on its own; both remain `None` (disabled)
in every default config until a human explicitly passes them,
identical to how #1/#6/#7/#11 were already treated before ratification.

## Tests

None -- pure documentation, no code touched.
