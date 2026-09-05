"""Session 36 tests for `scripts/compute_sp500_pit_listed_from.py`
(ADR-0061).

Unlike `fetch_sector_classifications.py`, this script makes no network
call -- it only reads a local CSV path -- so these tests run it
end-to-end via a small synthetic fixture CSV, rather than relying on
AST/source-text checks alone."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "compute_sp500_pit_listed_from.py"


def _load_main():
    spec = importlib.util.spec_from_file_location("compute_sp500_pit_listed_from", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.main


_FIXTURE_CSV = '''date,tickers
2010-01-04,"AAA,BBB,CCC"
2015-06-01,"AAA,BBB,CCC,DDD"
2020-01-02,"AAA,CCC,DDD"
2024-12-30,"AAA,CCC,DDD,EEE"
'''


def _write_fixture(tmp_path: Path) -> Path:
    csv_path = tmp_path / "sp_500_historical_components.csv"
    csv_path.write_text(_FIXTURE_CSV)
    return csv_path


class TestEndToEndAgainstExplicitSymbols:
    def test_left_censored_symbol_has_no_confirmable_listed_from(self, tmp_path) -> None:
        main = _load_main()
        csv_path = _write_fixture(tmp_path)
        out_path = tmp_path / "report.json"
        rc = main(["--csv-path", str(csv_path), "--symbols", "AAA", "--out", str(out_path)])
        assert rc == 0
        report = json.loads(out_path.read_text())
        result = report["per_symbol_results"][0]
        assert result["security_id"] == "AAA"
        assert result["found"] is True
        assert result["left_censored"] is True
        assert result["confirmable_listed_from"] is None
        assert result["right_censored"] is True
        assert result["left_the_index"] is False

    def test_symbol_added_after_first_snapshot_gets_a_confirmable_date(self, tmp_path) -> None:
        main = _load_main()
        csv_path = _write_fixture(tmp_path)
        out_path = tmp_path / "report.json"
        rc = main(["--csv-path", str(csv_path), "--symbols", "DDD", "--out", str(out_path)])
        assert rc == 0
        report = json.loads(out_path.read_text())
        result = report["per_symbol_results"][0]
        assert result["confirmable_listed_from"] == "2015-06-01"
        assert result["left_censored"] is False
        assert result["added_uncertainty_days"] == 1974  # (date(2015,6,1) - date(2010,1,4)).days
        assert result["right_censored"] is True

    def test_symbol_that_left_the_index_is_flagged_not_auto_applied(self, tmp_path) -> None:
        main = _load_main()
        csv_path = _write_fixture(tmp_path)
        out_path = tmp_path / "report.json"
        rc = main(["--csv-path", str(csv_path), "--symbols", "BBB", "--out", str(out_path)])
        assert rc == 0
        report = json.loads(out_path.read_text())
        result = report["per_symbol_results"][0]
        assert result["right_censored"] is False
        assert result["left_the_index"] is True
        assert report["left_the_index"] == ["BBB"]

    def test_symbol_never_seen_in_the_dataset_is_reported_not_silently_dropped(self, tmp_path) -> None:
        main = _load_main()
        csv_path = _write_fixture(tmp_path)
        out_path = tmp_path / "report.json"
        rc = main(["--csv-path", str(csv_path), "--symbols", "ZZZ", "--out", str(out_path)])
        assert rc == 0
        report = json.loads(out_path.read_text())
        result = report["per_symbol_results"][0]
        assert result["found"] is False
        assert result["confirmable_listed_from"] is None
        assert result["left_censored"] is None
        assert result["left_the_index"] is None


class TestReportShape:
    def test_report_has_expected_top_level_keys(self, tmp_path) -> None:
        main = _load_main()
        csv_path = _write_fixture(tmp_path)
        out_path = tmp_path / "report.json"
        main(["--csv-path", str(csv_path), "--symbols", "AAA", "EEE", "--out", str(out_path)])
        report = json.loads(out_path.read_text())
        assert {
            "note", "source_first_snapshot", "source_last_snapshot", "symbols_requested",
            "confirmed_listed_from_count", "left_the_index", "per_symbol_results", "content_checksum",
        } <= set(report)
        assert report["source_first_snapshot"] == "2010-01-04"
        assert report["source_last_snapshot"] == "2024-12-30"
        assert report["symbols_requested"] == 2

    def test_missing_csv_path_fails_cleanly_not_a_traceback(self, tmp_path) -> None:
        main = _load_main()
        rc = main(["--csv-path", str(tmp_path / "does_not_exist.csv"), "--symbols", "AAA", "--out", str(tmp_path / "out.json")])
        assert rc == 1


class TestUniverseSelection:
    def test_all_universe_selection_covers_pilot_and_research_symbols(self, tmp_path) -> None:
        from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE4

        main = _load_main()
        csv_path = _write_fixture(tmp_path)
        out_path = tmp_path / "report.json"
        main(["--csv-path", str(csv_path), "--universe", "ALL", "--out", str(out_path)])
        report = json.loads(out_path.read_text())
        expected = {s for u in (PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE4) for s in u.symbol_ids}
        actual = {r["security_id"] for r in report["per_symbol_results"]}
        assert actual == expected
