# ADR-0148: MEDIUM/LOW-severity fixes from the same external verification report as ADR-0147

**Status:** Accepted
**Date:** 2026-09-17
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0147-fix-workflow-secrets-in-if-and-adr-duplicate-numbering.md`
(the HIGH-severity fixes from the same report), `docs/decisions/ADR-0136`
(mark_to_market wiring), `docs/decisions/ADR-0137` (advance_simulation
wiring), `docs/decisions/ADR-0115` (initial-capital routing precedent)

---

## Context

Continuing the same uploaded external verification report ADR-0147
addressed HIGH-1/HIGH-2 from. This ADR covers the report's remaining
MEDIUM-1, MEDIUM-2, MEDIUM-3, LOW-1, and LOW-2 findings, each verified
independently before acting (per this project's own established
discipline) rather than applied at face value.

## MEDIUM-1: `mark_to_market`'s `missing` return value was discarded

`orchestration.paper_runner.run_cycle`'s own unconditional
`mark_to_market` call (ADR-0136) discarded its second return value
entirely -- a held security with no real price this cycle silently
fell back to average-cost valuation with zero signal anywhere.

**Fix:** `PaperRunnerState` gained `mark_to_market_missing: list[tuple[
datetime, tuple[str, ...]]]`. `run_cycle` now appends to it (when
`state` is supplied and the list is non-empty) instead of discarding
it. `scripts/run_paper_trading_cycle.py` and `scripts/run_multi_strategy_
paper_trading_cycle.py` both print a warning and write it into their
own report JSON (`mark_to_market_missing` field) -- the same "never let
a real issue arrive with zero signal" treatment `ingest_real_market_
data.py`'s own `missing_symbols` print already gets. `state=None`
callers are unaffected (matches `value_history`'s own existing opt-in
pattern).

Tests: `tests/orchestration/test_paper_runner.py::
TestMarkToMarketAccounting` (+2 tests).

## MEDIUM-2: the per-bar participation cap was per-ORDER, not per-BAR

`broker.paper.execution.simulate_fill` recomputed `max_fillable =
floor(bar.volume * max_participation)` fresh on every call, with no
memory of what another order already consumed from the SAME bar.
ADR-0137's own `advance_simulation` wiring made this newly reachable:
a still-open order retried alongside a freshly-submitted order for the
same security could each independently claim the full participation
share, doubling the real per-bar cap.

**Fix:** `PaperBrokerAdapter` now tracks cumulative filled quantity per
`(security_id, bar.available_time, bar.timestamp)`
(`_bar_participation_consumed`) and passes it to `simulate_fill`'s new
`already_consumed_this_bar` parameter, which subtracts it from
`max_fillable`. Keyed on the SAME `(available_time, timestamp)` tuple
`PaperMarketDataSource.get_reference_bar` itself uses to pick "the"
bar -- **not** `bar.timestamp` alone, which the first version of this
fix used and which broke two existing integration tests
(`test_paper_performance_scenarios.py`/`test_paper_learning_readiness_
lineage.py`'s own `TestScenarioB_*`): those fixtures build two
genuinely different bars (different `close`/`volume`, meant to
represent different trading days) that happen to share `make_bar`'s
default `timestamp` while varying only `available_time` -- a
convention several existing test fixtures already rely on. Confirmed
by re-running the full suite after the first key choice, seeing the
two failures, root-causing them to this exact fixture pattern (not a
logic error in the participation-cap arithmetic itself), and switching
to the data source's own disambiguating key instead of narrowing the
fix's scope or rewriting the fixtures.

Deliberately **process-local**, matching `PortfolioAccounting.
_valuation_history`'s own disclosed scope: `restore_fill` (restart
rehydration) does not repopulate it, since a bare `Fill` does not carry
the bar's own `timestamp`/`available_time` distinctly from
`execution_time`. Documented as a narrower, disclosed residual in
ADR-0137's own "Update" section, not a new gap this fix introduced.

Tests: `tests/broker/paper/test_paper_adapter.py::
TestParticipationCapSharedAcrossOrdersInTheSameBar` (+3 tests).

## MEDIUM-3: `--initial-capital` default -- verified NOT a bug

The report claimed `scripts/run_paper_trading_cycle.py`'s
`--initial-capital` default (1,000,000.0) is inconsistent with
ADR-0115's $10,000 figure. Verified directly against
`scripts/run_multi_strategy_paper_trading_cycle.py:326-333` (the script
ADR-0115 actually fixed): the $10,000 figure (`PAPER_CAPITAL_USD`,
ADR-0028) is deliberately routed ONLY to `PaperStrategyKind.BUY_AND_HOLD`
-- every `run_cycle`-kind strategy, even inside the multi-strategy
script itself, falls back to `PaperTradingConfig().initial_cash`
(1,000,000.0), the exact same value `run_paper_trading_cycle.py`
already uses for its own (always `run_cycle`-kind, "baseline_rule")
strategy. `PAPER_CAPITAL_USD` is ADR-0028's own reference figure
specifically for the US-long-term/`buy_and_hold` operating model, not a
project-wide standard -- `run_paper_trading_cycle.py` never runs that
strategy kind, so there is no real mismatch. **No code change made.**

## LOW-1: `_equity_history`/`_reconstruct_value_history` duplicated a third time

The same risk-snapshot reconstruction logic existed independently in
`scripts/run_paper_trading_cycle.py` (`_equity_history` +
`_reconstruct_value_history`), `scripts/generate_paper_performance_
tearsheet.py` (`_equity_history`), and `scripts/run_multi_strategy_
paper_trading_cycle.py` (`_reconstruct_value_history`) -- three
independently-written copies of the same query + reconstruction.

**Fix:** promoted to one shared `orchestration.paper_runner.
equity_history_from_risk_repository(risk_repository,
representative_security_id, *, up_to=None)`. All three scripts now
import and call it; each local copy removed. Behavior is a strict
superset of the least-safe original (always sorts by `as_of_time`,
matching the tearsheet script's own already-safer version rather than
`run_paper_trading_cycle.py`'s original unsorted version).

Tests: no new tests needed -- existing CLI-level tests for all three
scripts already exercise this path; full suite re-run confirms no
behavior change.

## LOW-2: Discord truncation measured Python codepoints, not UTF-16 code units

`notifications.discord_webhook.truncate_for_discord` compared
`len(content)` (Python codepoints) against Discord's documented 2000-
character limit. Verified via web search (not assumed): Discord, like
most JS-originated web APIs, measures string length the same way
JavaScript's `.length` does -- UTF-16 code units. A character outside
the Basic Multilingual Plane (most emoji, U+10000+) is one Python
codepoint but two UTF-16 code units, so `len()` under-counts exactly
those characters. Every report this module formats today has at most
one such character, so this was harmless in practice, but a future
formatter combining several near the boundary could silently exceed
the real limit and get a genuine HTTP 400.

**Fix:** new `_utf16_length()` helper (`len(s.encode('utf-16-le')) //
2`); `truncate_for_discord` now compares against it and truncates by
iterating codepoints (each already a complete, valid character) while
tracking the running UTF-16 count, stopping before any codepoint that
would exceed budget -- never splits a surrogate pair.

Tests: `tests/notifications/test_discord_webhook.py::
TestTruncateForDiscord` (+3 tests: astral character correctly counted
as 2 units, content that fits by UTF-16 count but not by naive
codepoint-vs-limit comparison is left unchanged, truncation never
produces an unpairable surrogate).

## Tests (all findings combined)

Full suite re-run clean after every fix in this ADR: 3155 passed (up
from 3147 before this batch -- 8 new tests: 2 MEDIUM-1, 3 MEDIUM-2, 3
LOW-2).

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed. MEDIUM-3
required no code change (verified not a real inconsistency).
