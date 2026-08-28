---
name: validation-status-guard
description: Check that any status update, ADR, or report about this project's validation state (backtest results, paper trading, real data ingestion, live-readiness) uses the project's own precise language rules before it is written. Use before writing or editing docs/PROJECT_STATUS.md, any docs/decisions/ADR, or any summary that claims data or a strategy has been "validated."
---

# Validation Status Guard

This project's constitution ranks Data Integrity and Reproducibility above
almost everything else, and its own history contains a concrete failure
mode worth guarding against directly: conflating a backtest/paper-trading
result with a claim about real-world validation. `README.md` and
`docs/PROJECT_STATUS.md` already establish precise language for this —
this skill is the check that a new status update actually follows it
before it is written, not a restatement of the rule.

## Before writing any status/validation claim

1. **Trace the data source.** For any performance number, does it come
   from real ingested market data (a specific ingestion run, with a
   traceable manifest/date range/symbol list), from paper trading, or from
   a backtest on synthetic/fixture data? Don't accept "it ran and produced
   numbers" as evidence of which — check the actual data path in code
   (`src/data_infra`, `src/broker/paper`, `src/broker/live`) or the
   ingestion manifest before writing anything.

2. **Match the claim to the evidence.** Specifically:
   - Only write "실 데이터 검증 완료" (or any English equivalent — "validated
     on real data", "confirmed with live data") when ingestion actually
     succeeded end-to-end and the result came from that ingested data.
   - A result from a single backtest window, without train/validation/test
     or walk-forward separation, must be labeled **INCONCLUSIVE** — never
     described as confirming or refuting a strategy.
   - A network/egress block, a missing API key, or any other reason real
     data was not fetched must be stated as exactly that (what was
     blocked, since when, what was tried), not glossed over or implied to
     be resolved.

3. **Don't let old phrasing carry forward unchanged.** If a Phase's status
   previously said data was blocked, and this session did not itself
   re-verify reachability, don't silently repeat last Phase's finding as
   if newly confirmed — say what was actually re-checked this time (see
   the diagnosing-bugs skill's "redact and show the actual command" habit
   applied here: show the actual reachability check run, if any).

4. **Cross-check against the kill-switch/live-trading gate.** Any status
   claim that a model or strategy is ready for the next stage (paper to
   live, e.g.) must reference the actual human-approval and validation-gate
   state in `src/broker/live/approval.py` / `safety_gate.py`, not just the
   backtest result. A green backtest is never sufficient grounds by itself
   to say "ready for live."

## Output

If a draft status update, ADR, or report violates any of the above, name
the specific sentence and what evidence is missing or misstated, and
propose the corrected wording — don't rewrite silently, since the exact
data lineage needs the user's or the code's confirmation, not a guess.
