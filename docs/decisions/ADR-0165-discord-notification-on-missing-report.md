# ADR-0165: Send a Discord failure notice when the report file is missing

**Status:** Accepted
**Date:** 2026-09-18
**Deciders:** Claude Code (daily Paper Trading Actions health-check routine)
**Related documents:** `docs/decisions/ADR-0146-discord-webhook-notifications-for-scheduled-reports.md`
(the original feature), `docs/decisions/ADR-0160-tiingo-proactive-budget-and-stooq-js-challenge-dead-end.md`
(the proactive Tiingo quota cap whose PARTIAL_SUCCESS days are exactly
when this gap shows up)
**Renumbering note:** originally authored and merged as `ADR-0164` from
a separate, concurrently-running session/branch
(`claude/phase-11-model-evolution-7hpibr`, PR #56) -- collided with an
unrelated `ADR-0164` (second/third fallback data providers) merged
minutes earlier from a different branch. Renumbered to `ADR-0165` here
(this file, its own title, and its two in-code comment references) on
discovery, same as this repository's own `ADR-0147` precedent for a
duplicate-numbering collision -- the earlier-merged ADR keeps its
number, the later one is renumbered. No content change beyond the
number itself.

## Context

Diagnosing the 2026-09-18 daily health check's failed `Paper Trading
Daily Cycle` run (run #33, `35337636963`), found the `run-cycle` job had
two separate failures, not one:

1. `Ingest latest market data` failed with `PARTIAL_SUCCESS` (2 of 86
   symbols -- `SO`, `D` -- hit Tiingo's own proactive budget cap,
   ADR-0160; Stooq's fallback is a documented dead end). This correctly
   skips `Run paper trading cycle (--resume)` and never writes
   `paper_trading_cycle_report.json` -- working exactly as ADR-0127
   intended.
2. `Send Discord notification` (`if: always()`) then ran anyway, found
   `paper_trading_cycle_report.json` missing, and
   `scripts/send_discord_notification.py` printed `FATAL: ... does not
   exist` to stderr and exited 1 -- without ever calling Discord.

The second failure is a real, separate bug: on exactly the days
something goes wrong upstream (the only days a notification actually
matters), the one channel this whole feature exists for -- Discord,
per ADR-0146's own account-owner request -- stayed completely silent.
The account owner would see nothing on Discord and would have to check
GitHub Actions directly to learn the cycle failed, defeating the
feature's purpose.

## Decision

`scripts/send_discord_notification.py`'s missing-report branch now
sends a best-effort Discord message ("`{report_type}` report not
generated -- an earlier step in the workflow run failed or was
skipped. Check the GitHub Actions run for details.") before still
returning exit code 1. The exit code is unchanged (the workflow step's
own red X still correctly signals a real problem, and is not the only
signal that duplicates -- `Ingest latest market data` already failed
first), but the account owner now also learns about it on Discord
instead of only in the Actions UI.

If the Discord send itself also fails (e.g. a real network error),
still returns 1 with both failures reported to stderr -- never masks
a real webhook failure as success.

## Consequences

### Positive

- Closes the real gap: a failed cycle now reaches Discord too, not just
  GitHub Actions.
- No change to the exit code contract other callers rely on (still 1
  on a missing report) -- purely additive.

### Negative / Trade-offs

- None identified. The failure note is generic (report type + "check
  the Actions run") rather than the specific upstream root cause,
  since this script has no way to know *why* the report is missing --
  deliberately not guessing at a cause it cannot verify.

## Tests

`tests/scripts/test_send_discord_notification_cli.py::TestMissingInputs`:
- `test_missing_report_file_fails_but_still_sends_a_discord_failure_notice`
  -- confirms exit code 1 AND that a Discord message was actually sent
  (mocked `urllib.request.urlopen`), asserting the failure note's
  content.
- `test_missing_report_file_and_a_failing_discord_send_both_report_failure`
  -- confirms a missing report combined with a failing Discord send
  still returns 1 (never silently swallowed).

Full suite re-run: see `docs/PROJECT_STATUS.md`'s session log.

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed.
