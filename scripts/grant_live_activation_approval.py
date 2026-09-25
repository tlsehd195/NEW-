#!/usr/bin/env python3
"""Grants (or refuses to grant) a real `LiveActivationApproval`
(`src/broker/live/approval.py`) -- the human-sourced token
`broker.live.safety_gate.evaluate_safety_gate` requires before any Live
order can pass the safety gate. Closes the "no human-approval CLI
tool" gap ADR-0197 named and, at the time, deferred (2순위 priority
pass, account-owner-approved scope: a real, tested support tool, never
wired into a Live execution entrypoint -- none exists in this
repository).

This script performs no I/O beyond argument parsing, stdout, and
writing the ONE output JSON file `--out` names -- it never touches a
real broker or account. Every field this project's own
`LiveActivationApproval.__post_init__` requires is required here too;
there is no default that could silently grant an invalid approval.
`--confirmation-token` requires the operator to type the exact phrase
`broker.live.approval.REQUIRED_CONFIRMATION_TOKEN` names, matching the
"deliberate extra step against an accidental/scripted True" that
constant's own comment documents.

The written JSON is not itself a capability -- nothing in this
repository's deterministic pipeline reads it (no Live execution
entrypoint exists yet). A future one would call
`broker.live.approval.payload_to_approval` on it to build the real
`SafetyGateContext.approval` it needs, which re-validates every field
again rather than trusting the file's structure alone.

Usage:
    python3 scripts/grant_live_activation_approval.py \\
        --approved-by "jane.doe" \\
        --confirmation-token "I CONFIRM LIVE TRADING ACTIVATION" \\
        --checklist-completed --strategy-evidence-reviewed \\
        --out live_activation_approval.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from broker.live.approval import LiveActivationApproval, approval_to_payload  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--approved-by", required=True, help="Real operator identity -- never AI/SYSTEM/CLAUDE.")
    parser.add_argument(
        "--confirmation-token", required=True,
        help='Must exactly match broker.live.approval.REQUIRED_CONFIRMATION_TOKEN.',
    )
    parser.add_argument(
        "--checklist-completed", action="store_true",
        help="Confirms the manual runbook checklist (docs/operations/LIVE-TRADING-RUNBOOK.md) was completed.",
    )
    parser.add_argument(
        "--strategy-evidence-reviewed", action="store_true",
        help="Confirms a human reviewed the activating strategy's real held-out TEST result (ADR-0045).",
    )
    parser.add_argument("--out", default="live_activation_approval.json", help="Output JSON file path.")
    args = parser.parse_args(argv)

    try:
        approval = LiveActivationApproval(
            approved_by=args.approved_by,
            approved_at=datetime.now(timezone.utc),
            confirmation_token=args.confirmation_token,
            checklist_completed=args.checklist_completed,
            strategy_evidence_reviewed=args.strategy_evidence_reviewed,
        )
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    out_path = Path(args.out)
    out_path.write_text(json.dumps(approval_to_payload(approval), indent=2) + "\n")
    print(f"Granted: approved_by={approval.approved_by!r} approved_at={approval.approved_at.isoformat()}")
    print(f"Written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
