"""Category: the observe-only Sahm log (ADR-0220 follow-up) appends only on
a new release or revision, and reports a flip of the rule's state."""

from __future__ import annotations

import importlib.util
import json
from datetime import date, datetime, timezone
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "record_sahm_observation.py"


def _load():
    spec = importlib.util.spec_from_file_location("record_sahm_observation", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _months(rates):
    out = []
    for i, r in enumerate(rates):
        y, m = divmod(2025 * 12 + i, 12)
        out.append((date(y, m + 1, 1), r))
    return out


_NOW = datetime(2026, 5, 10, tzinfo=timezone.utc)  # last month 2026-04 is fresh


def test_entry_reports_the_gap_and_state() -> None:
    mod = _load()
    entry = mod.build_entry(_months([4.0] * 13 + [4.0, 4.6, 4.9]), _NOW)
    assert entry["active"] is True and entry["implied_exposure"] == 0.5
    assert entry["gap"] == 0.5
    calm = mod.build_entry(_months([4.0] * 16), _NOW)
    assert calm["active"] is False and calm["implied_exposure"] == 1.0


def test_log_appends_only_on_change(tmp_path, monkeypatch) -> None:
    mod = _load()
    log = tmp_path / "sahm.jsonl"
    entry = mod.build_entry(_months([4.0] * 16), _NOW)
    assert mod.changed(None, entry)
    log.write_text(json.dumps(entry) + "\n")
    assert not mod.changed(mod.last_entry(log), dict(entry, recorded_at="later"))
    revised = mod.build_entry(_months([4.0] * 15 + [4.1]), _NOW)
    assert mod.changed(mod.last_entry(log), revised)


def test_stale_data_gives_no_entry() -> None:
    mod = _load()
    assert mod.build_entry(_months([4.0] * 16), datetime(2026, 12, 1, tzinfo=timezone.utc)) is None
