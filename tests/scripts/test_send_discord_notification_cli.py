"""Real, executable tests for `scripts/send_discord_notification.py`
(Session 38). Its one real network call (`notifications.discord_webhook.
send_discord_message`) goes through `urllib.request.urlopen`, monkeypatched
here exactly as `tests/data_infra/test_sec_edgar_transport.py` already
does for this project's other network-capable scripts -- safe to run
`main()` end to end."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "send_discord_notification.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("send_discord_notification", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeHTTPResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestMissingInputs:
    def test_no_webhook_url_anywhere_fails_without_a_network_call(self, tmp_path, monkeypatch) -> None:
        module = _load_script()
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps({"universe": "PILOT_UNIVERSE"}))
        exit_code = module.main(["--report", str(report_path), "--report-type", "paper_trading_cycle"])
        assert exit_code == 1

    def test_missing_report_file_fails_but_still_sends_a_discord_failure_notice(self, tmp_path, monkeypatch) -> None:
        """ADR-0165: a missing report (e.g. an earlier workflow step
        failed and this one was skipped) must not leave Discord
        completely silent -- the whole point of this script."""
        module = _load_script()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeHTTPResponse(204)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        missing = tmp_path / "does_not_exist.json"
        exit_code = module.main(
            ["--report", str(missing), "--report-type", "paper_trading_cycle", "--webhook-url", "https://discord.com/api/webhooks/x"]
        )
        assert exit_code == 1
        assert "report not generated" in captured["body"]["content"]

    def test_missing_report_file_and_a_failing_discord_send_both_report_failure(self, tmp_path, monkeypatch) -> None:
        import urllib.error

        module = _load_script()

        def fake_urlopen(req, timeout):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        missing = tmp_path / "does_not_exist.json"
        exit_code = module.main(
            ["--report", str(missing), "--report-type", "paper_trading_cycle", "--webhook-url", "https://discord.com/api/webhooks/x"]
        )
        assert exit_code == 1


class TestSuccessfulSend:
    def test_sends_formatted_report_content(self, tmp_path, monkeypatch) -> None:
        module = _load_script()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeHTTPResponse(204)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps({"universe": "PILOT_UNIVERSE", "checkpoints_run": 3}))

        exit_code = module.main(
            [
                "--report", str(report_path),
                "--report-type", "paper_trading_cycle",
                "--webhook-url", "https://discord.com/api/webhooks/real",
            ]
        )
        assert exit_code == 0
        assert "PILOT_UNIVERSE" in captured["body"]["content"]
        assert "Checkpoints run: 3" in captured["body"]["content"]

    def test_webhook_url_env_var_is_used_when_flag_omitted(self, tmp_path, monkeypatch) -> None:
        module = _load_script()
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/from-env")
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            return _FakeHTTPResponse(204)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps({"universe": "PILOT_UNIVERSE"}))

        exit_code = module.main(["--report", str(report_path), "--report-type", "paper_trading_cycle"])
        assert exit_code == 0
        assert captured["url"] == "https://discord.com/api/webhooks/from-env"


class TestNetworkFailure:
    def test_urlopen_error_is_reported_not_raised(self, tmp_path, monkeypatch) -> None:
        import urllib.error

        module = _load_script()

        def fake_urlopen(req, timeout):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps({"universe": "PILOT_UNIVERSE"}))

        exit_code = module.main(
            ["--report", str(report_path), "--report-type", "paper_trading_cycle", "--webhook-url", "https://discord.com/api/webhooks/x"]
        )
        assert exit_code == 1
