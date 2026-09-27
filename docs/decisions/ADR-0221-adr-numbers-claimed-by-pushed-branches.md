# ADR-0221: ADR numbers are claimed by pushed branches, not only by main

**Status:** Accepted
**Date:** 2026-09-27
**Deciders:** account owner, Claude Code session

**Related documents:** `scripts/adr_number.py`,
`tests/scripts/test_adr_number.py`, `tests/docs/test_adr_metadata.py`,
`CLAUDE.md` ("ADR 번호 발급 규칙")

## Context

Several Claude sessions work on this repository in parallel, and each
picked its next ADR number as "highest file on my copy of main + 1".
Two sessions branched from the same main therefore picked the same
number. Git never flags this: the files have different names
(`ADR-0220-a.md`, `ADR-0220-b.md`), so both merge cleanly. The only
guard was a manual project rule ("fetch main right before merging and
renumber if it collides"), which caught it late and forced rework each
time: ADR-0164, 0203, 0214, 0218 and 0219 were all renumbered, and the
TEST-3 lock branch was colliding again on ADR-0220 (after already moving
off 0219) while this ADR was being written.

Two stronger options were ruled out:

- **Atomic server-side reservation** (push `refs/tags/adr-claim/NNNN`,
  which fails if the tag exists): the sessions' git proxy only allows
  pushing each session's own branch; a tag push returned HTTP 403.
- **Date- or hash-based ADR ids**: no collisions, but it breaks the
  sequential `ADR-NNNN` scheme that ~200 files and every citation (and
  `tests/docs/test_documentation_citations_resolve.py`) rely on.

## Decision

1. **A number is taken once it exists on origin/main or on any unmerged
   remote branch.** `scripts/adr_number.py next` fetches every remote
   branch and returns max + 1 over all of them. `new SLUG --title T`
   creates the stub file with that number; the session commits and
   pushes it immediately, so its claim is visible to every other session
   within seconds instead of only at merge time, hours later.
2. **Merge gate.** `scripts/adr_number.py check` (run right before
   merging) fails if one of this branch's new ADR numbers is used under
   a different file name on origin/main, or on another open branch that
   added it earlier (first commit adding the file; a rename counts as a
   new claim). Merged branches and the session's own remote branch are
   ignored.
3. **Losing the race is cheap.** `scripts/adr_number.py renumber NNNN`
   moves the branch's own ADR file to the next free number and rewrites
   `ADR-NNNN` citations in files the branch added (committed, uncommitted
   or untracked) and in lines the branch added to existing files. Lines
   that already cited main's ADR-NNNN are left alone.
4. **Main-side backstop.** `tests/docs/test_adr_metadata.py` now fails
   if two ADR files share a number, so a collision that still reaches
   main breaks the full test suite instead of staying silent.

Existing numbers and citations are unchanged; gaps (a claimed number
whose branch is abandoned) are allowed.

## Consequences

- The remaining race is the few seconds between `new` and the push;
  `check` catches it deterministically (the earlier claim keeps the
  number), and `renumber` fixes it in one command.
- A PreToolUse hook that runs `check` before `mcp__github__merge_pull_request`
  would make the gate automatic. Editing `.claude/settings.json` and
  hooks is outside what a session may change on its own, so that is left
  for the account owner to decide; until then the gate is the CLAUDE.md
  rule.
