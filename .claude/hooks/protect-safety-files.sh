#!/bin/bash

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Normalize to a path relative to the project root when possible.
REL_PATH="$FILE_PATH"
if [ -n "$CLAUDE_PROJECT_DIR" ]; then
  REL_PATH="${FILE_PATH#$CLAUDE_PROJECT_DIR/}"
fi

# Per PROJECT_MASTER_PLAN.md: real-account orders, kill switch, risk
# limits, broker credentials, and live config are things the AI must not
# change on its own. This hook enforces that at the tool level.
PROTECTED_PATTERNS=(
  '^configs/live/'
  '^src/broker/live/kill_switch\.py$'
  '^src/broker/live/safety_gate\.py$'
  '^src/broker/live/approval\.py$'
  '(^|/)\.env$'
)

for pattern in "${PROTECTED_PATTERNS[@]}"; do
  if echo "$REL_PATH" | grep -qE "$pattern"; then
    echo "BLOCKED: '$REL_PATH' is a safety-critical file (kill switch / live trading gate / broker credentials / live config). Per PROJECT_MASTER_PLAN.md, AI must not modify this without the user's explicit, in-chat confirmation for this specific change. Ask the user to confirm explicitly, or have them make this edit themselves." >&2
    exit 2
  fi
done

exit 0
