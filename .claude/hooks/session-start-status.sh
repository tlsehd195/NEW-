#!/bin/bash
set -euo pipefail

cd "${CLAUDE_PROJECT_DIR:-.}"

STATUS_EXCERPT=""
if [ -f docs/PROJECT_STATUS.md ]; then
  STATUS_EXCERPT=$(head -c 4000 docs/PROJECT_STATUS.md)
fi

CONTEXT=$(cat <<EOF
Autonomous AI Investment System (aiinvest) — session context recovery:

1. Read PROJECT_MASTER_PLAN.md first (Source of Truth: philosophy,
   constitution, architecture, Phase rules, change management).
2. Then docs/PROJECT_STATUS.md for current Phase / done-in-progress-blocked
   state (excerpt below).
3. Then docs/decisions/ (ADRs) for why things are designed the way they are.

Safety constitution reminder: Capital Safety > Data Integrity >
Reproducibility > Validation > Risk Control > Accurate Trade Recording >
Learning > Performance > Complexity. Default is fail-closed. The AI must
never modify kill switch, risk limits, broker credentials, live config,
or place real-account orders on its own initiative — those require the
user's explicit confirmation (a PreToolUse hook also enforces this on the
known safety-critical files).

--- docs/PROJECT_STATUS.md (excerpt, first 4000 chars) ---
${STATUS_EXCERPT}
EOF
)

jq -n --arg ctx "$CONTEXT" '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'
