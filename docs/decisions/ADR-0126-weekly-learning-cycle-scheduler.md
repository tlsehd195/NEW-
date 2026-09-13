# ADR-0126: Weekly Learning Cycle scheduler

**Status:** Accepted
**Session:** 36 (continued)

## Context

The account owner asked what happens to the real market data and real
Paper Trading fills this project's daily GitHub Actions cycle
(`paper_trading_cycle.yml`, ADR-0082) has been accumulating since
2026-09-05. Answering that surfaced a real gap: `scripts/
run_learning_cycle.py` (ADR-0113) — the script that turns real,
already-recorded Trade Journal experience into a retrained candidate
model via `learning.pipeline.run_learning_pipeline` — exists, is fully
tested, and is wired to read from the same `--paper-store` catalog the
daily cycle already writes to, but was never invoked by any scheduled
workflow. Every day's real trading experience was accumulating with no
automated path that ever reads it back out to retrain from.

The account owner then asked, after a clarifying exchange distinguishing
this from something it explicitly is NOT (see below), to automate this.

## Decision

New workflow: **`.github/workflows/learning_cycle.yml`**, scheduled
weekly (`0 6 * * 6` — Saturday 06:00 UTC, safely after the week's last
weekday Paper Trading run at Friday 22:00 UTC has finished and
uploaded its own updated `paper-trading-store` artifact) plus
`workflow_dispatch` for manual runs.

- Restores the `paper-trading-store` artifact — the SAME artifact
  `paper_trading_cycle.yml` already produces daily — using the
  identical restore-and-defend-against-a-wrapped-zip logic that
  workflow's own restore steps use (ADR-0115, external review N-14),
  copied rather than factored into a reusable action to keep each
  workflow file fully self-contained and independently readable,
  matching this repository's existing convention of duplicating small
  shell snippets across its two prior scheduled workflows
  (`keepalive.yml`, `paper_trading_cycle.yml`) rather than introducing
  a composite-action abstraction for two call sites.
- Runs `scripts/run_learning_cycle.py --paper-store "$PAPER_STORE_DIR"
  --out learning_cycle_report.json` with every other flag left at its
  own documented default: `--provenance PAPER_TRADING` (the only
  provenance real Live orchestration can produce today) and `--trainer
  mean_reward_baseline` (that script's own documented honest choice —
  no `Strategy`/`DecisionAgent` in this codebase sets
  `OrderIntent.features` yet, so `linear_regression` would always
  report `fitted=False` against real data regardless of which script
  invokes it; this ADR does not change that separate, already-tracked
  gap).
- Re-uploads the updated `paper-trading-store` artifact (`if:
  always()`) — `run_learning_cycle.py` writes new rows into that same
  catalog file's own Learning Engine tables
  (`storage.learning_repository`), never touching the Trade Journal
  tables the daily cycle itself owns, so the two workflows never
  contend over the same tables even though they share one file.
- Uploads the run's own `learning_cycle_report.json` as a
  per-run-numbered artifact, mirroring `paper_trading_cycle.yml`'s own
  `paper-trading-cycle-report-${{ github.run_id }}` pattern.
- `permissions: contents: read, actions: read` — identical, minimal
  scope to the daily cycle; this workflow never writes to the
  repository itself.

**What this explicitly does NOT do** (the account owner's own
clarifying question this session, answered directly rather than
assumed away): this does not invent, select, or add any new factor.
Every one of this project's ~45 literature-sourced factors was added
by a human-directed research session, documented via its own ADR, per
RULE 0.8's explicit prohibition on picking or constructing a factor
after seeing a result (that would be exactly the data-snooping bias
the walk-forward/PBO/DSR discipline elsewhere in this project exists
to catch). This workflow only re-fits an EXISTING trainer's parameters
(currently just `mean_reward_baseline`'s single constant) against
freshly accumulated real Experience — the set of features a candidate
model can draw on is unchanged by this ADR and remains a separate,
explicit, human-directed decision. It also does not change what any
candidate model becomes: `CandidateModelStatus` stays `CANDIDATE`
either way, no code path this ADR touches ever sets `APPROVED`/
`DEPLOYED`, and no candidate this workflow produces is ever read by
Live Trading, Paper Trading's own decision pipeline, or any other
automated consumer — a human must review a run's own evaluation
metrics before anything produced here goes anywhere.

**Honest, expected failure mode, disclosed rather than engineered
around**: `run_learning_cycle.py` exits 1 when the paper store has no
real closed/realized trades to build Experience from yet, or when the
resulting dataset cannot actually be trained/validated
(`INSUFFICIENT_SAMPLES`) — by that script's own existing design (RULE
0.8: never report success when nothing was actually learned). Until
enough real Paper Trading trades have closed, this workflow failing on
its first several scheduled runs is that same honest signal working as
intended, not a bug this ADR should suppress. The restore step itself
also hard-fails (rather than silently starting fresh) when no prior
`paper-trading-store` artifact exists at all, since retraining from a
never-restored, empty local directory would silently train from
nothing.

## Tests

`tests/deploy/test_learning_cycle_workflow.py` (7 tests) — the same
category of static YAML-structure checks
`test_paper_trading_cycle_workflow.py` already established for the
daily cycle: valid YAML with the intended schedule, read-only
permissions, the real script invoked with the right catalog path, the
`paper-trading-store` artifact round-tripped with `if: always()`, the
restore step's hard-fail-with-no-prior-artifact behavior, and a real,
executable reproduction of the wrapped-artifact-zip flatten logic
(not just a text match) against both a wrapped and an already-flat
temp directory.

Full suite re-run after adding this workflow: no regressions.
