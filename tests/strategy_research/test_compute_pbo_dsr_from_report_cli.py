"""Real, executable tests for
`scripts/compute_pbo_dsr_from_report.py` (reads an existing report
JSON, computes PBO/DSR, writes an updated report -- no network call,
no backtest re-run, so `main()` is called directly here just like
`tests/data_infra/test_import_external_market_data_cli.py` does for
`scripts/import_external_market_data.py`).

SYNTHETIC report fixtures only -- proves the CLI mechanism works
correctly against a report shaped exactly like a real
`run_long_horizon_validation.py` output, not a claim about any real
strategy result."""

from __future__ import annotations

import importlib.util
import json
import random
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "compute_pbo_dsr_from_report.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("compute_pbo_dsr_from_report", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_folds(rng: random.Random, mean: float, stdev: float, n: int) -> list[dict]:
    return [
        {
            "fold_index": i,
            "net": {"cumulative_return": rng.gauss(mean, stdev), "sharpe_ratio": 0.5},
        }
        for i in range(n)
    ]


def _fake_report(rng: random.Random, *, data_status: str = "REAL", n_folds: int = 40) -> dict:
    return {
        "data_status": data_status,
        "results": {
            "good": {"walk_forward": {
                "train_window_months": 6, "test_window_months": 2, "step_months": 2,
                "fold_count": n_folds, "positive_net_return_folds": n_folds,
                "median_net_cumulative_return": 0.02, "median_net_sharpe": 0.5,
                "stdev_net_cumulative_return": 0.01, "worst_max_drawdown": -0.05,
                "worst_fold_index": 0, "best_net_cumulative_return": 0.05, "best_fold_index": 1,
                "regime_breakdown": {"BULL": n_folds // 2, "BEAR": n_folds - n_folds // 2},
                "folds": _fake_folds(rng, 0.02, 0.01, n_folds),
            }},
            "noise_a": {"walk_forward": {
                "train_window_months": 6, "test_window_months": 2, "step_months": 2,
                "fold_count": n_folds, "positive_net_return_folds": n_folds // 2,
                "median_net_cumulative_return": 0.0, "median_net_sharpe": 0.1,
                "stdev_net_cumulative_return": 0.01, "worst_max_drawdown": -0.05,
                "worst_fold_index": 0, "best_net_cumulative_return": 0.02, "best_fold_index": 1,
                "regime_breakdown": {"BULL": n_folds // 2, "BEAR": n_folds - n_folds // 2},
                "folds": _fake_folds(rng, 0.0, 0.01, n_folds),
            }},
            "noise_b": {"walk_forward": {
                "train_window_months": 6, "test_window_months": 2, "step_months": 2,
                "fold_count": n_folds, "positive_net_return_folds": n_folds // 2,
                "median_net_cumulative_return": 0.0, "median_net_sharpe": 0.1,
                "stdev_net_cumulative_return": 0.01, "worst_max_drawdown": -0.05,
                "worst_fold_index": 0, "best_net_cumulative_return": 0.02, "best_fold_index": 1,
                "regime_breakdown": {"BULL": n_folds // 2, "BEAR": n_folds - n_folds // 2},
                "folds": _fake_folds(rng, 0.0, 0.01, n_folds),
            }},
        },
    }


class TestComputePboDsrFromReportCli:
    def test_main_computes_and_writes_pbo_dsr_result(self, tmp_path) -> None:
        module = _load_script()
        rng = random.Random(42)
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(_fake_report(rng)))

        exit_code = module.main(["--report", str(report_path)])
        assert exit_code == 0

        updated = json.loads(report_path.read_text())
        assert "pbo_dsr_result" in updated
        assert 0.0 <= updated["pbo_dsr_result"]["pbo_probability"] <= 1.0
        assert set(updated["pbo_dsr_result"]["deflated_sharpe_by_candidate"]) == {"good", "noise_a", "noise_b"}

        good_evidence = updated["results"]["good"]["evidence_assessment"]
        assert good_evidence["pbo_probability"] is not None
        assert good_evidence["deflated_sharpe_ratio"] is not None

    def test_refuses_non_real_data_status(self, tmp_path) -> None:
        module = _load_script()
        rng = random.Random(1)
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(_fake_report(rng, data_status="SYNTHETIC")))

        exit_code = module.main(["--report", str(report_path)])
        assert exit_code == 1
        # Must not have modified the file.
        assert "pbo_dsr_result" not in json.loads(report_path.read_text())

    def test_out_path_does_not_overwrite_original_when_specified(self, tmp_path) -> None:
        module = _load_script()
        rng = random.Random(7)
        report_path = tmp_path / "report.json"
        original = _fake_report(rng)
        report_path.write_text(json.dumps(original))
        out_path = tmp_path / "updated_report.json"

        exit_code = module.main(["--report", str(report_path), "--out", str(out_path)])
        assert exit_code == 0
        assert out_path.is_file()
        assert "pbo_dsr_result" not in json.loads(report_path.read_text())
        assert "pbo_dsr_result" in json.loads(out_path.read_text())

    def test_too_few_qualifying_candidates_fails_cleanly(self, tmp_path) -> None:
        module = _load_script()
        rng = random.Random(3)
        report = _fake_report(rng, n_folds=3)  # below the 6-fold minimum
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(report))

        exit_code = module.main(["--report", str(report_path)])
        assert exit_code == 1

    def test_integrity_invalid_folds_are_excluded_from_pbo_dsr(self, tmp_path) -> None:
        """External audit finding (2026-09-24): this script read every
        fold's cumulative_return unconditionally, including ones with
        an ERROR/CRITICAL integrity issue -- it must now check each
        fold's own is_valid_performance flag first (same fix applied to
        run_long_horizon_validation.py's own PBO/DSR computation)."""
        module = _load_script()
        rng = random.Random(42)
        report = _fake_report(rng)
        # Poison a handful of "good"'s folds with an extreme return AND
        # mark them integrity-invalid -- if the script forgot to filter,
        # these would visibly skew median/PBO/DSR away from the
        # unpoisoned baseline computed by test_main_computes_and_writes_
        # pbo_dsr_result above.
        good_folds = report["results"]["good"]["walk_forward"]["folds"]
        for fold in good_folds[:5]:
            fold["net"]["cumulative_return"] = 9.99
            fold["is_valid_performance"] = False
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(report))

        exit_code = module.main(["--report", str(report_path)])
        assert exit_code == 0

        updated = json.loads(report_path.read_text())
        # The extreme poisoned value must not have pulled the deflated
        # Sharpe ratio up the way including 5/40 folds at +999% would.
        assert updated["pbo_dsr_result"]["deflated_sharpe_by_candidate"]["good"] < 1.0

    def test_different_candidates_with_different_invalid_folds_stay_aligned(self, tmp_path) -> None:
        """The subtler half of the same audit finding: compute_pbo
        requires every candidate's fold-return list to be the same
        length, in the same fold order (position i = the same time
        window for every candidate). Filtering each candidate's own
        invalid folds independently would desynchronize that the moment
        two candidates disagree about WHICH folds are invalid -- this
        must use the common (intersected) set of valid fold indices
        instead, and must not raise."""
        module = _load_script()
        rng = random.Random(11)
        report = _fake_report(rng)
        good_folds = report["results"]["good"]["walk_forward"]["folds"]
        noise_a_folds = report["results"]["noise_a"]["walk_forward"]["folds"]
        # Disjoint invalid sets -- "good" loses folds 0-2, "noise_a"
        # loses folds 3-5. Neither candidate's own valid-fold count
        # drops below the CLI's 6-fold minimum (40 - 3 = 37).
        for fold in good_folds[:3]:
            fold["is_valid_performance"] = False
        for fold in noise_a_folds[3:6]:
            fold["is_valid_performance"] = False
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(report))

        exit_code = module.main(["--report", str(report_path)])
        assert exit_code == 0

        updated = json.loads(report_path.read_text())
        assert set(updated["pbo_dsr_result"]["deflated_sharpe_by_candidate"]) == {"good", "noise_a", "noise_b"}

    def test_no_network_module_is_imported_by_this_script(self) -> None:
        source = _SCRIPT_PATH.read_text()
        for forbidden in ("import requests", "urllib.request", "http.client", "TiingoHttpTransport", "StooqHttpTransport"):
            assert forbidden not in source, f"{forbidden!r} must not appear in a script that claims to make no network call"
