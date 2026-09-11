# ADR-0008: Validation Protocol Structure for Phase 2

**Status:** Accepted
**Date:** 2026-08-24
**Deciders:** Claude Code (Phase 2 session), pending project owner review
**Related documents:** `PROJECT_MASTER_PLAN.md` §13.4-13.5 (renumbered
from the original §48-49/§71 this ADR was written against -- see
ADR-0115) (López de Prado-style PBO/Deflated Sharpe validation is
§13.5), `docs/specifications/PHASE-2-backtesting.md` §14

---

## Context

`PROJECT_MASTER_PLAN.md` §13.4 defines the project's overall validation
protocol: `Training → Validation → Walk Forward → Purged Validation →
Embargo → Out of Sample → Paper Trading`. Phase 2 is the first phase
capable of running any of these mechanically (it has a working
backtest), but the project has no trained model yet (Phase 9+) and no
strategy variant search underway (baseline strategies only — Phase 2
spec §10). This ADR fixes how much of that protocol Phase 2 actually
builds versus reserves for later.

## Decision

Phase 2 implements only:

1. **`chronological_train_test_split(start, end, split_date)`** — a
   simple, non-random, time-ordered split into two contiguous ranges.
2. **`WalkForwardSplitter(train_period, test_period, step)`** — yields
   sequential `(train_start, train_end, test_start, test_end)` windows,
   each test window strictly following its train window in time,
   advancing by `step` through the full date range.
3. **`ValidationSplitter`** (a `Protocol`) — the shape any future
   splitter (including Purged K-Fold and Embargo) must satisfy so
   `BacktestEngine`/experiment-running code that consumes a splitter
   does not need to change when a more sophisticated splitter is added.

Phase 2 does **not** implement Purged K-Fold or Embargo logic itself.

## Reasoning

- Random train/test splitting is never used for this project's
  time-series data, full stop — shuffling rows across time leaks future
  information into "training" through adjacent-in-time correlation.
  `chronological_train_test_split` and `WalkForwardSplitter` are
  incapable of producing a random split by construction (there is no
  shuffle step anywhere in either implementation).
- Purged K-Fold and Embargo (López de Prado's contribution, cited in
  `PROJECT_MASTER_PLAN.md` §71) exist specifically to prevent leakage
  *around the boundary* between train and test folds when samples have
  overlapping label horizons (e.g., a label computed from a forward
  return window that extends past the fold boundary). Phase 2 has no
  labels, no trained model, and no fold-based experiment yet — there is
  nothing for a purge/embargo window to protect. Implementing it now
  would be untestable in any meaningful way (no real leakage scenario
  exists to catch) and would be exactly the "필요한 최소한의 연구만
  반영한다" (§17 of the Phase 2 instruction) violation the project
  explicitly warns against.
- Defining the `ValidationSplitter` Protocol now, even though only two
  simple implementations exist, means the eventual Purged K-Fold/Embargo
  implementation (whenever Phase 9's Learning Engine needs it) is a
  drop-in addition, not a refactor of whatever consumes splitters by
  then.

## Alternatives Considered

- **Implement Purged K-Fold/Embargo now, ahead of need**: Rejected per
  the reasoning above — no current consumer, no way to validate it is
  correct without a real leakage scenario to test against, and directly
  contrary to the Phase 2 instruction's explicit research-scope
  discipline.
- **Skip building any splitter interface until Phase 9**: Rejected —
  Walk Forward is explicitly listed as a Phase 2 "최소" (minimum)
  requirement (Phase 2 instruction §11), not a future one; building the
  `ValidationSplitter` Protocol at the same time costs little and avoids
  a later interface change.
- **A single `Splitter` class with a `mode` flag (`"walk_forward"` |
  `"purged"` | ...) instead of a Protocol with multiple
  implementations**: Rejected — a mode flag hides materially different
  behavior (and materially different required inputs, e.g., purge/embargo
  window sizes) behind one interface, which tends to produce exactly the
  kind of misconfiguration risk (silently running the wrong validation
  mode) this project's validation layer exists to prevent.

## Consequences

### Positive

- `BacktestEngine` can already be run across a `WalkForwardSplitter`'s
  windows today, giving Phase 2 a genuinely useful validation structure
  immediately, not just a promise of one later.
- No speculative, unvalidatable purge/embargo code sits in the codebase
  waiting for a use case that may shape its actual required parameters
  differently than guessed today.

### Negative / Trade-offs

- Until Purged K-Fold/Embargo is actually built (Phase 9+), any
  overlapping-label validation scenario is not protected against by this
  layer. This is a known, explicitly scoped gap, not an oversight —
  tracked here so a future session does not need to rediscover why it is
  missing.

## Status of Implementation at Time of This ADR

Implemented in `src/backtest/validation.py`
(`chronological_train_test_split`, `WalkForwardSplitter`,
`ValidationSplitter` Protocol). No test file is dedicated solely to this
module in Phase 2 beyond basic construction; full exercise of
`WalkForwardSplitter` against `BacktestEngine` is deferred to whichever
phase first needs to run a walk-forward strategy evaluation
end-to-end.
