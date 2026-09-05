# ADR-0080: #5/#10 risk limit values RATIFIED by the user

**Status:** Accepted
**Session:** 36 (continued)

## Context

ADR-0076 proposed `max_sector_weight=25%` (#5) and `max_order_notional=$1,000`
(#10), mirroring the #1/#6/#7 "Claude proposes, human ratifies" pattern
(ADR-0060). The account owner reviewed and approved both, unchanged.

## Decision

| # | Field | Proposed | **RATIFIED value** |
|---|---|---|---|
| 5 | `RiskConfig.max_sector_weight` | 25% | **25% (0.25)** |
| 10 | `RiskConfig.max_order_notional` | $1,000 | **$1,000** |

Same treatment as #1/#6/#7/#11 (ADR-0060/ADR-0065): `RiskConfig`'s own
default is untouched (still shared with backtest/paper code paths, per
ADR-0060's own precedent for why) -- a human passes
`max_sector_weight=0.25`/`max_order_notional=1000.0` explicitly
whenever a real Live `RiskConfig` is constructed. `LIVE-RISK-POLICY.md`
classification for both changes from "proposed, awaiting ratification"
to "RATIFIED, not yet code-applied."

`max_order_notional`'s own "revisit once real capital is confirmed"
caveat (ADR-0076) still stands -- ratifying the number now does not
freeze it against that future revisit once the account's real USD
balance is known.

## What this does NOT do

Does not change `RiskConfig`'s default field values. Does not activate
Live trading (independently still blocked by the Toss capability gap,
`TOSS-API-GAP-ANALYSIS.md`, item B). Does not resolve item B (Toss
operational verification / KRW-USD FX), which remains explicitly
deferred by the account owner's own instruction.

## Tests

None -- pure documentation, no code touched.
