# ADR-0175: Fail real ingestion runs on unexplained zero-bar symbols (independent audit P1-1)

**Status:** Accepted
**Date:** 2026-09-19
**Deciders:** Claude Code (session continued), account owner (had a
separate AI perform an independent adversarial audit of this project,
asked this session to first independently verify its findings, then
"순서대로 고쳐" -- fix them in order, this is the first of three)

## Context

The account owner supplied an independent audit report (from a
different AI) covering this project's real code, not just its docs.
Before changing anything, this session independently re-read the cited
source and confirmed the report's P1-1 finding was real, not a
misreading:

- `src/data_infra/providers/fallback.py`'s `FallbackDataProvider.fetch()`
  returns the FIRST provider's response as soon as that provider does
  not raise -- including an empty `[]` list. Its own module docstring
  claims "No silent 'success' fabrication... never returns an empty
  list or partial data presented as complete," but that claim only
  actually holds for the all-tiers-raised-an-exception path; a tier
  that returns `[]` without raising short-circuits the whole chain.
- `src/data_infra/provider.py`'s `IngestionRunner._ingest_one()` returns
  `IngestionRecordResult(security_id, IngestionStatus.SUCCESS,
  len(new_bars), None)` unconditionally once `normalize()`/
  `append_bars()` succeed, even when `len(new_bars) == 0`.
  `_resolve_overall_status()` has no concept of "successful but empty."

The consequence: `scripts/ingest_real_market_data.py` (the flagship
real-ingestion script) could exit 0 for a run where a requested symbol
silently got zero bars for a reason that was never actually a
legitimate market closure -- and nothing in the manifest or the exit
code distinguished that from an ordinary, correct holiday-only run.

**A naive fix was considered and rejected before writing any code**:
making `FallbackDataProvider.fetch()` treat any empty, non-exception
response as a failure and fall through to the next tier. This was
rejected because it introduces a real regression -- on a genuine market
holiday, EVERY tier legitimately and correctly returns `[]`, and this
fix would turn that completely normal situation into a fabricated
`PermanentProviderError`. The same reasoning rules out changing
`IngestionRunner`'s per-symbol status semantics: both classes are
shared by every other real and test call site in this repository
(`tests/data_infra/test_quality_real_data.py`,
`tests/storage/test_data_quality_flags.py`, and every other script that
constructs a `FallbackDataProvider`/`IngestionRunner`), and neither
actually has enough information on its own to know whether "zero
records" means "market was closed" or "every tier is broken" -- only
the caller, which knows the real calendar and the full requested range,
can tell the two apart.

## Decision

`scripts/ingest_real_market_data.py` now cross-checks its own
already-computed `missing_symbols` (requested symbols with zero
persisted bars, Phase 31) against the real, production-grade NYSE
trading calendar (`data_infra.calendar.US_EQUITY_NYSE` -- a rule-derived
calendar spanning 2000-2035, NOT the toy Phase-1-scope `US_EQUITY`
sample, whose own module docstring explicitly disclaims production
accuracy and warns against exactly this kind of use).

- `expected_trading_days_in_range`: counts real NYSE trading days in
  `[--start, --end]` (inclusive) using `US_EQUITY_NYSE.is_trading_day()`.
- `unexplained_zero_bar_symbols`: equals `missing_symbols` when
  `expected_trading_days_in_range > 0`, otherwise always `[]`.
- The script now exits non-zero (and prints a `FATAL` line to stderr)
  when `unexplained_zero_bar_symbols` is non-empty, in addition to its
  existing `result.status`/`quality_run.status` exit-code checks (Phase
  30/Session 37).

Both fields are added to the JSON manifest and printed to stdout,
following this script's existing convention (every other manifest field
Phase 30/31 added is both persisted and printed, since the manifest
artifact itself is often unreachable from this environment's own egress
-- see the script's own module docstring).

This fix is deliberately confined to `scripts/ingest_real_market_data.py`
alone. `FallbackDataProvider`, `IngestionRunner`, and
`DataQualityFramework` are all left completely unmodified -- their
existing, shared, well-tested behavior (including the pre-existing
`min_expected_bars`/`WARNING`-severity mechanism in
`src/data_infra/quality.py`, which this fix does not touch or replace)
continues to work exactly as before for every other caller.

## Consequences

### Positive
- A real, independently-audited gap is closed: a real provider outage
  or bug that causes every tier to silently return nothing for a symbol
  on a genuinely open trading day is now a real, visible ingestion
  failure (non-zero exit code, `FATAL` stderr line, manifest field) --
  not indistinguishable from a routine holiday-only run.
- No change to any shared class's behavior or existing severity
  semantics -- zero risk of regressing
  `tests/data_infra/test_quality_real_data.py`'s or
  `tests/storage/test_data_quality_flags.py`'s existing
  `min_expected_bars`/`WARNING`-severity expectations, since this fix
  never touches `DataQualityFramework`/`FallbackDataProvider` at all.
- Uses the calendar module's own already-correct distinction between a
  toy sample and a real, rule-derived, wide-range calendar -- no new
  holiday logic was written for this fix.

### Negative / Trade-offs
- This fix only covers `scripts/ingest_real_market_data.py`, the
  flagship real-ingestion entry point. `FallbackDataProvider.fetch()`'s
  own module docstring claim ("No silent 'success' fabrication") is
  still only literally true for the all-tiers-raised path -- any other
  future caller of `FallbackDataProvider`/`IngestionRunner` directly
  (bypassing this script) would not automatically get this same
  protection unless it independently performs the same calendar
  cross-check. This is a deliberate, scoped choice (see the rejected
  naive fix above), not an oversight, but it does mean the underlying
  shared classes' docstring claim remains narrower than its own wording
  suggests -- a documentation clarification for `fallback.py`'s
  docstring specifically may be worth a small, separate follow-up.
- `expected_trading_days_in_range` treats `[--start, --end]` as
  inclusive on both ends -- a coarse "was the market open at all in
  this range" signal, not a precise per-symbol expected-bar-count model
  (the existing `min_expected_bars` mechanism in
  `DataQualityFramework.run()` already exists for that finer-grained
  need and is intentionally left untouched here).
- Does not account for a symbol's own real listing/delisting window
  (e.g. a symbol legitimately not yet listed for the whole requested
  range would still trip this check if any real NYSE trading day falls
  in that range) -- `missing_symbols` already had this same limitation
  before this fix, and closing it is a separate, larger undertaking
  (the same real point-in-time-membership machinery discussed in
  ADR-0175's sibling finding, P1-2, RESEARCH_UNIVERSE_STAGE4's own
  documented survivorship-bias gap) that this fix does not attempt.

## Tests

`tests/data_infra/test_ingest_real_market_data_wiring.py`'s new
`TestUnexplainedZeroBarSymbolsGateExitCode` class (5 tests): confirms
the real `US_EQUITY_NYSE` calendar (not the toy sample) is imported and
used, the two new manifest keys exist, `unexplained_zero_bar_symbols`
is only ever populated when `expected_trading_days_in_range > 0`, the
FATAL message is printed, and the exit-code `return` statement actually
checks the new list. Two pre-existing tests in the same file
(`test_return_statement_also_checks_quality_run_status`,
`test_quality_issues_are_persisted_to_the_repository_before_the_exit_
code_check`) were updated to match the `return` statement's new
multi-line, multi-condition form (no behavioral change to those tests'
own assertions). This script is still never imported/executed by the
automated suite (real network call; see its own module docstring) --
all coverage here is source-text/AST-based, the same discipline this
file already established for Phase 30/31.

## Status of Implementation at Time of This ADR

Code and tests complete. This is the first of three P1 findings from
the independent audit report being fixed in the order the account
owner specified ("순서대로 고쳐"); P1-2 (survivorship-biased production
universe) and P1-3 (cycle-level cumulative risk exposure not enforced
in `paper_runner.py`) are still pending, tracked separately.
