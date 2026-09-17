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

    def test_performance_section_metrics_are_rendered_when_present(self) -> None:
        report = {
            "performance": {
                "sharpe_ratio": 1.2345, "sortino_ratio": 2.0, "max_drawdown": -0.15, "total_return": 0.081,
            },
        }
        message = format_paper_trading_cycle_report(report)
        assert "Sharpe ratio: 1.234" in message
        assert "Sortino ratio: 2.000" in message
        assert "Max drawdown: -15.00%" in message
        assert "Total return: 8.10%" in message

    def test_performance_metrics_that_are_none_are_skipped_not_fabricated(self) -> None:
        """`reasons`-carrying `None` metrics (e.g. insufficient_data) must
        never render as 0/N/A."""
        report = {"performance": {"sharpe_ratio": None, "reasons": {"sharpe_ratio": "insufficient_data"}}}
        message = format_paper_trading_cycle_report(report)
        assert "Sharpe ratio" not in message

    def test_missing_performance_section_is_skipped_entirely(self) -> None:
        """An older report file (written before ADR-0136) has no
        `performance` key at all -- must not raise."""
        message = format_paper_trading_cycle_report({"universe": "PILOT_UNIVERSE"})
        assert "Sharpe" not in message


class TestTruncateForDiscord:
    def test_short_content_is_unchanged(self) -> None:
        assert truncate_for_discord("hello") == "hello"

    def test_long_content_is_truncated_to_the_real_discord_limit(self) -> None:
        content = "x" * 3000
        truncated = truncate_for_discord(content, limit=2000)
        assert len(truncated) == 2000
        assert truncated.endswith("... (truncated)")

    def test_astral_characters_count_as_two_units_like_discord_does(self) -> None:
        """External review, LOW-2: Discord measures `content` in UTF-16
        code units, not Python codepoints -- an astral character (e.g.
        emoji U+10000 and above) is ONE Python codepoint but TWO UTF-16
        units. All-BMP content, so `len()` and the real UTF-16 count
        agree here -- this just pins the boundary math itself."""
        content = "x" * 1999 + "\U0001F4C8"  # 📈, U+1F4C8 -- one codepoint, two UTF-16 units
        # UTF-16 length is 1999 + 2 = 2001 -- one over the limit, even
        # though `len(content)` (Python codepoints) is only 2000.
        assert len(content) == 2000
        truncated = truncate_for_discord(content, limit=2000)
        assert truncated.endswith("... (truncated)")
        assert "\U0001F4C8" not in truncated  # the emoji itself didn't fit -- dropped whole, never split

    def test_content_that_fits_by_utf16_count_is_left_unchanged(self) -> None:
        """The inverse check: content whose UTF-16 length is exactly at
        the limit must NOT be truncated, even though it contains an
        astral character that a naive codepoint count would undercount."""
        content = "x" * 1998 + "\U0001F4C8"  # UTF-16 length: 1998 + 2 = 2000
        assert len(content) == 1999  # codepoint count would (wrongly) say "well under limit"
        assert truncate_for_discord(content, limit=2000) == content

    def test_truncation_never_splits_a_surrogate_pair(self) -> None:
        """Truncating right at an astral character's own boundary must
        drop that character whole, never emit half of a surrogate pair
        (which `str.encode` would refuse, raising `UnicodeEncodeError`
        on `surrogatepass`-free encoding)."""
        content = "x" * 1999 + "\U0001F4C8" + "y" * 10
        truncated = truncate_for_discord(content, limit=2000)
        truncated.encode("utf-16-le")  # must not raise


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
