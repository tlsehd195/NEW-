#!/bin/bash
set -euo pipefail

# Only run in Claude Code on the web / remote sessions -- each one starts
# from a fresh container, so the full dev/test environment (installed
# manually into an ad hoc venv in past sessions) has to be reinstalled
# every time or it silently isn't there for the next session.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# llmwiki MCP tool (.mcp.json registers it) used to be cloned + built by
# this hook on every session start, racing the MCP client's ~30s stdio
# connection timeout against a git clone + npm install + tsc build.
# Reordering this block ahead of venv/pip setup (see git history) only
# narrowed that race, it didn't close it -- on a slow network the build
# still lost, giving CONNECTION_CLOSED. Fixed by vendoring a prebuilt,
# dependency-free bundle at vendor/llmwiki-mcp/bin.bundle.cjs (committed,
# not gitignored -- see vendor/llmwiki-mcp/NOTICE.md for provenance and
# how to refresh it) that .mcp.json now runs directly. Nothing to build
# here anymore.

# A venv, not a system-wide install: this container's system Python has
# apt-managed packages (e.g. PyYAML) with no pip RECORD, which breaks a
# system-wide `pip install` outright when a version in requirements-dev.txt
# collides with one of them.
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

.venv/bin/python3 -m pip install --quiet --upgrade pip
.venv/bin/python3 -m pip install --quiet --editable .
.venv/bin/python3 -m pip install --quiet -r requirements-dev.txt

# Put the venv first on PATH for the rest of this session, so a plain
# `python3`/`pytest` picks up everything just installed above.
echo "export PATH=\"$CLAUDE_PROJECT_DIR/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
