# ADR-0167: Surface the real, pre-existing data quality ERROR backlog (866 issues) instead of guessing at it

**Status:** Accepted (diagnostics only -- root cause of the 866 issues remains OPEN, see below)
**Date:** 2026-09-18
**Deciders:** Claude Code (session continued), account owner (asked directly
whether the live data was actually clean, rather than accepting reassurance)
**Related documents:** `docs/decisions/ADR-0164-second-and-third-fallback-data-providers.md`
(the work that prompted re-checking a real run's logs), `src/data_infra/quality.py`
(the checks themselves), Session 37's own `TestCriticalDataQualityFindingsGateExitCode`
(the existing CRITICAL-only exit gate)

## Context

The account owner asked directly: is the real paper trading run actually
running on clean data, with prior corruption resolved? This was
investigated directly against real logs rather than answered from
memory or reassurance.

Two real `workflow_dispatch` runs from the same day were compared:

- Run at 11:04 (`35337636963`): most Tiingo calls failed (proactive
  budget exhaustion, ADR-0160) and Stooq's fallback failed on every
  call (its own confirmed permanent dead end) -- almost no new bars
  were persisted.
- Run at 14:07 (`35353526858`, after ADR-0164's fixes): 5376 real bars
  persisted from Tiingo/Twelve Data/Alpha Vantage successfully.

Both runs printed the **exact same** `Data quality status: FAILED (867
issue(s))` with an **identical** severity breakdown, `{'INFO': 0,
'WARNING': 1, 'ERROR': 866, 'CRITICAL': 0}`. Two runs with radically
different real data cannot coincidentally produce an identical issue
count -- this was traced to the actual code, not assumed: `scripts/
ingest_real_market_data.py` calls `repository.get_bars(symbol,
args.start, args.end, ..., include_quality_rejected=True)` for
`quality.run()`'s input, which re-reads the FULL persisted
`[--start, --end]` window (currently roughly 40 calendar days) from the
catalog every single run -- not just the bars this run itself fetched.
Since `DataQualityFramework.run()` recomputes issues fresh from bar
content each call (it does not diff against previously-recorded flags),
the same largely-unchanged historical bars produce the same 866
ERROR-severity issues every time.

**Conclusion, stated plainly**: these 866 issues are real, pre-existing
problems already present in the live catalog's recent history. They
were not introduced by today's Twelve Data/Alpha Vantage work, and
they are NOT resolved by anything in this session. They have most
likely been silently present for some time, because
`scripts/ingest_real_market_data.py`'s exit code (Session 37,
`TestCriticalDataQualityFindingsGateExitCode`) only hard-fails on
`CRITICAL_FAILURE` -- a `FAILED` status with 866 `ERROR`-severity
issues prints to CI stdout and is otherwise silently absorbed, every
run, with no alert.

**What this ADR does NOT establish**: which specific check(s)
(`duplicate_records`/`ohlc_consistency`/`negative_or_zero_price`/
`negative_volume`/`symbol_mismatch`/`future_dated`/
`ingestion_precedes_availability` are the ERROR-severity candidates in
`quality.py`) or which securities are responsible. This session's own
egress cannot reach the GitHub Actions artifact (Azure Blob Storage)
holding the real catalog to query it directly (confirmed: a direct
`curl` to the artifact's real download URL returns a 403 CONNECT
rejection from this environment's own proxy, the same wall
`test_ingest_real_market_data_wiring.py`'s own docstring already
documented before this session). Guessing at the root cause from code
reading alone, without the real data, would violate this project's own
"verify before claiming" discipline -- so this ADR stops at making the
real breakdown observable, not at claiming to have found the cause.

One candidate WAS found and ruled out by direct calculation:
`_check_future_dated` compares a bar's `available_time` (`timestamp +
20h`) against `as_of_now` (`args.end`, parsed as midnight UTC) -- for a
bar dated exactly on `args.end`'s own calendar date, `available_time`
(that day + 20h) is always after `as_of_now` (that day at midnight),
which is a real, latent bug (it will incorrectly flag "today's" own bar
as future-dated whenever same-day data is ingested), but this run's
`ACTUAL_DATA_END` was `2026-09-17`, one day behind `args.end`
(`2026-09-18`), so no bar in this specific run could have triggered it.
This bug is real and worth fixing in its own right, but is not this
ADR's main finding and is left for a future session with the real
per-check breakdown in hand (or a session that revisits `_check_
future_dated` specifically) to fix correctly.

## Decision

Rather than guess at the root cause, make the real breakdown visible
two ways:

1. **`scripts/ingest_real_market_data.py`** now computes and prints (and
   adds to the manifest) `check_counts` (issues grouped by `check_name`)
   and `error_security_ids` (every security with at least one
   ERROR-severity issue) -- the next real scheduled/`workflow_dispatch`
   run will show exactly which check(s) and which securities are
   responsible, with no code changes needed to get that answer.
2. **New `scripts/diagnose_data_quality_flags.py`**: a read-only,
   network-free diagnostic that queries `data_quality_flags` directly
   against a `--db-path` catalog (e.g. a downloaded-and-unzipped
   `market-data-catalog` GitHub Actions artifact) for the same
   per-check/per-security breakdown, plus a sample of the real issue
   messages for the worst-offending check. Runnable locally or in
   Colab right now, without waiting for another scheduled run or this
   session regaining artifact access.

Neither of these fixes the 866 issues themselves -- this ADR is
diagnostic infrastructure, not a remediation. The actual root cause and
fix are explicitly left as follow-up work once the real breakdown is in
hand (either from the next scheduled run's own stdout, or from the
account owner running the new diagnostic script against a downloaded
artifact).

## Consequences

### Positive

- The next real run makes the exact check/security breakdown visible
  for free, closing the gap that made this ADR's own root-cause
  investigation dead-end at "866 ERROR issues, cause unknown."
- The account owner (or a future session) can get the same answer
  immediately, without waiting for a new scheduled run, by running the
  new diagnostic script against an already-downloaded artifact.
- Honestly narrows, rather than closes, the account owner's original
  question: confirms the problem is real and pre-existing (not
  something this session broke), rather than either dismissing the
  concern or fabricating a root cause this session could not verify.

### Negative / Trade-offs

- **The 866 real ERROR-severity issues remain unresolved.** The paper
  trading pipeline continues running on top of them (the exit-code gate
  still only blocks on CRITICAL_FAILURE, unchanged by this ADR) until a
  future session identifies the actual check/securities and fixes the
  underlying data or check logic.
- The `_check_future_dated` off-by-design-issue found while
  investigating is documented here but not fixed -- fixing it requires
  deciding what `as_of_now` SHOULD mean for a same-day ingestion
  (`args.end` at midnight, vs. a real wall-clock "now"), a real design
  question left for a session that takes it on deliberately, not as a
  side effect of this diagnostic-only ADR.

## Tests

New `tests/scripts/test_diagnose_data_quality_flags.py` (3 tests: real
per-check/per-security breakdown against seeded `data_quality_flags`
rows, missing `--db-path` fails cleanly, an empty catalog does not
crash). `tests/data_infra/test_ingest_real_market_data_wiring.py`
gained 2 tests confirming the new manifest keys and stdout lines exist
(same AST/source-only discipline that file already established -- this
script is never imported/executed by the automated suite, real network
call only). Full suite re-run: see `docs/PROJECT_STATUS.md`'s session
log for the exact before/after counts.

## Status of Implementation at Time of This ADR

Diagnostic code and tests complete and committed. The actual data
quality ERROR backlog investigation is explicitly OPEN -- the next real
scheduled/`workflow_dispatch` run's stdout, or the account owner running
`scripts/diagnose_data_quality_flags.py` against a downloaded
`market-data-catalog` artifact, is required before a future session can
identify and fix the real root cause.
