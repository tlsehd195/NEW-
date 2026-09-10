# CLAUDE.md

Project context lives in `PROJECT_MASTER_PLAN.md` (Source of Truth) and
`docs/PROJECT_STATUS.md` (current state) — read those first, per the
SessionStart hook. This file is only tool-usage rules for Claude Code
itself in this repo.

## Reach for these instead of the default, when they apply

- **Exploring code structure** (finding a function/class, understanding
  call sites, mapping a module before editing it) → use
  `claude-mem:smart-explore` before falling back to reading whole files
  with `Read`. Reserve full-file `Read` for when you actually need to
  read the logic itself, not just locate it.
- **Library/framework/API usage** you're not 100% certain of (duckdb,
  pyarrow, pytest, or anything else pulled in later) → check `context7`
  (`resolve-library-id` then `query-docs`) before writing code against
  remembered API shape. Skip it for pure stdlib or this repo's own code.
- **About to add a large, mostly-noisy tool result to context** (a long
  log, a big query result, a verbose command output where only a slice
  matters) → run it through `headroom_compress` first; use
  `headroom_retrieve` if the original is needed later. Don't bother for
  output that's already small or already the useful part.
- **Picking up unclear or possibly-already-solved work** → check
  `claude-mem:mem-search` for relevant prior-session context before
  re-deriving it from scratch or asking the user.
- **Writing/editing/reviewing code** → `ponytail` is on by default
  (full intensity): YAGNI ladder, stdlib/native first, shortest working
  diff. It never trims input validation, error handling that prevents
  data loss, or security measures — those stay regardless of intensity.
  For a focused bloat pass, `ponytail-review` (diff) or `ponytail-audit`
  (whole repo).
- **Backtest, strategy-research, or data-ingestion code** → run
  `backtest-integrity-review` before trusting any result (lookahead
  bias, survivorship bias, calendar/corporate-action integrity).
- **Writing a status update, ADR, or anything claiming data/strategy
  validation** → run it past `validation-status-guard` first; this
  project's own precise-language rules (e.g. what "실 데이터 검증
  완료" actually requires) are stricter than general writing norms.

## Don't reach for

- `git push --force`, `reset --hard`, `clean -f`, `branch -D` — blocked
  by a PreToolUse hook anyway; don't try to work around it.
- Editing `configs/live/**`, `src/broker/live/{kill_switch,safety_gate,
  approval}.py`, or `.env` without the user's explicit in-chat
  confirmation for that specific change — also hook-enforced.

## Skill-observation capture (task-observer)

Before the first tool call of any session — and before writing or
proposing a plan, not merely before executing one — invoke the
task-observer skill AND execute its Session Start Protocol (storage
check, frontmatter scan, review trigger). Loading the skill and running
the protocol are separate steps; a session that loads the file and stops
has activated nothing. Any turn that will involve a tool call counts; do
not classify the session as "too simple" from its opening message.

After completing each task, check the observation records written this
session and report a one-line summary (ids and titles, or "none logged
and why").

Loading a skill is not complete until you have queried the observation
log for OPEN observations naming it and read their bodies:
```
grep -l "skill:.*<skill-name>" \
  /home/user/NEW-/skill-observations/observation-log/*.md
```
Apply their insights to the current work, even if the skill file hasn't
been updated yet. Run this at every skill load, however many skills load
in one session.

The task-observer workspace for this project is:
```
/home/user/NEW-/skill-observations
```
Every path the skill uses derives from that root and nothing else:
```
/home/user/NEW-/skill-observations/observation-log/
/home/user/NEW-/skill-observations/cross-cutting-principles.md
/home/user/NEW-/skill-updates/
/home/user/NEW-/skill-updates/PENDING.md
```
Never resolve any of them from the current working directory. This
project's skills are installed at project scope (`.agents/skills/` /
`.claude/skills/`, committed to the repo), so the log is pinned inside
the repo too, not at a user/global path.
