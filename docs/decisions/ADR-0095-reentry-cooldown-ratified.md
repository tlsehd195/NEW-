# ADR-0095: #16 reentry cooldown value RATIFIED by the user

**Status:** Accepted
**Session:** 36 (continued)

## Context

ADR-0093 proposed `RiskConfig.reentry_cooldown_days=5` (#16), mirroring
the #1/#5/#6/#7/#10/#11 "Claude proposes, human ratifies" pattern
(ADR-0060/ADR-0080). The account owner reviewed and approved the value,
unchanged.

## Decision

| # | Field | Proposed | **RATIFIED value** |
|---|---|---|---|
| 16 | `RiskConfig.reentry_cooldown_days` | 5 trading days | **5 trading days** |

Same treatment as every earlier ratified item: `RiskConfig`'s own
default is untouched (`reentry_cooldown_days` stays `None`, still
shared with backtest/paper code paths) -- a human passes
`reentry_cooldown_days=5` explicitly whenever a real Live `RiskConfig`
is constructed. `LIVE-RISK-POLICY.md` item #16's classification changes
from "proposed, awaiting ratification" to "RATIFIED, not yet
code-applied."

**A second gap remains that #1/#5/#6/#7/#10/#11 did not have**: even
once `reentry_cooldown_days=5` is passed to a real `RiskConfig`, the
check in `PortfolioRiskEngine.assess` does nothing unless the caller
also supplies `last_exit_time_by_security` on every call -- and no
orchestration layer (`orchestration.paper_runner`/`orchestration.
live_runner`) populates that mapping from real Trade Journal history
yet (ADR-0093). Ratifying the number here settles the policy question;
it does not make the limit active anywhere by itself. That wiring, plus
running the shadow-evaluation harness (ADR-0094) against real trade
history before this limit ever gates a real order, remains separate,
future work.

## What this does NOT do

Does not change `RiskConfig`'s default field values. Does not wire
`last_exit_time_by_security` into any orchestration code path. Does not
activate Live trading (independently still blocked by the Toss
capability gap, `TOSS-API-GAP-ANALYSIS.md`, item B).

## Tests

None -- pure documentation, no code touched (the infrastructure and its
tests were already built and verified in ADR-0093).
