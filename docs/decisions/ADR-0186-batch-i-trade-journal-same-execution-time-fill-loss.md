# ADR-0186: Fix same-execution_time partial-fill loss in the Trade Journal (audit Batch I)

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Claude Code (session continued), account owner (asked to
process every remaining P2/P3 finding from the independent audit
report, in batches; this is Batch I -- the last of the originally
planned batches)

## Context

The independent audit's §8 regression-test list (item 9, both the
original and the later re-verification report) named a real, narrower
survivor of Phase 17's own `record_trade` fix: `fill.execution_time`
distinguishes two partial fills of the same order ONLY when they happen
at different simulated instants. Two genuinely different partial fills
that share the exact same `execution_time` (a broker/simulator filling
several lots at one identical timestamp is a real, reachable case, not
contrived) still collide on the natural key
`("trade", experiment_id, fill.order_id, fill.execution_time)` and the
second is silently discarded -- exactly the class of bug Phase 17's own
fix was written to close, one level narrower.

Confirmed independently in both `trade_journal.repository.
InMemoryTradeJournalRepository.record_trade` and `storage.
trade_journal_repository.DuckDBTradeJournalRepository.record_trade`,
which duplicate the same natural-key construction.

## Decision

`PaperFillRecord.fill_id` (`broker.paper.models`) already exists and is
already a real, globally-unique, restart-safe identifier allocated per
fill (`_IdAllocator("PAPERFILL")` in `broker.paper.adapter`) -- this fix
threads it through rather than inventing a new identity scheme:

- `TradeRecord` gained a new, optional `fill_id: Optional[str] = None`
  field (additive; round-trips through `trade_record_to_payload`/
  `payload_to_trade_record`).
- `record_trade(..., fill_id: Optional[str] = None)` on both
  repositories now includes `fill_id` in the natural key when a caller
  supplies one. `None` (the default) preserves the EXACT prior
  key/behavior for every existing caller -- this matters concretely for
  `DuckDBTradeJournalRepository`, whose `natural_key` column already
  has real rows persisted in the OLD string format in any real
  `--paper-store`; the fix appends the `fill_id` suffix only when one is
  actually supplied, so an unmigrated caller's key computation is
  byte-identical to before and does not orphan already-persisted rows.
- `orchestration.paper_runner._record_fills_to_journal` (the one shared
  helper both the same-cycle and delayed-T+1-fill paths call) now
  passes `fill_id=fill_record.fill_id` -- the real, already-unique
  identifier was sitting right at the call site, previously discarded
  when only the inner `fill_record.fill` was passed through.

### Pre-ADR-0113 fills retroactive-journaling tooling -- explicitly deferred, not built

The audit also lists the real underlying data shape this bug produced
over time: 1,485 real historical fills, only 11 ever reaching the Trade
Journal, and 8 orders with no persisted status event. Building a
backfill tool to retroactively reconstruct `TradeRecord`s for those
1,485 pre-fix fills is a materially different, much larger undertaking
than this ADR's bug fix -- it would mean re-deriving historical
decision/realized-PnL/holding-period data outside the real-time code
path that normally produces it, with real risk of misrepresenting what
was actually decided at the time. This is a data-migration policy
decision for the account owner, not something to build unilaterally
while closing a narrow natural-key bug. **Explicitly deferred.** The
independent audit's own follow-up re-scan (R3, same SHA) cross-checked
the 9 committed backup files and confirmed this 8-order set is stable
and internally consistent (`orphaned fills 0/1,485`, `orphaned status
events 0/1,477`, the 8 status-missing orders exactly matching the
already-known set) -- i.e., this is a known, bounded historical gap, not
active data corruption, which supports treating it as a deliberate,
separately-scoped decision rather than an urgent fix.

## Consequences

### Positive
- Closes the real gap: two same-instant partial fills of one order now
  both survive in the Trade Journal (and therefore in Experience/
  Learning) when a caller supplies the real per-fill identity it
  already has.
- Zero risk to any existing caller or already-persisted data: the new
  parameter is opt-in, `None` default preserves exact prior behavior,
  and the DuckDB natural-key string format is unchanged for any caller
  that does not supply `fill_id` (verified directly against the actual
  stored string, not just behaviorally).
- Reuses a real, already-allocated identifier (`PaperFillRecord.
  fill_id`) rather than inventing a new one -- no new ID-allocation
  surface, no new restart-safety concern.

### Negative / Trade-offs
- The 1,485 pre-fix historical fills / 11-trade journal / 8
  status-missing orders gap remains exactly as it was -- this ADR does
  not touch it, by design (see deferral above).
- A caller that constructs its own `Fill`/`record_trade` call outside
  `orchestration.paper_runner` (there is none today, confirmed by grep)
  would need to be updated to pass `fill_id` to benefit from this fix;
  the fix is only as complete as its callers.

## Tests

`tests/trade_journal/test_idempotency.py`'s new
`test_two_distinct_partial_fills_sharing_the_same_execution_time_need_fill_id_to_survive`:
proves the collision still happens without `fill_id` (backward
compatibility), that two distinct fills with distinct `fill_id`s both
survive, and that a real retry of the same `fill_id` still dedupes.

`tests/storage/test_trade_journal_persistence.py`'s mirror test
(DuckDB backend) additionally asserts the stored `natural_key` string
for a no-`fill_id` call is byte-identical to the pre-fix format.

Verified both as real regression guards by reverting the natural-key
change in both repositories and confirming both new tests fail first
(fixed-order fill count assertions, `t1.trade_id != t2.trade_id`) before
restoring the fix.

Full suite run before merge as the merge gate (see PR).

## Status of Implementation at Time of This ADR

Code and tests complete. This is Batch I, the last of the originally
planned pass through the independent audit report's remaining P2/P3
findings. Two further independent audit reports (round 2 at SHA
`13e422c`, round 3 fresh-rescan at the same SHA) and two advisory
reports (MCP tooling location, external-repository applicability) were
received during this batch's work; their disposition is recorded
separately, not folded into this ADR.
