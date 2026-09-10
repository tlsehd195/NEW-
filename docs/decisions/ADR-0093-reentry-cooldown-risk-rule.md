# ADR-0093: Reentry cooldown risk rule -- infrastructure built, number PROPOSED not ratified

**Status:** Accepted (infrastructure); the numeric threshold is PROPOSED, not ratified
**Session:** 36 (continued)

## Context

Fourth of the 5 items identified from comparing this project against
`dragon1086/prism-insight` (see ADR-0090's Context for the full
background), per the account owner's "전부 적용" instruction:
`prism-insight` enforces a cooldown period after exiting a position
before re-entering it, to avoid immediately reversing a just-made exit
decision on noise rather than genuinely new information.

This project's own constitutional principle -- risk limits are not
self-modified by AI, established earlier this session when a request to
raise `max_sector_weight` from 25% to 45% was declined -- applies here
directly: a reentry-cooldown period is a real risk-policy number, and
this ADR does not choose one unilaterally. It builds the infrastructure
(inert by default) and proposes a number through the same
PROPOSED-then-ratified process `LIVE-RISK-POLICY.md` items #1/#5/#6/#7/
#10 already went through.

## Decision

**Schema**: `trade_journal.models.TradeRecord.exit_reason: Optional[str]
= None` (additive) -- this project previously had no way to distinguish
a normal strategy-driven SELL from a risk-engine-forced exit
(stop-loss, risk-limit breach), a gap that must close before a
cooldown rule can ever be selective about which exits trigger it.
Free-text/tag, not an Enum -- whoever converts a `Fill` into a
`TradeRecord` decides the vocabulary. Plumbed through as an optional
passthrough parameter in `InMemoryTradeJournalRepository.record_trade`,
`DuckDBTradeJournalRepository.record_trade` (round-trips via
`payload_json`, no new SQL column -- this project's "additive schema
via a new Optional field, never `ALTER TABLE`" convention), and both
`broker.paper.journal.build_trade_record`/`broker.live.journal.
build_trade_record` bridges. No producer populates it with real
classification logic yet -- that is future work, once a real caller
needs it.

**Risk config**: `risk.config.RiskConfig.reentry_cooldown_days:
Optional[int] = None` -- `None` means "not enforced," the same
convention `max_turnover`/`max_sector_weight` already established.
Validated positive when set.

**Enforcement**: `PortfolioRiskEngine.assess` gains a new opt-in
parameter, `last_exit_time_by_security: Optional[dict[str, datetime]] =
None`. When `config.reentry_cooldown_days` is set AND the caller
supplies this mapping AND `security_id` is a key in it, a new BUY is
REJECTed (`reentry_cooldown_breached`) if fewer than
`reentry_cooldown_days` days have elapsed since the recorded exit;
otherwise unaffected. Like every other limit in this function, only a
new BUY is gated -- HOLD/NO_TRADE and any SELL/EXIT pass through
unchanged.

**Deliberately mirrors `liquidity_state`'s opt-in pattern, NOT
`sector_by_security`'s fail-closed pattern** -- this is the one real
design decision in this ADR, so it is explained rather than just
stated: `sector_by_security` fails closed (REJECTs) when the mapping or
this security's entry is missing, because every real security SHOULD
have a knowable sector -- an absence there really is missing data.
"This security has no recorded recent exit" is different: it is the
OVERWHELMINGLY common, entirely legitimate state for any fresh entry or
long-held position, not a data gap. Fail-closed on it would REJECT
essentially every first-time BUY the moment `reentry_cooldown_days` is
set but a caller has not (yet) wired up exit-history tracking --
exactly the wrong behavior for what this limit is meant to do. So a
security absent from the mapping, or the mapping itself being `None`
entirely, both PASS -- matching `liquidity_state`'s own documented
"enforced only when the caller supplies it for this call, simply
skipped otherwise" precedent instead.

**Proposed number (NOT ratified)**: 5 trading days, recorded in
`LIVE-RISK-POLICY.md` item #16 with full rationale -- a round,
conservative "avoid same-week whipsaw re-entry" starting point, not
claimed empirically optimal for this project's own data (no such study
was run, nor should one be, per RULE 0.8). Explicitly NOT wired into
any orchestration layer's default -- `RiskConfig.reentry_cooldown_days`
stays `None` until a human ratifies a number, mirroring #1/#5/#6/#7/#10's
own "ratified but not baked into the default config" treatment.

## What this does NOT do

Does not choose a ratified cooldown number -- 5 days is PROPOSED only,
awaiting the account owner's explicit ratify-or-revise decision, same
as every other numeric risk policy item in this document's history.
Does not decide which `exit_reason` values should even count toward the
cooldown (e.g., should a discretionary profit-take exit trigger the
same cooldown as a stop-loss? Not decided here -- the current
implementation cools down after ANY recorded exit the caller reports,
regardless of reason, since no orchestration layer populates
`last_exit_time_by_security` from real history yet to make that
distinction meaningful). Does not wire `last_exit_time_by_security`
into `orchestration.paper_runner`/`orchestration.live_runner` from real
Trade Journal history -- that integration (querying recent trades per
security and building the mapping each cycle) is separate, future work,
tracked as an open item in `LIVE-RISK-POLICY.md`. Does not implement
the 5th `prism-insight`-derived item (shadow-evaluation harness --
tracked separately, and per the account owner's own precedent for this
project's governance discipline, likely the natural first candidate to
shadow-test once the orchestration wiring above exists).

## Tests

`tests/risk/test_engine.py::TestReentryCooldown` (7 tests): a recent
exit within the window REJECTs; exactly at the boundary (`days_since_
exit == reentry_cooldown_days`) is no longer blocked (strict `<`,
verified against one day short of the boundary too); an exit past the
window PASSes; a security absent from the mapping is not gated (the
ordinary case); an omitted mapping entirely is not gated even with the
limit configured; the limit not being configured skips the check even
with a recent exit supplied; HOLD/SELL are never blocked by the
cooldown. `tests/risk/test_engine.py::TestInvalidConfiguration::
test_risk_config_rejects_non_positive_reentry_cooldown_days`.
`tests/trade_journal/`, `tests/storage/test_trade_journal_persistence.py::
test_exit_reason_survives_restart`, `tests/broker/paper/
test_paper_journal.py`, `tests/broker/live/test_live_journal.py` --
`exit_reason` passthrough and DuckDB round-trip. Full suite re-run, all
tests pass.
