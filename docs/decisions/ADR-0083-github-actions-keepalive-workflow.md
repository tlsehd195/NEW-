# ADR-0083: keepalive workflow prevents the 60-day scheduled-workflow auto-disable

**Status:** Accepted
**Session:** 36 (continued)

## Context

ADR-0082 disclosed, but did not solve, a real risk: GitHub
automatically disables ALL scheduled (`schedule:`) workflows in a
repository after 60 days with no repository **commit** activity.
Verified against GitHub's own documentation and community reports
(not assumed): workflow *runs* -- including `paper_trading_cycle.yml`
firing successfully every weekday -- do not count as activity for this
rule; only new commits do. A quiet stretch of the repository (no
manual commits for 60+ days) would silently stop the Paper Trading
scheduler even though nothing about the workflow itself failed --
`workflow_dispatch` would still work manually, but the whole point of
this scheduler is not needing to remember to do that.

This also transitively protects against the artifact 90-day expiry
ADR-0082 also disclosed: as long as `paper_trading_cycle.yml` keeps
actually getting the chance to run, it re-uploads fresh artifacts
before the old ones would expire. The 60-day auto-disable was the one
failure mode that could silently stop that from happening at all.

## Decision

Add `.github/workflows/keepalive.yml`: a monthly (`cron: "0 12 1 *
*"`, comfortably inside the 60-day window even accounting for a missed
or delayed run) scheduled workflow that commits a trivial heartbeat
timestamp file (`.github/keepalive-heartbeat.txt`) if and only if it
changed. This is the standard community-established pattern for this
exact problem (used by e.g. `gh-action-keepalive`, `keepalive-workflow`
on the GitHub Marketplace) -- reimplemented directly here (a few lines
of plain `git commit`/`push`) rather than depending on a third-party
Action, since the repo's own CDN/dependency posture already avoids
unnecessary external dependencies where a few lines suffice.

The heartbeat file is the only thing this workflow ever touches --
never `data/`, never a DuckDB path, never anything `.gitignore`
already excludes.

## What this does NOT do

Does not eliminate the artifact 90-day expiry risk outright -- if
`paper_trading_cycle.yml` itself starts failing every run (e.g. an
expired/revoked `MARKET_DATA_API_KEY`) for more than 90 consecutive
days, artifacts would still expire even with the repository kept
"active" by this workflow. Whether GitHub sends a failure notification
email for a failing scheduled run, and to whom, was not verified in
this session -- the account owner should confirm their own GitHub
notification settings rather than relying on an unverified claim about
that here. Does not change cron timing precision (GitHub Actions'
inherent, undocumented-to-the-minute scheduling jitter, unrelated to
this workflow).

## Tests

`tests/deploy/test_keepalive_workflow.py` (new): statically parses the
YAML and asserts the schedule interval is well under 60 days, the
workflow has `contents: write` permission (required to push), and the
only file path ever referenced in its `run` steps is the heartbeat
file -- never `data/` or a `*.duckdb`/`*.parquet` path.
