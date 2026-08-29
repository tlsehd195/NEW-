"""Real, executable test for
`scripts/analyze_long_horizon_result.py` -- reads an existing report
JSON, prints/writes the Track A decomposition, no network call, no
backtest re-run (same `importlib.util` direct-load pattern
`test_compute_pbo_dsr_from_report_cli.py` already uses).

SYNTHETIC report fixture only."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "analyze_long_horizon_result.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("analyze_long_horizon_result", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_report() -> dict:
    fold = {
        "regime_trend_state": "BULL",
        "gross": {"cumulative_return": 0.03, "turnover": 1.0},
        "net": {"cumulative_return": 0.02, "sharpe_ratio": 0.4, "turnover": 1.0, "total_transaction_cost": 5.0},
    }
    return {
        "data_status": "REAL",
        "universe": "RESEARCH_UNIVERSE",
        "universe_version": "stage2",
        "results": {
            "buy_and_hold": {
                "walk_forward": {"folds": [fold, dict(fold, net={**fold["net"], "cumulative_return": -0.01})]},
                "held_out_test": {
                    "gross": {"cumulative_return": 0.40, "turnover": 0.5},
                    "net": {
                        "cumulative_return": 0.40, "cagr": 0.10, "max_drawdown": -0.26,
                        "turnover": 0.5, "total_transaction_cost": 33.9,
                        "benchmark_cumulative_return": 0.93, "benchmark_cagr": 0.22,
                        "excess_return": -0.53, "annualized_excess_return": -0.12,
                        "benchmark_max_drawdown": -0.19,
                    },
                    "num_trades_net": 30,
                },
                "evidence_assessment": {
                    "level": "ROBUSTNESS_PENDING", "reason": "test",
                    "pbo_probability": 0.0, "deflated_sharpe_ratio": 0.997, "positive_fold_ratio": 0.45,
                },
            },
        },
    }


class TestAnalyzeLongHorizonResultCli:
    def test_runs_end_to_end_and_writes_json_output(self, tmp_path) -> None:
        module = _load_script()
        report_path = tmp_path / "long_horizon_validation.json"
        report_path.write_text(json.dumps(_fake_report()))
        out_path = tmp_path / "analysis.json"

        exit_code = module.main(["--report", str(report_path), "--out", str(out_path)])

        assert exit_code == 0
        assert out_path.exists()
        written = json.loads(out_path.read_text())
        assert len(written) == 1
        assert written[0]["strategy_name"] == "buy_and_hold"
        assert written[0]["fold_distribution"]["fold_count"] == 2
        assert written[0]["held_out_drawdown_field_present"] is False

    def test_prints_not_computable_markers_for_signal_ic_and_capture(self, tmp_path, capsys) -> None:
        module = _load_script()
        report_path = tmp_path / "long_horizon_validation.json"
        report_path.write_text(json.dumps(_fake_report()))

        module.main(["--report", str(report_path)])

        out = capsys.readouterr().out
        assert "NOT_COMPUTABLE_FROM_REPORT" in out
        assert "Signal IC" in out
        assert "upside/downside capture" in out
