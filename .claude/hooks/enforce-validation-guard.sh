#!/bin/bash

# Per CLAUDE.md: validation-status-guard must be invoked before writing or
# editing docs/PROJECT_STATUS.md or any docs/decisions/ADR-*.md file (any
# report claiming data/strategy validation). Matcher covers Edit/Write/
# MultiEdit (the writes to gate) plus Skill (to observe the skill being
# invoked and arm the marker) -- narrower than "all tools" since only
# those four tool names are ever relevant here.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
SKILL_NAME=$(echo "$INPUT" | jq -r '.tool_input.skill // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

STATE_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/state"
MARKER="$STATE_DIR/validation-guard-active"
mkdir -p "$STATE_DIR"

if [ "$TOOL_NAME" = "Skill" ] && [ "$SKILL_NAME" = "validation-status-guard" ]; then
  touch "$MARKER"
  exit 0
fi

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

REL_PATH="$FILE_PATH"
if [ -n "$CLAUDE_PROJECT_DIR" ]; then
  REL_PATH="${FILE_PATH#$CLAUDE_PROJECT_DIR/}"
fi

if echo "$REL_PATH" | grep -qE '^docs/PROJECT_STATUS\.md$|^docs/decisions/ADR-.*\.md$'; then
  if [ -f "$MARKER" ]; then
    exit 0
  fi
  echo "BLOCKED: '$REL_PATH' is a validation-status-claiming document. Per CLAUDE.md, invoke Skill(validation-status-guard) first to check the draft against this project's precise-language rules, then retry this edit." >&2
  exit 2
fi

exit 0
