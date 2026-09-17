# ADR-0147: Fix workflow `secrets`-in-`if:` bug and complete the ADR duplicate-numbering cleanup

**Status:** Accepted
**Date:** 2026-09-17
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `.github/workflows/paper_trading_cycle.yml`,
`.github/workflows/data_quality_rescan.yml`, every ADR file touched below

---

## Context

The account owner uploaded an external verification report auditing this
session's own prior changes (commits `0646e40`..`7682cce`, PRs #23-#32)
and asked that it be checked before continuing other work. Per this
project's established discipline, each claim was verified independently
(direct testing, direct `ls`/`grep`, WebSearch against primary sources)
rather than trusted at face value — and the report's own suggested fix
for the first finding was itself found to be subtly wrong before a
corrected version was applied.

### HIGH-1: `secrets` context referenced directly inside a step's `if:`

`paper_trading_cycle.yml`'s "Send Discord notification" step read
`if: always() && secrets.DISCORD_WEBHOOK_URL != ''`. Verified via
WebSearch (GitHub's own documented workaround, `actions/runner#520`):
the `secrets` context is not a valid reference inside a step's `if:`
at all — this is a workflow **parse-time** error, invalidating the
entire run, not just this one step. The report's own suggested fix
(re-reading a step-level `env:` block from that same step's `if:`) was
independently checked and found to be *also* broken — a step's `if:`
can only read job- or workflow-level `env:`, never its own step's.

### HIGH-2: ADR duplicate numbering, and a false "no duplicates" claim

Five ADR numbers (0126, 0127, 0128, 0129, 0135) each had two different
files on `main`, because this session's own branch had drifted stale
(based on commit `da4b94d`, predating `0646e40`, the merge that brought
in another PR's independently-numbered ADRs) — confirmed by direct
`ls`/`uniq -c` against the true `origin/main` tree, not the session's
own stale local checkout. This session's own earlier PR (commit
`313bdf4`) had claimed "main에는 실제 중복 없음" ("no real duplicates on
main"), which was itself factually wrong for exactly this reason: it
checked the stale local branch, not `origin/main`.

## Decision

**HIGH-1:** Moved `DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}`
from the step's own `env:` into the workflow-level `env:` block, and
changed the step's `if:` to read `env.DISCORD_WEBHOOK_URL != ''` instead
of `secrets.DISCORD_WEBHOOK_URL != ''`.

**HIGH-2:** Renumbered the five later-created files in each duplicate
pair (the earlier-created file, by `origin/main`'s own commit history,
keeps its original number):

| Old number | File | New number |
|---|---|---|
| ADR-0126 | weekly-learning-cycle-scheduler | ADR-0142 |
| ADR-0127 | data-quality-gate-and-rejection | ADR-0143 |
| ADR-0128 | retroactive-data-quality-rescan | ADR-0144 |
| ADR-0129 | scheduled-data-quality-rescan | ADR-0145 |
| ADR-0135 | discord-webhook-notifications-for-scheduled-reports | ADR-0146 |

For each renamed file: the file itself (`git mv`), its own H1 title, and
every cross-reference to it elsewhere in the repo were updated — not
just the ADR's own text but every other file that names it by number:
`docs/PROJECT_STATUS.md`, sibling ADRs (`ADR-0135`→146's own two
sibling ADRs `ADR-0136`/`ADR-0138` referenced it by old number;
`ADR-0144`/`ADR-0145`/`ADR-0135`(unrenamed) referenced the gate ADR by
its old `ADR-0127` number), and code/workflow/test files
(`.github/workflows/data_quality_rescan.yml`,
`scripts/rescan_data_quality.py`, `scripts/import_external_market_data.py`,
`tests/deploy/test_data_quality_rescan_workflow.py`,
`tests/data_infra/test_rescan_data_quality_cli.py`,
`tests/data_infra/test_import_external_market_data_cli.py`). Each of
these files reused a number from the duplicate range to mean the file
that got renamed, which was easy to miss on a first pass across
`docs/decisions/` alone — confirmed by a repo-wide grep for all five old
numbers and manually checking every remaining hit means the OTHER,
correctly-unrenamed file in each pair (the five original
delisted-price-source ADRs 0126-0130, which keep their numbers).

## Consequences

### Positive

- The Discord notification workflow step no longer invalidates the
  entire scheduled run at parse time once `DISCORD_WEBHOOK_URL` is
  configured as a real repo secret.
- Every ADR number on `main` now refers to exactly one file; every
  cross-reference (prose and code comments) points at the file it
  actually means.

### Negative / Trade-offs

- This session's own earlier PR (#26) contained a factually incorrect
  "no duplicates" claim in its commit message and in the corresponding
  `docs/PROJECT_STATUS.md` prose; that prose entry is left as historical
  record (describing what was believed and reported at the time) rather
  than rewritten, since `PROJECT_STATUS.md`'s own convention is an
  append-only session log — the numbers it names have since all been
  corrected by this ADR's renumbering.

## Tests

No test files needed changes for HIGH-1 (workflow YAML only). HIGH-2
already had test coverage for the renumbered files' own content
(unchanged behavior, only doc/comment text and filenames changed); full
suite re-run clean (3147 passed) after all changes above.

## Status of Implementation at Time of This ADR

Code and docs complete and committed.
