# ADR-0096: Reentry cooldown wired into Paper/Live orchestration from real Trade Journal history

**Status:** Accepted
**Session:** 36 (continued)

## Context

ADR-0093 built the reentry-cooldown infrastructure (`RiskConfig.
reentry_cooldown_days`, `PortfolioRiskEngine.assess`'s opt-in
`last_exit_time_by_security` parameter, `TradeRecord.exit_reason`) but
explicitly left one gap open: "no caller yet populates `last_exit_
time_by_security` from real trade history at any orchestration layer."
ADR-0095 then ratified the proposed value (5 trading days), but noted
ratifying the number does not make the limit active anywhere by
itself. The account owner asked directly for this wiring ("배선 해").

## Decision

`orchestration.paper_runner.run_cycle` and `orchestration.live_runner.
run_cycle` both gain a new opt-in parameter, `trade_journal_repository`,
typed against a new narrow `TradeJournalReader` Protocol (`list_trades`
only) -- each module defines its own copy, per the existing "no
cross-import between paper_runner and live_runner" discipline this
project already established for `_reference_price`/`_PRICE_LOOKBACK_DAYS`.

When supplied, a new `_last_exit_time_by_security` helper (also one
copy per module, same reasoning) queries `list_trades(security_id=...,
provenance=..., end=as_of_time)` once per security -- point-in-time
safe, a trade dated after the current checkpoint is never queried at
all -- and returns the most recent FULL exit's timestamp per security.
This mapping is passed straight through to `risk_engine.assess` as
`last_exit_time_by_security`, exactly mirroring `sector_by_security`'s
existing opt-in wiring pattern in both files.

**Only a FULL exit counts, a decision made here rather than left
ambiguous**: `side == OrderSide.SELL` AND `position_after == 0.0`. A
partial trim that still leaves a nonzero position is ordinary
rebalancing, not the "reentry" the cooldown concept is about -- a
security cannot be "reentered" while a position in it is still held.
This is an engineering/behavioral decision, not a risk-policy NUMBER,
so it did not require the same ratify-by-the-account-owner process
ADR-0093/ADR-0095's numeric proposals did (the same distinction this
project already draws between Claude deciding a factor's exclusion
rules vs. a human ratifying a risk limit's value).

`None` (the default, omitted parameter) means exactly what it already
means to `risk_engine.assess` directly: the check is simply not
evaluated for that call -- a caller that has not wired up a Trade
Journal repository sees no behavior change at all, same as before this
ADR.

## What this does NOT do

Does not change any risk-policy number -- `RiskConfig.reentry_cooldown_
days` still defaults to `None`; a human still must pass `reentry_
cooldown_days=5` explicitly for the check to ever fire, exactly as
ADR-0095 already established. Does not decide which `exit_reason`
values should count toward the cooldown (ADR-0093's own open question)
-- this wiring counts ANY full exit regardless of `exit_reason`,
consistent with that ADR's own stated scope. Does not run the
shadow-evaluation harness (ADR-0094) against this real wiring to
accumulate evidence before the limit is actually turned on in a real
Paper/Live run -- that remains a separate, deliberate next step, not
bundled into this wiring change.

## Tests

`tests/orchestration/test_paper_runner.py::TestReentryCooldownPropagatesThroughTheWholeChain`
(4 tests) and `tests/orchestration/test_live_runner.py::TestReentryCooldownPropagatesThroughTheWholeChain`
(3 tests), both using a real `InMemoryTradeJournalRepository` populated
via the normal `record_decision`/`record_trade` flow (never a
hand-constructed fake matching only what the test expects): a recent
full exit correctly REJECTs a new BUY end to end (through Order
Validation, no submission reaches the broker/session); an exit outside
the cooldown window does not reject; a partial exit (nonzero `position_
after`) does not count even if very recent; omitting `trade_journal_
repository` entirely leaves behavior unchanged even with `reentry_
cooldown_days` configured. All existing orchestration tests (including
both boundary-scan test files) continue to pass unmodified. Full suite
re-run, 2527 tests pass.
