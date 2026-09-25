"""Real, executable tests for `scripts/run_ai_prediction_experiment.py`
(ADR-0206). Makes no real network call -- `urllib.request.urlopen` is
monkeypatched to return a canned Gemini response, the same discipline
`tests/ai_gateway/test_ai_gateway_gemini_transport.py` already
establishes (no automated test in this repository may ever call the
real Gemini API). Exercised against a real, locally-seeded DuckDB
catalog (`backtest_helpers.make_bars`/`make_security`), mirroring
`tests/scripts/test_run_monitoring_sweep.py`'s own precedent for a
network-free CLI script test.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

from backtest_helpers import make_bars, make_security, trading_days

from storage.config import StorageConfig
from storage.data_repository import DuckDBDataRepository
from storage.engine import StorageEngine

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_ai_prediction_experiment.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_ai_prediction_experiment", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _seed_catalog(db_path: Path) -> None:
    days = trading_days(date(2024, 1, 2), date(2024, 4, 30))
    closes = [100.0 * (1.002 ** i) for i in range(len(days))]  # steadily rising -- real "UP" outcome
    bars = make_bars("AAA", days, closes)
    engine = StorageEngine(StorageConfig(root_dir=db_path))
    repository = DuckDBDataRepository(engine)
    repository.add_security(make_security("AAA", "AAA"))
    repository.append_bars(bars)
    engine.close()


class _FakeGeminiResponse:
    def __init__(self, body: dict) -> None:
        self.status = 200
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


_CANNED_BODY = {
    "candidates": [{"content": {"parts": [{"text": json.dumps(
        {"direction": "UP", "confidence": 0.7, "reasoning": "steady uptrend"}
    )}]}}],
    "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 20, "totalTokenCount": 70},
}


class TestPredictSubcommand:
    def test_predict_writes_a_prediction_record_and_persists_to_duckdb(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: _FakeGeminiResponse(_CANNED_BODY))

        db_path = tmp_path / "market_data"
        _seed_catalog(db_path)
        out_path = tmp_path / "predictions.json"

        module = _load_module()
        rc = module.main([
            "predict", "--db-path", str(db_path), "--universe", "AAA",
            "--as-of", "2024-02-15", "--horizon-days", "5", "--lookback-days", "15",
            "--pause-seconds", "0", "--output", str(out_path),
        ])
        assert rc == 0

        payload = json.loads(out_path.read_text())
        assert payload["as_of"] == "2024-02-15"
        assert len(payload["predictions"]) == 1
        record = payload["predictions"][0]
        assert record["security_id"] == "AAA"
        assert record["status"] == "SUCCESS"
        assert record["predicted_direction"] == "UP"
        assert record["predicted_confidence"] == 0.7

        # Persisted through the real ai_gateway DuckDB repositories, not just the JSON sidecar.
        engine = StorageEngine(StorageConfig(root_dir=db_path), read_only=True)
        try:
            row = engine.connection.execute(
                "SELECT provenance FROM ai_requests WHERE request_id = ?", [record["request_id"]]
            ).fetchone()
            assert row is not None
            assert row[0] == "HISTORICAL_SIMULATION"
        finally:
            engine.close()

    def test_predict_skips_a_security_with_insufficient_history(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        def _fail_if_called(req, timeout):
            raise AssertionError("must never call Gemini for a security with insufficient history")

        monkeypatch.setattr("urllib.request.urlopen", _fail_if_called)

        db_path = tmp_path / "market_data"
        _seed_catalog(db_path)
        out_path = tmp_path / "predictions.json"

        module = _load_module()
        rc = module.main([
            "predict", "--db-path", str(db_path), "--universe", "AAA",
            # Very first trading day on record -- no history at all yet.
            "--as-of", "2024-01-02", "--horizon-days", "5", "--lookback-days", "15",
            "--pause-seconds", "0", "--output", str(out_path),
        ])
        assert rc == 0
        record = json.loads(out_path.read_text())["predictions"][0]
        assert record["status"] == "SKIPPED_INSUFFICIENT_HISTORY"


class TestScoreSubcommand:
    def test_score_reports_correct_prediction_against_the_real_realized_move(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: _FakeGeminiResponse(_CANNED_BODY))

        db_path = tmp_path / "market_data"
        _seed_catalog(db_path)
        predictions_path = tmp_path / "predictions.json"

        module = _load_module()
        rc = module.main([
            "predict", "--db-path", str(db_path), "--universe", "AAA",
            "--as-of", "2024-02-15", "--horizon-days", "5", "--lookback-days", "15",
            "--pause-seconds", "0", "--output", str(predictions_path),
        ])
        assert rc == 0

        scored_path = tmp_path / "scored.json"
        rc = module.main([
            "score", "--db-path", str(db_path), "--predictions", str(predictions_path),
            "--as-of", "2024-04-30", "--output", str(scored_path),
        ])
        assert rc == 0

        result = json.loads(scored_path.read_text())
        assert result["summary"]["scored_count"] == 1
        assert result["summary"]["correct_count"] == 1
        assert result["summary"]["accuracy"] == 1.0
        assert result["predictions"][0]["actual_direction"] == "UP"
        assert result["predictions"][0]["correct"] is True

    def test_score_reports_pending_when_target_day_has_not_happened_yet(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: _FakeGeminiResponse(_CANNED_BODY))

        db_path = tmp_path / "market_data"
        _seed_catalog(db_path)
        predictions_path = tmp_path / "predictions.json"

        module = _load_module()
        module.main([
            "predict", "--db-path", str(db_path), "--universe", "AAA",
            "--as-of", "2024-04-25", "--horizon-days", "5", "--lookback-days", "15",
            "--pause-seconds", "0", "--output", str(predictions_path),
        ])

        scored_path = tmp_path / "scored.json"
        rc = module.main([
            "score", "--db-path", str(db_path), "--predictions", str(predictions_path),
            # Catalog only has data through 2024-04-30 -- not enough trading days after 2024-04-25 for a 5-day horizon.
            "--as-of", "2024-04-30", "--output", str(scored_path),
        ])
        assert rc == 0
        result = json.loads(scored_path.read_text())
        assert result["summary"]["scored_count"] == 0
        assert result["summary"]["pending_count"] == 1
