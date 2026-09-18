# ADR-0156: Scope the Paper Trading store git backup to ledger tables only

**Status:** Accepted
**Date:** 2026-09-18
**Deciders:** Claude Code (session continued)
**Related documents:** `docs/decisions/ADR-0150-paper-trading-store-git-backup.md`
(the design this corrects), `scripts/export_paper_store_backup.py`,
`.github/workflows/paper_trading_cycle.yml`

---

## Context

ADR-0150 added a git-committed JSON backup of the Paper Trading store,
closing the "artifact 90-day retention is the ledger's only
persistence" risk an external review named. Its own "Status of
Implementation" section disclosed honestly that it had "not yet been
exercised against a real scheduled run." This session ran it for real
for the first time, via `workflow_dispatch` (run
[35288987584](https://github.com/tlsehd195/NEW-/actions/runs/35288987584))
against the real production catalog, specifically to verify a related
fix (ADR-0147's HIGH-1) actually reaches a green run. It did not —
the workflow's own new backup step failed:

```
remote: error: File backups/paper_trading_store/risk_assessments.json is 397.36 MB; this exceeds GitHub's file size limit of 100.00 MB
remote: error: File backups/paper_trading_store/predictions.json is 194.34 MB; this exceeds GitHub's file size limit of 100.00 MB
remote: error: File backups/paper_trading_store/decision_outputs.json is 203.27 MB; this exceeds GitHub's file size limit of 100.00 MB
remote: error: File backups/paper_trading_store/regime_composites.json is 2103.60 MB; this exceeds GitHub's file size limit of 100.00 MB
remote: error: File backups/paper_trading_store/regime_observations.json is 2282.97 MB; this exceeds GitHub's file size limit of 100.00 MB
remote: error: File backups/paper_trading_store/position_sizing_results.json is 207.27 MB; this exceeds GitHub's file size limit of 100.00 MB
 ! [remote rejected] main -> main (pre-receive hook declined)
```

Root cause: `export_paper_store_backup.py` introspected
`information_schema.tables` and dumped EVERY table in the catalog
unconditionally — a deliberate design choice at the time ("a future new
table is backed up automatically without this script needing an
update"). Against this project's real, ~61,600-decision-cycle catalog,
that swept in several large per-cycle-per-security Learning Engine/
telemetry tables (`predictions`, `decision_outputs`,
`position_sizing_results`, `risk_assessments`, `regime_composites`,
`regime_observations` — the last two alone totaling over 4 GB) that
were never this backup's actual target. ADR-0150's own Context section
named the thing actually at risk: "the entire order/fill/trade/
decision history." Because `git push` is atomic across every file in
one commit, the huge unrelated files blocked the push entirely — which
means the ACTUAL target (`paper_orders`/`paper_fills`/`decisions`/
`trades`, each only a few thousand rows) also silently never got backed
up, on every single run, since ADR-0150 merged. This had zero test
coverage catching it because `tests/scripts/
test_export_paper_store_backup.py`'s fixtures only ever seeded one or
two rows into one table — nowhere near the size that breaks a real
git push, and the test suite never exercises `git push` itself (that
step lives in the workflow YAML, not the script).

No repo corruption resulted: the rejected push means nothing from that
run ever reached `main` — the ephemeral runner's own local commit
(`9429153`, "Update Paper Trading store backup snapshot") existed only
in that run's throwaway workspace and vanished when the runner
terminated. The bug is a silent absence of backup coverage, not
corrupted data.

## Decision — explicit ledger allowlist, plus a size safety cap

`scripts/export_paper_store_backup.py`'s `export_paper_store_backup()`
now filters `information_schema.tables` down to an explicit
`_LEDGER_TABLES` allowlist matching what ADR-0150 actually named:
`paper_orders`, `paper_fills`, `order_status_events`, `decisions`,
`trades`, `post_trade_analyses`, `counterfactuals`, `corrections`,
`paper_performance_reports`. A ledger table absent from a particular
catalog (e.g. an older store predating a newer table) is simply
skipped, not an error — `set(_LEDGER_TABLES) & existing_tables`, still
processed in `_LEDGER_TABLES`'s own fixed order.

This gives up ADR-0150's "a future new table is backed up
automatically" property. That trade-off is deliberate: the property
was actively harmful here — a script that "just works" against any
future table is exactly what silently swept in multi-gigabyte
telemetry tables it was never meant to cover. A future session adding
a genuinely new LEDGER table (e.g. a new Trade Journal audit-trail
table) adds one line to `_LEDGER_TABLES`; that is a smaller and safer
maintenance cost than the failure mode this ADR fixes.

**Defense in depth**: `_MAX_TABLE_JSON_BYTES = 50 * 1024 * 1024` (50
MB, well under GitHub's 100 MB hard limit) — even an allowlisted
ledger table is skipped (with a loud stderr `WARNING`, never a crash)
if its own JSON serialization exceeds this cap, rather than risking the
exact same atomic-push failure again if a ledger table itself ever
grows unexpectedly large. The skip means that ONE table's backup goes
stale for that run (the OLD file at `--out-dir`, if any, is left
untouched, not deleted) while every other table still backs up and
commits normally — the atomic-failure mode this whole ADR exists to
close.

The Learning Engine/telemetry tables excluded here are not
"un-backed-up forever" in any absolute sense: they are reconstructable
by re-running ingestion and `scripts/run_learning_cycle.py` against a
surviving ledger, which is precisely why they were never the target of
a durability guarantee in the first place — the ledger itself (orders,
fills, the Trade Journal) is the one thing with no such reconstruction
path.

## Consequences

### Positive

- The Paper Trading ledger's git-committed backup now actually reaches
  `main` on a real run — verified by re-running the same
  `workflow_dispatch` after this fix merges (see Status below).
- The size cap protects against the same failure mode recurring for a
  reason not yet seen (a ledger table growing unexpectedly large),
  without reintroducing the all-or-nothing atomic-push fragility.

### Negative / Trade-offs

- Adding a genuinely new ledger table now requires a one-line update to
  `_LEDGER_TABLES` — ADR-0150's "automatic" property is gone. Accepted:
  see Decision above for why automatic coverage was the actual bug.
- The Learning Engine/telemetry tables (predictions, regime
  observations, risk assessments, etc.) have NO durable backup of their
  own beyond the existing 90-day GitHub Actions artifact. This was
  already true in practice (ADR-0150's backup never actually protected
  them, it only appeared to) — this ADR makes that honest rather than
  changing it. A future session wanting durability for that data too
  should design it separately (e.g. a size-aware chunked format, or an
  external store), not by re-widening this script's scope.

## Tests

`tests/scripts/test_export_paper_store_backup.py`: existing tests
re-pointed from `risk_assessments` (now correctly excluded) to
`decisions` (a real ledger table) for their seed data. Two new tests:
a populated non-ledger table (`risk_assessments`) is never backed up
regardless of how populated it is; a table whose JSON would exceed
`_MAX_TABLE_JSON_BYTES` (monkeypatched to a tiny value for the test) is
skipped with a stderr `WARNING` rather than written. 9 tests total in
this file (up from 7), full suite re-run clean.

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed. Not yet
re-exercised against a real scheduled/`workflow_dispatch` run as of
writing — the next such run (scheduled or manually triggered) is this
fix's own real-world verification, the same way ADR-0150's original gap
was only found by that same kind of run.
