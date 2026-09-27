"""ADR-0225: which names count as unseen for a locked window, and the
one-exam-per-window rule."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_infra.universe import BENCHMARK_SYMBOL, RESEARCH_UNIVERSE_STAGE5
from strategy_research.locked_windows import TEST_1, TEST_3
from strategy_research.unseen_exam import (
    EXAM_REPORT_KEY,
    exam_already_taken,
    exam_verdict,
    locked_window_by_name,
    seen_symbols,
)


def _write(reports_dir: Path, name: str, report: dict) -> Path:
    path = reports_dir / name
    path.write_text(json.dumps(report))
    return path


class TestSeenSymbols:
    def test_named_universes_and_benchmark_are_always_seen(self, tmp_path: Path) -> None:
        seen = seen_symbols(TEST_3, tmp_path)
        assert BENCHMARK_SYMBOL in seen
        assert set(RESEARCH_UNIVERSE_STAGE5.symbol_ids) <= seen

    def test_report_names_are_seen_only_when_its_range_overlaps_the_window(self, tmp_path: Path) -> None:
        _write(tmp_path, "overlap.json", {
            "security_ids": ["ZZOVER"], "overall_start": "2000-01-01T00:00:00+00:00",
            "overall_end": "2020-08-28T00:00:00+00:00",
        })
        _write(tmp_path, "before.json", {
            "security_ids": ["ZZBEFORE"], "overall_start": "2000-01-01T00:00:00+00:00",
            "overall_end": "2016-07-11T00:00:00+00:00",
        })
        seen = seen_symbols(TEST_3, tmp_path)
        assert "ZZOVER" in seen
        assert "ZZBEFORE" not in seen  # ends exactly where TEST-3 starts
        assert "ZZOVER" not in seen_symbols(TEST_1, tmp_path)

    def test_report_without_a_range_counts_as_seeing_every_window(self, tmp_path: Path) -> None:
        _write(tmp_path, "norange.json", {"security_ids": ["ZZNORANGE"]})
        assert "ZZNORANGE" in seen_symbols(TEST_1, tmp_path)

    def test_unreadable_and_non_dict_reports_are_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "bad.json").write_text("{not json")
        _write(tmp_path, "list.json", ["ZZLIST"])
        assert "ZZLIST" not in seen_symbols(TEST_3, tmp_path)

    def test_a_renamed_company_is_seen_under_its_new_ticker(self, tmp_path: Path) -> None:
        _write(tmp_path, "old.json", {"security_ids": ["ZZOLD"]})
        assert "ZZNEW" in seen_symbols(TEST_3, tmp_path, {"ZZOLD": "ZZNEW", "ZZOTHER": "ZZX"})
        assert "ZZX" not in seen_symbols(TEST_3, tmp_path, {"ZZOLD": "ZZNEW", "ZZOTHER": "ZZX"})


class TestOneExamPerWindow:
    def test_exam_report_blocks_its_own_window_only(self, tmp_path: Path) -> None:
        taken = _write(tmp_path, "exam.json", {EXAM_REPORT_KEY: {"window": TEST_3.name}})
        assert exam_already_taken(TEST_3, tmp_path) == taken
        assert exam_already_taken(TEST_1, tmp_path) is None

    def test_ordinary_reports_do_not_count_as_an_exam(self, tmp_path: Path) -> None:
        _write(tmp_path, "screen.json", {"security_ids": ["A"], "results": {}})
        assert exam_already_taken(TEST_3, tmp_path) is None


class TestVerdict:
    def test_pass_needs_both_cagr_and_sharpe_above_baseline(self) -> None:
        baseline = {"cagr": 0.10, "sharpe_ratio": 0.8}
        assert exam_verdict({"cagr": 0.12, "sharpe_ratio": 0.9}, baseline) == "PASS"
        assert exam_verdict({"cagr": 0.12, "sharpe_ratio": 0.7}, baseline) == "FAIL"
        assert exam_verdict({"cagr": 0.10, "sharpe_ratio": 0.9}, baseline) == "FAIL"


def test_locked_window_by_name() -> None:
    assert locked_window_by_name("TEST-3") is TEST_3
    with pytest.raises(KeyError):
        locked_window_by_name("TEST-9")
