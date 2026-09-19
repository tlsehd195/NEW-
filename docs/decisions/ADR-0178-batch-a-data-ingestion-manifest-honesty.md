# ADR-0178: Fix same-day bar undercounting/false future_dated flag; review 3 related audit items

**Status:** Accepted
**Date:** 2026-09-19
**Deciders:** Claude Code (session continued), account owner (asked to
process every remaining P2/P3 finding from the independent audit
report, in batches; this is Batch A -- data ingestion honesty)

## Context

The independent audit report's Step 1 (`src/data_infra/`) and its
document-vs-code diff table (item #14) both cite a "future_dated
same-day bug at `ingest_real_market_data.py:250`" as still present,
attributing it to `ADR-0167`. Re-reading ADR-0167 directly: it never
claims to have fixed this -- it explicitly identifies the bug and
explicitly defers it ("This bug is real and worth fixing in its own
right, but is not this ADR's main finding and is left for a future
session"). The audit's citation of the ADR is imprecise, but the
underlying factual claim (the bug is real and unfixed in the code) is
correct, and was independently re-confirmed here by direct code
reading before any fix was written.

**Investigation found the real, empirically-verified impact is
different from -- and larger than -- ADR-0167's own hypothesis**:

`_check_future_dated` (`src/data_infra/quality.py:429`) flags `bar.
available_time > as_of_now`. A daily EOD bar's `available_time` is its
own calendar date at 20:00 UTC (`END_OF_SESSION_OFFSET`,
`data_infra.provider.bar_available_time`) -- but `scripts/ingest_real_
market_data.py`/`scripts/import_external_market_data.py` both parse
`--end` to MIDNIGHT UTC of that date and pass it, unshifted, as BOTH
(a) `get_bars(..., as_of_time=args.end, ...)`'s own point-in-time
cutoff when re-reading bars for the reproducibility manifest, AND (b)
`quality.run(..., as_of_now=args.end, ...)`.

Because (a) already excludes any bar whose `available_time > args.end`
-- which is true for EVERY bar dated exactly on `--end`'s own date,
always -- the bar never reaches `all_bars` in the first place, so (b)
`_check_future_dated` can never actually see it and never fires. **This
was verified directly, not assumed**: a real invocation of
`import_external_market_data.py` with `--end` set to the exact date of
the last real CSV row showed `total_bars_persisted: 1` (not 2) and
`ACTUAL_DATA_END` one day behind the CSV's own real last row, with
`Data quality status: PASSED (0 issues)` -- confirming the audit's
literal claim ("this bug produces false `future_dated` failures") does
NOT currently manifest as an observable error in either script's
output. What silently happens instead, every single run, is **the
manifest's own `total_bars_persisted`/`actual_data_end`/`checksum`/
`missing_symbols` (all derived from `all_bars`) permanently
under-report by excluding the most recently requested day's own real,
already-persisted bar** -- a reproducibility-manifest honesty gap, not
a false-failure gap, and arguably a more consequential defect than the
one named (a false ERROR is at least visible; a silently short
manifest is not).

## Decision

Both scripts now compute `reporting_as_of_time = args.end +
timedelta(days=1)` and use it for BOTH the manifest's own `get_bars(...,
as_of_time=reporting_as_of_time, ...)` re-read AND `quality.run(...,
as_of_now=reporting_as_of_time, ...)`. This expresses `--end`'s own
documented meaning correctly ("as of the END of this requested day,"
matching the argparse help text both scripts already had) rather than
its first instant, and fixes both symptoms from the same root cause at
once: the manifest now includes the last requested day's own bar when
one was actually ingested, and `_check_future_dated` (now actually
reachable, since the bar is no longer pre-filtered out) correctly does
not flag it.

**Deliberately scoped to these two "reproducibility manifest" call
sites only** -- never to `run_long_horizon_validation.py`,
`run_paper_trading_cycle.py`, `run_first_real_strategy_evaluation.py`,
or `run_multi_strategy_paper_trading_cycle.py`'s own, structurally
identical-looking `get_bars(..., as_of_time=args.end, ...)` calls
(confirmed via a repo-wide grep before editing). Those calls are real
point-in-time backtest/paper-trading data views, not post-ingestion
reporting -- widening their own `as_of_time` by a day would let a
backtest or a live paper cycle "see" a bar slightly before its real
20:00 UTC availability boundary, a genuine look-ahead risk this ADR
must not introduce. The fix here only ever touches the two scripts'
own end-of-run manifest re-read, which feeds no trading decision.

## Three related audit items reviewed, not fixed here

The same audit step named three further P2 items. Each was
investigated directly before deciding not to act on it this round:

1. **`ingestion_time`/`retrieved_at` stamped from the caller's `--end`,
   not the real fetch instant** (`tiingo.py`, mirrored in
   `file_import.py`/`twelvedata.py`/`alphavantage.py`). This is
   confirmed real and, for a BACKFILL run (historical `--start`/`--end`
   far in the past, executed today), does distort "when did this
   system actually learn this" the way the audit describes. It is also
   a **deliberate, explicitly-documented instance of this project's
   own foundational reproducibility principle** ("never
   `datetime.now()`/`utcnow()`," stated in this exact docstring and
   dozens of others across the codebase) -- changing it would need a
   real design decision about which of two competing correctness goals
   (reproducibility vs. honest backfill provenance) wins, not a
   one-line fix. Left open, flagged for the account owner.
2. **Only `CRITICAL` severity excludes a bar / fails the exit code;
   `ERROR`-severity issues (e.g. the real 866-issue backlog ADR-0167/
   ADR-0168 investigated) are absorbed into stdout with no operator
   alert.** ADR-0168 already fixed the ROOT CAUSE of that specific
   866-issue backlog's duplicate/grandfathered-bar defects (confirmed:
   ADR-0168 predates the audited commit), but its own "Negative /
   Trade-offs" section already discloses the 87 original bad physical
   rows are never deleted (Raw Immutability) and will keep triggering
   `_check_ingestion_precedes_availability` on every future rescan
   forever, AND that the repair script has never actually been run
   against the real production catalog (blocked by this environment's
   own egress). The broader architectural question -- should any
   `FAILED` (not just `CRITICAL_FAILURE`) quality run also trigger a
   real operator-visible alert (e.g. via the existing Discord webhook
   path) -- is a genuine policy decision belonging with Batch F
   (monitoring wiring), not this batch.
3. **`data_status: "REAL"` hardcoded as a literal** in both scripts.
   Investigated and found to be an already-justified, deliberate
   choice, not an oversight: both scripts structurally can ONLY ever
   ingest real data (`TiingoDataProvider`/`TwelveDataDataProvider`/
   `AlphaVantageDataProvider` for one, user-supplied CSVs via
   `LocalFileDataProvider` for the other) -- there is no code path
   through either script that could produce synthetic data, unlike
   `run_long_horizon_validation.py` (which accepts both and therefore
   needs a caller-supplied `--data-status` flag, per that script's own
   module docstring). No change made; this audit item is assessed as a
   false positive.

## Consequences

### Positive
- The manifest for both real ingestion scripts now honestly reports
  the last requested day's own bar, closing a real, silent
  under-reporting gap that affected every run using either script.
- `_check_future_dated` (previously completely untested anywhere in
  this repository -- confirmed via a repo-wide grep before writing this
  fix) now has real, executable, end-to-end test coverage for the first
  time.
- Scoped precisely to avoid the one real risk this class of fix could
  introduce (loosening a backtest/live-trading point-in-time boundary)
  -- confirmed via grep that every OTHER `as_of_time=args.end` call
  site in this repository was left untouched.

### Negative / Trade-offs
- Three related, real audit items are explicitly NOT resolved by this
  ADR (see above) -- two are flagged as needing an account-owner
  decision (backfill `ingestion_time` semantics; ERROR-severity
  alerting policy), one is assessed as already-correct.
- The fix widens each script's own manifest-reporting `as_of_time`
  window by exactly one calendar day -- if some other, not-yet-written
  future caller relied on the OLD (buggy) narrower boundary for a
  reason this session did not anticipate, that caller would need its
  own review. No such caller exists today (confirmed by the same
  repo-wide grep).

## Tests

`tests/data_infra/test_import_external_market_data_cli.py`'s new
`test_a_bar_dated_exactly_on_end_is_no_longer_silently_excluded_or_
flagged`: real end-to-end run (this script makes no network call, so
it is actually executed, unlike `ingest_real_market_data.py`) proving
`total_bars_persisted`/`actual_data_end` now correctly include the
last requested day's own bar and no `future_dated` issue fires.
Verified this test genuinely fails without the fix (reverted the fix
locally, confirmed `total_bars_persisted == 1` instead of the expected
`2`, then restored the fix) before finalizing it as a real regression
test, not a tautology.

`tests/data_infra/test_ingest_real_market_data_wiring.py` needed no
changes (its existing AST/source-text assertions do not reference the
renamed `reporting_as_of_time` variable).

Full suite re-run: `tests/data_infra/ tests/data/ tests/storage/
tests/scripts/` -- 1139 passed. Full repository suite: 3487 passed.

## Status of Implementation at Time of This ADR

Code and tests complete for the one genuinely-fixable item in this
audit step (future_dated/undercounting). The two remaining, real,
open items (backfill `ingestion_time` semantics; ERROR-severity
alerting policy) are explicitly deferred pending the account owner's
own scope decision, not silently dropped. This is Batch A of a larger,
explicitly-requested pass through every remaining P2/P3 finding in the
independent audit report; Batch B (backtest/strategy_research
integrity) is next.
