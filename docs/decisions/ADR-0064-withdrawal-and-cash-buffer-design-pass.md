# ADR-0064: design pass for withdrawal policy (#14) and Live cash buffer (#15) -- no decision made

**Status:** Accepted (documentation only -- no code)
**Session:** 36

## Context

The last item of a 3-part risk-infrastructure request this session
(after ADR-0062's sector exposure limit and ADR-0063's order notional
cap / consecutive-failure observability). Items #14/#15 had stood in
`LIVE-RISK-POLICY.md` since an earlier session as "raised
conversationally, listed only, not analyzed or proposed yet" -- the
user's own explicit instruction at the time was to record them without
resolving them. This session's instruction asked to proceed on them,
but as a design pass specifically ("생각이 많이 필요함" -- this needs
a lot of thought) -- the opposite of a quick number to fill in.

## Decision

Added a new "Session 36 — Design pass for #14/#15" section to
`LIVE-RISK-POLICY.md`, enumerating real, differently-shaped options
for both items (the actual missing piece the earlier placeholders
named: "Options: not yet enumerated"):

**#14 (withdrawal policy)**: three options analyzed on their own
merits -- (A) a fixed schedule the system executes automatically, (B)
a rule-based policy a human pre-approves with each specific withdrawal
still requiring its own separate human approval (mirroring
`LiveActivationApproval`'s existing two-layer governance shape), (C)
purely manual/out-of-band withdrawal the system never observes. Each
option's real tradeoffs are stated, including a genuine architectural
finding: this project's existing governance pattern (every capital-
affecting capability requires a human to approve the specific action,
not just a standing policy that permits it) makes Option A a weaker
safeguard than the precedent this codebase has established everywhere
else, not merely a stylistic difference.

**#15 (Live cash buffer)**: three options -- (A) keep the current
static `minimum_cash_ratio=0.05` floor unchanged, (B) size the buffer
off #14's actual resolved withdrawal schedule (explicitly gated by
#14 being decided first -- cannot be sized against an undefined
mechanism), (C) a regime-conditional buffer reusing the existing
Phase 5 regime-detection subsystem's LIQUIDITY/VOLATILITY axes rather
than inventing a new signal.

## What this deliberately does NOT do

- **Does not pick an option for either item.** No recommendation is
  given for #14 or #15 -- unlike #1/#6/#7's Phase 20 treatment (which
  gave Claude's own reasoned proposal for the user to ratify or
  revise), these two remain genuinely open with no default steer,
  matching the user's own "생각이 많이 필요함" framing.
- **Does not change any code.** `RiskConfig.minimum_cash_ratio` is
  untouched; no withdrawal-related field, model, module, or approval
  type is added to `src/`.
- **Does not build the "Withdrawal Proposal" module Option B
  describes**, even though that option is analyzed in detail -- it
  remains a real possibility for a future session IF #14 is ever
  actually decided in that direction, not something to build
  speculatively now.

## Consequences

- `LIVE-RISK-POLICY.md` items #14/#15 remain open DECISION REQUIRED
  items -- their status is unchanged (still not ratified, still
  independently moot while the Toss capability gap blocks Live
  regardless) -- only the depth of analysis backing them changed.
- A future session that revisits #14/#15 has the actual option space
  and their tradeoffs already laid out, rather than starting from "not
  yet enumerated" again.

## Tests

None -- documentation-only change, no code touched. Full suite:
unchanged at 2293 passed.
