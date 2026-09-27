---
id: 1
title: Guard command substitutions against optional-failure pipelines under set -e/pipefail
status: open
type: open-source
skill: [session-start-hook]
proposes_skill: []
siblings_checked: "no skill-families.md registry exists yet (first observation in this log); session-start-hook is the only harness-hook-authoring skill installed — checked git-guardrails-claude-code, different domain (git command blocking, not dependency/setup scripting), not applicable"
area: hook script reliability under bash strict mode
date: 2026-09-10
session_context: >
  Writing a SessionStart hook (session-start-status.sh) for the aiinvest
  project that injects a count of open task-observer observations via
  `find ... | wc -l | tr -d ' '` inside a `VAR=$(...)` assignment, under
  `set -euo pipefail`.
resolved:
resolution:
reference:
---

**Issue:** `OPEN_COUNT=$(find "$DIR" ... 2>/dev/null | wc -l | tr -d ' ')`
under `set -euo pipefail` silently kills the whole script the first time
it runs against a directory that doesn't exist yet (the common case: the
observation log hasn't been created). `find` exits non-zero on the
missing path; `wc -l` and `tr -d ' '` both still succeed and produce the
textually-correct output ("0"); but `pipefail` makes the pipeline's exit
status the last non-zero code in the pipe, i.e. `find`'s failure survives
past two successful downstream stages. A bare assignment (`VAR=$(...)`,
not inside `if`/`while`/`&&`/`||`) is not exempt from `set -e`, so the
script exits immediately after the assignment line, before the value is
ever used — and because it's a `SessionStart` hook, the failure is
silent: no error surfaces to the user, the hook just stops emitting
`additionalContext` for that call. Caught only by manually running
`bash -x` on the hook and noticing the trace stopped one line early with
exit 1, after `find`/`wc`/`tr` had all been traced and had visibly
correct output.

The `references/environments.md` reference file for this same skill
actually ships a nearly identical `find | wc -l | tr -d ' '` snippet for
computing open-observation counts (the exact pattern that broke here) —
but its example script is `#!/bin/sh` without `set -e`/`pipefail`, so the
bug is latent in the snippet itself and only manifests when someone
(reasonably) copies it into a stricter bash script, which is the
recommended target for a Claude Code `SessionStart` hook.

**Suggested improvement:** in `session-start-hook`'s guidance/examples for
writing hook scripts in bash (as opposed to `sh`), any command
substitution built from a pipeline where an early stage can legitimately
return non-zero on a normal condition (an empty/missing directory, `grep`
finding no matches, etc.) needs an explicit `|| true` (or `|| echo
<default>`) on the *whole* assignment, not just awareness that pipefail
exists. Worth calling out explicitly since the failure is silent
(SessionStart hook errors don't visibly interrupt the session) and the
existing reference snippet in this skill bundle (`environments.md`) would
reproduce the same bug if copied verbatim into a `set -euo pipefail`
script instead of the `sh` script it was written for.

**Principle:** under bash strict mode, `VAR=$(pipeline)` is only as safe
as its least-safe stage — `set -o pipefail` propagates any stage's
failure through stages that themselves succeed, and a plain assignment is
not protected by `set -e`'s `if`/`&&`/`||` exemptions. Any pipeline stage
whose failure is an expected, normal outcome (not a real error) needs an
explicit `|| true`/`|| default` guard on the assignment as a whole, and
this is easy to miss precisely when the pipeline's *final* stage always
succeeds (as `wc -l | tr -d ' '` does here) — the visible output looks
correct in isolation, so nothing about testing the pipeline manually
(without `set -e`) reveals the bug.
