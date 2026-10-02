"""Category: the observe-only SMA log (ADR-0235) decides from past month-end
closes only and reports a risk-off state."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "record_sma_observation.py"


def _load():
    spec = importlib.util.spec_from_file_location("record_sma_observation", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rows(prices):
    return [
        {"datetime": f"{2025 + i // 12}-{i % 12 + 1:02d}-20", "close": str(p)}
        for i, p in enumerate(prices)
    ]


_NOW = datetime(2026, 2, 3, tzinfo=timezone.utc)


def test_rising_prices_stay_invested_and_falling_go_risk_off() -> None:
    mod = _load()
    up = mod.build_entry(mod.rows_to_bars(_rows([float(p) for p in range(100, 113)])), _NOW)
    down = mod.build_entry(mod.rows_to_bars(_rows([float(p) for p in range(112, 99, -1)])), _NOW)
    assert up["implied_exposure"] == 1.0 and up["risk_off"] is False
    assert down["implied_exposure"] == 0.0 and down["risk_off"] is True
    assert up["decision_month"] == "2026-02"


def test_too_little_history_gives_no_entry() -> None:
    mod = _load()
    assert mod.build_entry(mod.rows_to_bars(_rows([100.0] * 5)), _NOW) is None
