#!/bin/bash
set -euo pipefail

cd "${CLAUDE_PROJECT_DIR:-.}"

# Reset the enforce-task-observer.sh / enforce-validation-guard.sh
# per-session markers -- a fresh session must not inherit a marker left
# by a previous one and silently skip those gates.
HOOK_STATE_DIR="$(pwd)/.claude/hooks/state"
mkdir -p "$HOOK_STATE_DIR"
rm -f "$HOOK_STATE_DIR/task-observer-active" "$HOOK_STATE_DIR/validation-guard-active"

STATUS_EXCERPT=""
if [ -f docs/PROJECT_STATUS.md ]; then
  STATUS_EXCERPT=$(head -c 4000 docs/PROJECT_STATUS.md)
fi

OBS_DIR="$(pwd)/skill-observations"
OBS_MSG="Invoke the task-observer skill before the first tool call (see CLAUDE.md)."
OPEN_COUNT=$(find "$OBS_DIR/observation-log" -maxdepth 1 -name '*.md' -exec grep -l '^status: open$' {} + 2>/dev/null | wc -l | tr -d ' ' || true)
LAST_REVIEW=$(cat "$OBS_DIR/last-review-date.txt" 2>/dev/null || echo never)
if [ "${OPEN_COUNT:-0}" -gt 0 ] 2>/dev/null; then
  OBS_MSG="$OBS_MSG $OPEN_COUNT open observations; last review: $LAST_REVIEW."
  if [ "$LAST_REVIEW" = "never" ]; then
    OBS_MSG="$OBS_MSG Offer the review."
  fi
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

--- task-observer ---
${OBS_MSG}
EOF
)

jq -n --arg ctx "$CONTEXT" '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'
