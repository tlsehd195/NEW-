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
            "initial_capital": 1_000_000.0,
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
        assert "2024-01-02 ~ 2026-09-17" in message
        assert "처리된 체크포인트: 187개" in message
        assert "주문 제출: 42건 (체결: 39건)" in message
        assert "초기 자본: 1,000,000.00" in message
        assert "최종 현금: 12,345.68" in message
        assert "AAPL: 10" in message and "MSFT: 5" in message
        # An unrecognized note string (not one of the fixed known ones)
        # must still be shown as-is, never dropped or mistranslated.
        assert "Real Paper Trading cycle run." in message

    def test_early_exit_resume_shape_never_fabricates_missing_fields(self) -> None:
        """`--resume`'s "nothing new to process" report has no
        `total_orders_submitted` key at all (it never got that far) --
        the formatter must skip that line, never render it as
        0/None/"unknown". `start`/`end`/`last_processed` ARE present on
        this shape (added after an external review found the account
        owner's real Discord message had no date at all on this
        shape) -- the period line must still render from those."""
        report = {
            "note": "Nothing new to process -- every requested checkpoint was already recorded.",
            "universe": "RESEARCH_UNIVERSE",
            "checkpoints_run": 0,
            "start": "2024-02-01T00:00:00+00:00",
            "end": "2024-02-15T00:00:00+00:00",
            "last_processed": "2024-02-14T00:00:00+00:00",
            "final_cash": 5000.0,
            "final_positions": {},
        }
        message = format_paper_trading_cycle_report(report)
        assert "기간" in message and "2024-02-01" in message and "2024-02-15" in message
        assert "주문 제출" not in message
        assert "보유 포지션: 없음" in message
        assert "처리된 체크포인트: 0" in message

    def test_a_37_position_portfolio_is_listed_in_full(self) -> None:
        """External review: a real production message summarized away a
        real 37-position portfolio the account owner actually wanted to
        see -- must now list all of them (raised threshold)."""
        report = {"final_positions": {f"SYM{i}": i for i in range(37)}}
        message = format_paper_trading_cycle_report(report)
        assert "보유 포지션 (37개):" in message
        assert "SYM0: 0" in message and "SYM36: 36" in message

    def test_way_too_many_positions_are_still_summarized_not_listed(self) -> None:
        report = {"final_positions": {f"SYM{i}": i for i in range(200)}}
        message = format_paper_trading_cycle_report(report)
        assert "보유 포지션: 200개 (너무 많아 표시 생략)" in message
        assert "SYM0" not in message

    def test_fractional_share_quantities_are_rounded_for_display(self) -> None:
        """External review: a real message showed unrounded floats like
        "AAPL: 3.162355322244007" (--lot-size, ADR-0140) -- must round
        to a readable number of decimals, and a whole share count must
        show with no decimals at all."""
        report = {"final_positions": {"AAPL": 3.162355322244007, "MSFT": 10.0}}
        message = format_paper_trading_cycle_report(report)
        assert "AAPL: 3.1624" in message
        assert "3.162355322244007" not in message
        assert "MSFT: 10" in message
        assert "MSFT: 10.0" not in message

    def test_positions_are_grouped_a_few_per_line_not_one_long_line(self) -> None:
        report = {"final_positions": {f"SYM{i}": i for i in range(8)}}
        message = format_paper_trading_cycle_report(report)
        position_section = message.split("보유 포지션 (8개):")[1]
        assert position_section.count("\n") >= 1  # more than a single flat line

    def test_performance_section_metrics_are_rendered_when_present(self) -> None:
        report = {
            "performance": {
                "sharpe_ratio": 1.2345, "sortino_ratio": 2.0, "max_drawdown": -0.15, "total_return": 0.081,
            },
        }
        message = format_paper_trading_cycle_report(report)
        assert "샤프 비율: 1.234 (양호)" in message
        assert "소르티노 비율: 2.000" in message
        assert "최대 낙폭: -15.00%" in message
        assert "총 수익률: ▲ 8.10%" in message

    def test_negative_total_return_gets_a_down_arrow(self) -> None:
        report = {"performance": {"total_return": -0.05}}
        message = format_paper_trading_cycle_report(report)
        assert "총 수익률: ▼ -5.00%" in message

    def test_sharpe_label_buckets(self) -> None:
        assert "양호" in format_paper_trading_cycle_report({"performance": {"sharpe_ratio": 1.5}})
        assert "보통" in format_paper_trading_cycle_report({"performance": {"sharpe_ratio": 0.5}})
        assert "부진" in format_paper_trading_cycle_report({"performance": {"sharpe_ratio": -0.5}})

    def test_performance_metrics_that_are_none_are_skipped_not_fabricated(self) -> None:
        """`reasons`-carrying `None` metrics (e.g. insufficient_data) must
        never render as 0/N/A."""
        report = {"performance": {"sharpe_ratio": None, "reasons": {"sharpe_ratio": "insufficient_data"}}}
        message = format_paper_trading_cycle_report(report)
        assert "샤프 비율" not in message

    def test_known_note_is_translated_to_korean(self) -> None:
        report = {"note": "Nothing new to process -- every requested checkpoint was already recorded."}
        message = format_paper_trading_cycle_report(report)
        assert "새로 처리할 체크포인트 없음" in message

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

    def test_sends_a_real_browser_user_agent_not_the_default_urllib_one(self, monkeypatch) -> None:
        """ADR-0166: a real production run got HTTP 403 straight from
        Discord's own infrastructure with no User-Agent header at all --
        same root cause class this project already found for Stooq
        (ADR-0157)."""
        captured = {}

        def fake_urlopen(req, timeout):
            captured["user_agent"] = req.get_header("User-agent")
            return _FakeHTTPResponse(204)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        send_discord_message("https://discord.com/api/webhooks/real", "hello")
        assert captured["user_agent"] is not None
        assert "python-urllib" not in captured["user_agent"].lower()

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
