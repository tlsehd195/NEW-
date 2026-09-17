"""Category: Transport Failure Test (formatting half) + Transport Failure
Test (network half) -- `notifications.discord_webhook.send_discord_
message` is the one real, network-capable function in this module.
`urllib.request.urlopen` is monkeypatched in every network-touching
test, mirroring `tests/data_infra/test_sec_edgar_transport.py`'s
identical discipline (ADR-0025's "no automated test may call a real
external provider" rule)."""

from __future__ import annotations

import json

import pytest

from notifications.discord_webhook import (
    format_paper_trading_cycle_report,
    send_discord_message,
    truncate_for_discord,
)


class _FakeHTTPResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestFormatPaperTradingCycleReport:
    def test_full_run_shape_includes_every_real_field(self) -> None:
        report = {
            "note": "Real Paper Trading cycle run.",
            "universe": "RESEARCH_UNIVERSE",
            "start": "2024-01-02",
            "end": "2026-09-17",
            "checkpoints_run": 187,
            "total_orders_submitted": 42,
            "total_orders_with_a_fill": 39,
            "final_cash": 12345.678,
            "final_positions": {"AAPL": 10, "MSFT": 5},
            "value_history_length": 187,
            "risk_config": {"max_sector_weight": 0.25},
            "content_checksum": "abc123",
        }
        message = format_paper_trading_cycle_report(report)
        assert "RESEARCH_UNIVERSE" in message
        assert "2024-01-02 -> 2026-09-17" in message
        assert "Checkpoints run: 187" in message
        assert "Orders submitted: 42 (filled: 39)" in message
        assert "Final cash: 12,345.68" in message
        assert "AAPL: 10" in message and "MSFT: 5" in message
        assert "Real Paper Trading cycle run." in message

    def test_early_exit_resume_shape_never_fabricates_missing_fields(self) -> None:
        """`--resume`'s "nothing new to process" report has no `start`/
        `end`/`total_orders_submitted` keys at all -- the formatter must
        skip those lines, never render them as 0/None/"unknown"."""
        report = {
            "note": "Nothing new to process -- every requested checkpoint was already recorded.",
            "universe": "RESEARCH_UNIVERSE",
            "checkpoints_run": 0,
            "final_cash": 5000.0,
            "final_positions": {},
        }
        message = format_paper_trading_cycle_report(report)
        assert "Period:" not in message
        assert "Orders submitted:" not in message
        assert "Open positions: none" in message
        assert "Checkpoints run: 0" in message

    def test_more_than_fifteen_positions_are_summarized_not_listed(self) -> None:
        report = {"final_positions": {f"SYM{i}": i for i in range(20)}}
        message = format_paper_trading_cycle_report(report)
        assert "Open positions: 20 (too many to list)" in message
        assert "SYM0" not in message


class TestTruncateForDiscord:
    def test_short_content_is_unchanged(self) -> None:
        assert truncate_for_discord("hello") == "hello"

    def test_long_content_is_truncated_to_the_real_discord_limit(self) -> None:
        content = "x" * 3000
        truncated = truncate_for_discord(content, limit=2000)
        assert len(truncated) == 2000
        assert truncated.endswith("... (truncated)")


class TestSendDiscordMessage:
    def test_successful_post_sends_json_content(self, monkeypatch) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["content_type"] = req.get_header("Content-type")
            return _FakeHTTPResponse(204)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        send_discord_message("https://discord.com/api/webhooks/real", "hello")
        assert captured["url"] == "https://discord.com/api/webhooks/real"
        assert captured["body"] == {"content": "hello"}
        assert captured["content_type"] == "application/json"

    def test_unexpected_success_status_raises(self, monkeypatch) -> None:
        monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: _FakeHTTPResponse(202))
        with pytest.raises(RuntimeError):
            send_discord_message("https://discord.com/api/webhooks/real", "hello")

    def test_long_content_is_truncated_before_sending(self, monkeypatch) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeHTTPResponse(204)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        send_discord_message("https://discord.com/api/webhooks/real", "x" * 3000)
        assert len(captured["body"]["content"]) == 2000
