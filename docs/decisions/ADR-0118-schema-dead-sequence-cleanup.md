# ADR-0118: dead `regime_*_id_seq` sequences removed; ADR-0117 reporting error corrected

**Status:** Accepted
**Session:** 37 (continued)

## Context

A fourth verification pass re-diffed `main` @ `d6eca5f` (post-PR #9,
ADR-0117) against the account owner's original review report and found
every MEDIUM/LOW/test item from the prior three rounds genuinely
resolved, with exactly one exception: `src/storage/schema.py:237-240`'s
`regime_observation_id_seq`/`regime_composite_id_seq` are created but
never consumed anywhere (`regime_observations`/`regime_composite_
observations` use a caller-assigned `regime_id TEXT PRIMARY KEY`
instead — the same natural-key pattern `broker_requests`/
`broker_responses` already use, per `storage.broker_repository`'s own
module docstring).

**This session's own ADR-0117 misreported this item.** Its LOW-residual
entry stated "`storage/schema.py`'s 2 unused sequences ... re-verified
already addressed by ADR-0116 (explanatory comments present in both
places)" — conflating this item with the genuinely-already-fixed
`risk/engine.py:230` `current_price` comment (which the same sentence
also referenced). `git log` confirms neither ADR-0116 (`4f4fcac`) nor
ADR-0117 (`15fbc08`) ever touched `storage/schema.py`; no explanatory
comment existed there before this ADR. The verification report's own
independent `git log`/`git show` check caught this directly — recorded
here rather than silently corrected, per this project's own file-
memory discipline (an inaccurate ADR claim is itself a defect worth a
paper trail, even when the underlying code impact is zero).

## Decision

Removed both dead `CREATE SEQUENCE` statements from `storage/schema.py`
and replaced them with an explanatory comment recording why no
sequence is needed (natural-key PRIMARY KEY, matching the pattern
already established for `broker_requests`/`broker_responses`) and that
an earlier schema revision left these two behind unused. Confirmed via
`grep` that neither sequence name appears in any `nextval(...)` call,
test, or script anywhere in the repository before removing them.

No production data is affected -- `CREATE SEQUENCE IF NOT EXISTS`
never had a consumer, so no real catalog ever depended on either
sequence's counter state.

## What this does NOT do

Does not re-litigate any other ADR-0115/0116/0117 finding -- the
fourth verification pass confirmed all of them hold. Does not add a
regression test for this change (a self-evidently correct, behavior-
free DDL cleanup the removed grep search above already verifies has no
consumer to protect).

## Tests

`tests/storage/` and `tests/regime/` (258 tests) re-run clean after
the change, confirming no hidden dependency on either sequence. Full
suite re-run: see `PROJECT_STATUS.md`'s own session entry for the
exact before/after count.
