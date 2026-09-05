# ADR-0079: #15 (Live cash buffer) resolved, interim: keep 5%, revisit with real data

**Status:** Accepted (policy documentation; no code change)
**Session:** 36 (continued)

## Context

ADR-0076 explained #15 to the account owner (what it actually asks, now
that #14's resolution removes the withdrawal-linked option from
contention) and put the two remaining real choices back to them: keep
the inherited `RiskConfig.minimum_cash_ratio=0.05` floor, or build a
regime-conditional buffer that increases cash reserves in unfavorable
market conditions.

## Decision

**Keep `0.05` for now (Option A) -- explicitly interim, not final.**
The account owner's own framing: once real Live operating data
accumulates, revisit and add the regime-conditional automatic
adjustment (Option C, reusing `regime.enums`'s existing LIQUIDITY/
VOLATILITY axes) at that point.

No code change: `RiskConfig.minimum_cash_ratio` is untouched. Building
Option C's actual regime-to-buffer-size mapping now, before any real
Live track record exists to inform it, would be exactly the kind of
premature, unvalidated policy design RULE 0.8 already warns against for
strategy research -- the same discipline applies to a risk-policy
parameter. The trigger for revisiting is explicit and substantive (real
Live operating history), not a calendar date.

`LIVE-RISK-POLICY.md` classification for #15 changes from "INHERITED,
needs Live-specific re-examination" to RESOLVED (interim) -- both #14
and #15 are now resolved, closing out the last of the items this
session's "정말 남은 거 2개 맞아?" audit surfaced.

## Tests

None -- pure documentation, no code touched.
