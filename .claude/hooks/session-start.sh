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
