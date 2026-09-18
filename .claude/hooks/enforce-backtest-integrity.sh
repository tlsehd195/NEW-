#!/bin/bash

# Per CLAUDE.md: backtest-integrity-review must be invoked before writing
# or reviewing code in src/backtest, src/strategy_research, src/data_infra,
# or src/predict (lookahead bias / survivorship bias / point-in-time
# violations / corporate-action data-quality risk). Matcher covers
# Edit/Write/MultiEdit (the writes to gate) plus Skill (to observe the
# skill being invoked and arm the marker) -- same pattern as
# enforce-validation-guard.sh.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
SKILL_NAME=$(echo "$INPUT" | jq -r '.tool_input.skill // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

STATE_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/state"
MARKER="$STATE_DIR/backtest-integrity-active"
mkdir -p "$STATE_DIR"

if [ "$TOOL_NAME" = "Skill" ] && [ "$SKILL_NAME" = "backtest-integrity-review" ]; then
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

if echo "$REL_PATH" | grep -qE '^src/(backtest|strategy_research|data_infra|predict)/'; then
  if [ -f "$MARKER" ]; then
    exit 0
  fi
  echo "BLOCKED: '$REL_PATH' is in a lookahead/survivorship/point-in-time-sensitive package. Per CLAUDE.md, invoke Skill(backtest-integrity-review) first, then retry this edit." >&2
  exit 2
fi

exit 0
