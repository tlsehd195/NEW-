# KRW/USD FX Reference (Phase 20, instruction section 14)

## Phase 22 update: USD-denominated Paper account chosen — no rate needed for Paper Trading

Phase 22's instruction reaffirmed the same constraint below (no
verified real-time or dateable KRW/USD rate is accessible from this
environment) and explicitly permitted an alternative to filling in this
document with a rate at all: standing up the Paper Trading account
natively in USD instead of converting a KRW figure. **That is the path
taken.**

`src/broker/paper/us_longterm_config.py`'s `PAPER_CAPITAL_USD = 10_000.0`
is the resulting reference Paper capital — an explicitly-labeled,
round, order-of-magnitude USD stand-in for the user's stated
`10,000,000` KRW target, **not a currency conversion**. It carries no
implied exchange rate, and nothing in this codebase treats it as one.
`PAPER_CAPITAL_KRW_STATED_TARGET = 10_000_000.0` is recorded alongside
it purely for traceability back to the user's actual stated figure —
never used in any arithmetic.

This document's own "no rate recorded" status (below) is **unchanged**
by this decision — choosing the USD-account path this phase does not
resolve the underlying FX-access gap, it routes around needing to
resolve it for Paper Trading specifically. If Live Trading is someday
seriously planned against a real KRW Toss account, this document's
placeholder table still needs a real, sourced rate filled in at that
time — see "When this would actually become necessary" below, also
unchanged.

## Status: no rate recorded — placeholder only

This document exists because a real Toss Securities account (the
eventual Live Trading target, still fully BLOCKED — see
`docs/operations/TOSS-API-GAP-ANALYSIS.md` and
`docs/operations/LIVE-TRADING-RUNBOOK.md`) is KRW-denominated while this
system's own price data, `PortfolioAccounting`, and every backtest/paper
metric are USD-denominated (the pilot universe is US equities — ADR-0025
/ `MARKET-DATA-PROVIDER.md`). A KRW/USD figure will eventually be useful
for **human-facing discussion only** — e.g. translating a proposed
`max_daily_loss` risk limit (`docs/operations/LIVE-RISK-POLICY.md`'s
open DECISION REQUIRED item) between the two currencies a human is
actually thinking in.

**No exchange-rate value is recorded here.** Every FX data source domain
checked this session was unreachable from this environment (the same
`EGRESS_BLOCKED` pattern documented in ADR-0025 for market-data
providers and in `TOSS-API-GAP-ANALYSIS.md` for Toss itself), and this
model has no way to independently verify a *current* KRW/USD rate as of
the session's actual date. Writing in a plausible-sounding number here
would be exactly the "pretend to have a real-time rate" this
instruction explicitly forbids — a rate that is wrong by an unknown,
unstated margin is worse than an honestly empty field, since it invites
being trusted.

## How to fill this in (for a human, or a future session with verified access)

When a real reference value is needed:

1. Obtain it from a citable, dateable source (e.g. a central bank
   published rate, a major exchange's daily reference rate) — not a
   live trading quote, since this value is explicitly **reference-only,
   not a live/tradeable rate**.
2. Record it in the table below with the source and retrieval date.
3. Every consumer of this value (documentation, a risk-policy
   discussion, a human sizing a KRW-denominated limit) must treat it as
   a stale snapshot, never as current market truth, and re-check it
   before relying on it for anything with real financial consequence.

| Field | Value |
|---|---|
| KRW per USD | **UNKNOWN — not recorded** |
| Source | *(fill in: e.g. Bank of Korea, ECB reference rate, exchange daily close)* |
| Retrieved | *(fill in: date the value was actually read from the source)* |
| Reference-only | Yes — never a live/tradeable rate |

## What this is explicitly NOT

- **Not** wired into any code path. No file in `src/` reads this
  document or performs a KRW/USD conversion anywhere in this
  repository, as of Phase 20.
- **Not** a fix for the pre-existing `currency="KRW"` label on
  `PaperBrokerAdapter.get_account()`'s `BrokerAccountSnapshot`
  (`src/broker/paper/adapter.py`, inherited from an earlier phase,
  unmodified this phase per the "never arbitrarily change Phase 0-19
  source behavior" rule). That label is a simulated-account currency
  tag; the cash figure it labels is numerically tracked in the same
  units as the USD-priced securities `PortfolioAccounting` holds. No
  currency conversion is actually applied anywhere in that path today —
  this is a known, pre-existing simplification, not a Phase 20 finding
  to silently paper over, and not something this phase's additive-only
  mandate authorizes changing in `broker.paper.*`.
- **Not** required for Paper Trading, backtesting, or any Phase 20
  deliverable to function — every one of them already operates entirely
  in USD.

## When this would actually become necessary

Only once Live Trading is seriously being planned against a real KRW
Toss account (itself BLOCKED regardless — see
`docs/operations/LIVE-TRADING-RUNBOOK.md`'s unmet-conditions list) and a
human needs to reason about a risk limit or capital figure in KRW
terms. Until then this remains an intentionally empty placeholder.
