#!/bin/bash

# Per CLAUDE.md: the task-observer skill must be invoked before the first
# tool call of any session. The skill's own description says description
# matching alone is not enforceable and asks to be paired with a harness
# hook -- this is that hook. Matcher is ".*" (all tools) so this fires on
# every tool call in the session.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
SKILL_NAME=$(echo "$INPUT" | jq -r '.tool_input.skill // empty')

STATE_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/state"
MARKER="$STATE_DIR/task-observer-active"
mkdir -p "$STATE_DIR"

if [ "$TOOL_NAME" = "Skill" ] && [ "$SKILL_NAME" = "task-observer" ]; then
  touch "$MARKER"
  exit 0
fi

if [ -f "$MARKER" ]; then
  exit 0
fi

echo "BLOCKED: task-observer has not been invoked yet this session. Per CLAUDE.md, invoke Skill(task-observer) first (its Session Start Protocol: storage check, frontmatter scan, review trigger) -- then retry this tool call." >&2
exit 2
