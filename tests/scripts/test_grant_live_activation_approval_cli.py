"""Tests for `scripts/grant_live_activation_approval.py` (2순위
priority pass -- closes ADR-0197's "no human-approval CLI tool for
LiveActivationApproval" gap). Makes no network call and touches no
real broker/account -- the only I/O is the one `--out` JSON file --
run end to end via `main()`, mirroring
`tests/broker/live/test_print_live_configuration_version_cli.py`'s own
pattern."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from broker.live.approval import REQUIRED_CONFIRMATION_TOKEN

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "grant_live_activation_approval.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("grant_live_activation_approval", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestScriptIsSyntacticallyValid:
    def test_module_loads_without_error(self) -> None:
        _load_module()


class TestAValidGrantWritesARealApprovalFile:
    def test_all_required_flags_present_grants_and_writes(self, tmp_path, capsys) -> None:
        module = _load_module()
        out_path = tmp_path / "approval.json"
        rc = module.main([
            "--approved-by", "jane.doe",
            "--confirmation-token", REQUIRED_CONFIRMATION_TOKEN,
            "--checklist-completed", "--strategy-evidence-reviewed",
            "--out", str(out_path),
        ])

        assert rc == 0
        assert "Granted" in capsys.readouterr().out
        payload = json.loads(out_path.read_text())
        assert payload["approved_by"] == "jane.doe"
        assert payload["confirmation_token"] == REQUIRED_CONFIRMATION_TOKEN
        assert payload["checklist_completed"] is True
        assert payload["strategy_evidence_reviewed"] is True

    def test_the_written_file_round_trips_through_payload_to_approval(self, tmp_path) -> None:
        """The strongest proof this tool is real: what it writes must
        actually reconstruct into a valid LiveActivationApproval, not
        just look like JSON."""
        from broker.live.approval import payload_to_approval

        module = _load_module()
        out_path = tmp_path / "approval.json"
        module.main([
            "--approved-by", "jane.doe", "--confirmation-token", REQUIRED_CONFIRMATION_TOKEN,
            "--checklist-completed", "--strategy-evidence-reviewed", "--out", str(out_path),
        ])

        approval = payload_to_approval(json.loads(out_path.read_text()))
        assert approval.is_valid() is True


class TestAnInvalidGrantIsRefusedNotSilentlyWritten:
    def test_missing_checklist_flag_refuses_and_writes_nothing(self, tmp_path, capsys) -> None:
        module = _load_module()
        out_path = tmp_path / "approval.json"
        rc = module.main([
            "--approved-by", "jane.doe", "--confirmation-token", REQUIRED_CONFIRMATION_TOKEN,
            "--strategy-evidence-reviewed",  # --checklist-completed deliberately omitted
            "--out", str(out_path),
        ])

        assert rc == 1
        assert "REFUSED" in capsys.readouterr().err
        assert not out_path.exists()

    def test_missing_strategy_evidence_flag_refuses_and_writes_nothing(self, tmp_path) -> None:
        module = _load_module()
        out_path = tmp_path / "approval.json"
        rc = module.main([
            "--approved-by", "jane.doe", "--confirmation-token", REQUIRED_CONFIRMATION_TOKEN,
            "--checklist-completed",  # --strategy-evidence-reviewed deliberately omitted
            "--out", str(out_path),
        ])

        assert rc == 1
        assert not out_path.exists()

    def test_wrong_confirmation_token_refuses_and_writes_nothing(self, tmp_path) -> None:
        module = _load_module()
        out_path = tmp_path / "approval.json"
        rc = module.main([
            "--approved-by", "jane.doe", "--confirmation-token", "not the real phrase",
            "--checklist-completed", "--strategy-evidence-reviewed", "--out", str(out_path),
        ])

        assert rc == 1
        assert not out_path.exists()

    def test_automated_actor_identity_refuses_and_writes_nothing(self, tmp_path) -> None:
        module = _load_module()
        out_path = tmp_path / "approval.json"
        rc = module.main([
            "--approved-by", "SYSTEM", "--confirmation-token", REQUIRED_CONFIRMATION_TOKEN,
            "--checklist-completed", "--strategy-evidence-reviewed", "--out", str(out_path),
        ])

        assert rc == 1
        assert not out_path.exists()
