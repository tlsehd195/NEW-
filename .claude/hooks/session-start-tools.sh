#!/bin/bash
set -uo pipefail

# Reinstalls/re-registers the machine-level (non-git) tools this project's
# sessions use, since they live outside the repo (~/.claude, ~/.local) and
# do not survive a fresh container. Runs async so it never blocks session
# start; every step is idempotent (safe to re-run on an already-set-up
# machine) and failures are swallowed so one broken tool can't break the
# other two or the session itself.

echo '{"async": true, "asyncTimeout": 300000}'

export PATH="$HOME/.local/bin:$PATH"

# claude-mem: plugin + background worker (cross-session memory)
npx --yes claude-mem@latest install --provider claude >/tmp/claude-mem-install.log 2>&1 || true
if ! pgrep -f "worker-service.cjs" >/dev/null 2>&1; then
  nohup npx --yes claude-mem@latest start >/tmp/claude-mem-worker.log 2>&1 &
  disown
fi

# headroom: isolated pipx install + MCP registration (token compression)
python3 -m pip install --user --quiet pipx >/dev/null 2>&1 || true
python3 -m pipx install --backend pip "headroom-ai[mcp]" >/tmp/headroom-install.log 2>&1 || true
headroom mcp install >/tmp/headroom-mcp-install.log 2>&1 || true

# context7: MCP registration for this project (up-to-date library docs)
if ! claude mcp list 2>/dev/null | grep -q "^context7:"; then
  claude mcp add context7 -- npx -y @upstash/context7-mcp >/tmp/context7-mcp-add.log 2>&1 || true
fi
