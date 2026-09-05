# ADR-0075: External scheduler wiring guidance for `run_paper_trading_cycle.py`

**Status:** Accepted
**Session:** 36 (continued)

## Context

ADR-0073 made repeated invocation of `run_paper_trading_cycle.py`
actually safe (`--resume` + the ID-allocator collision fix). What
remained on the user's own "순서대로" list was the scheduler itself --
this project genuinely cannot build or run one (there is no
always-on server this session controls), but it can hand over a
complete, safe, copy-pasteable real crontab entry rather than leaving
the user to work out the operational details alone.

## Decision

The script's own module docstring now documents a real crontab line,
with two additions beyond the bare Python invocation:

1. **`flock -n`** around the whole command. Two overlapping invocations
   (e.g. a slow real-network bar fetch overrunning into the next
   scheduled slot) would otherwise both try to hold a `StorageEngine`
   connection to the same DuckDB file at once -- unsupported by this
   project's own single-writer design (ADR-0002). `flock -n` makes a
   second, overlapping cron firing refuse to start instead of racing
   the first for the file.
2. **Log redirection** (`>> .../paper_trading_cycle.log 2>&1`) -- cron
   runs unattended; without this, a failure (including one `flock`
   itself silently skipped) would go unnoticed until someone happened
   to check.

No new source file or test is added -- this is operational guidance
for a mechanism outside this codebase's control, not a new capability
to verify with `pytest`. `--resume` (ADR-0073) is REQUIRED in the
example; omitting it reintroduces the double-submission risk that ADR
already fixed the safe path for.

## What remains out of scope

Actually registering this crontab entry (or an equivalent, e.g. a
systemd timer or a hosted scheduler) on a real machine remains the
user's own operational step -- no session here has a persistent server
to run one on. Monitoring the scheduler itself (alerting if a scheduled
run never happens) is likewise not attempted.
