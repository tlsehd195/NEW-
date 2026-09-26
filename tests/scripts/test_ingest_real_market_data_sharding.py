"""ADR-0213: `scripts/ingest_real_market_data.py`'s `--tiingo-only`
and `--shard-index`/`--shard-count` flags, run end to end via `main()`
with every HTTP transport replaced by an in-process fake (no network).

`--tiingo-only` exists because Twelve Data/Alpha Vantage free tiers
truncate long histories (5,000 / ~100 bars), so a long backfill must
fail loudly on a Tiingo error rather than silently fall back."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from data_infra.providers.tiingo_transport import TiingoTransportResponse
from data_infra.universe import SymbolMetadata, UniverseDefinition

from storage.config import StorageConfig
from storage.data_repository import DuckDBDataRepository
from storage.engine import StorageEngine

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ingest_real_market_data.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("ingest_real_market_data_sharding_test", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_TIINGO_ROW = {
    "date": "2024-01-02T00:00:00.000Z", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5,
    "volume": 1000.0, "adjClose": 10.5, "adjHigh": 11.0, "adjLow": 9.5, "divCash": 0.0, "splitFactor": 1.0,
}


class _FakeTiingoTransport:
    calls: list[str] = []

    def __init__(self, base_url, *, budget=None) -> None:
        pass

    def get(self, path, *, params, timeout):
        _FakeTiingoTransport.calls.append(path)
        return TiingoTransportResponse(status_code=200, body=[dict(_TIINGO_ROW)], raw_text=None, headers={})


class _ForbiddenTransport:
    def __init__(self, base_url, **kwargs) -> None:
        pass

    def get(self, *args, **kwargs):
        raise AssertionError("a fallback provider was called under --tiingo-only")


def _universe(symbols: list[str]) -> UniverseDefinition:
    return UniverseDefinition(
        name="TEST", version="t", role="RESEARCH", description="test",
        symbols=tuple(SymbolMetadata(symbol=s) for s in symbols),
    )


@pytest.fixture
def module(monkeypatch):
    mod = _load_module()
    _FakeTiingoTransport.calls = []
    monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")
    monkeypatch.setattr(mod, "TiingoHttpTransport", _FakeTiingoTransport)
    monkeypatch.setattr(mod, "TwelveDataHttpTransport", _ForbiddenTransport)
    monkeypatch.setattr(mod, "AlphaVantageHttpTransport", _ForbiddenTransport)
    mod._UNIVERSES["TEST_UNIVERSE"] = _universe(["DDD", "AAA", "CCC", "BBB", "EEE"])
    return mod


def _run(module, monkeypatch, tmp_path, *extra: str) -> int:
    argv = [
        "ingest_real_market_data.py", "--universe", "TEST_UNIVERSE",
        "--start", "2024-01-02", "--end", "2024-01-02", "--db-path", str(tmp_path / "db"), "--tiingo-only", *extra,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    return module.main()


def _fetched_symbols() -> set[str]:
    return {path.split("/")[3] for path in _FakeTiingoTransport.calls}


def test_shard_zero_takes_every_nth_sorted_symbol_plus_the_benchmark(module, monkeypatch, tmp_path) -> None:
    assert _run(module, monkeypatch, tmp_path, "--shard-index", "0", "--shard-count", "2") == 0
    assert _fetched_symbols() == {"AAA", "CCC", "EEE", "SPY"}


def test_later_shard_excludes_the_benchmark(module, monkeypatch, tmp_path) -> None:
    assert _run(module, monkeypatch, tmp_path, "--shard-index", "1", "--shard-count", "2") == 0
    assert _fetched_symbols() == {"BBB", "DDD"}


def test_every_universe_symbol_is_registered_even_when_only_one_shard_is_fetched(module, monkeypatch, tmp_path) -> None:
    assert _run(module, monkeypatch, tmp_path, "--shard-index", "1", "--shard-count", "2") == 0
    engine = StorageEngine(StorageConfig(root_dir=tmp_path / "db"))
    try:
        rows = engine.connection.execute("SELECT security_id FROM security_master").fetchall()
    finally:
        engine.close()
    assert {r[0] for r in rows} == {"AAA", "BBB", "CCC", "DDD", "EEE"}


def test_sequential_shards_into_one_catalog_cover_the_whole_universe(module, monkeypatch, tmp_path) -> None:
    for index in range(3):
        assert _run(module, monkeypatch, tmp_path, "--shard-index", str(index), "--shard-count", "3") == 0
    engine = StorageEngine(StorageConfig(root_dir=tmp_path / "db"))
    try:
        repository = DuckDBDataRepository(engine)
        covered = {
            s for s in ("AAA", "BBB", "CCC", "DDD", "EEE", "SPY")
            if repository.get_bars(s, *_range(), _range()[1], include_quality_rejected=True)
        }
    finally:
        engine.close()
    assert covered == {"AAA", "BBB", "CCC", "DDD", "EEE", "SPY"}


def _range():
    from datetime import datetime, timezone

    return datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 1, 3, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "extra",
    [
        ("--shard-index", "0"),
        ("--shard-count", "2"),
        ("--shard-index", "2", "--shard-count", "2"),
        ("--shard-index", "0", "--shard-count", "2", "--symbols", "AAA"),
    ],
)
def test_invalid_shard_arguments_are_rejected(module, monkeypatch, tmp_path, extra) -> None:
    with pytest.raises(SystemExit):
        _run(module, monkeypatch, tmp_path, *extra)


def _load_coverage_module():
    path = _SCRIPT_PATH.parent / "report_price_catalog_coverage.py"
    spec = importlib.util.spec_from_file_location("report_price_catalog_coverage_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_coverage_report_fails_until_every_shard_is_ingested(module, monkeypatch, tmp_path, capsys) -> None:
    coverage = _load_coverage_module()
    coverage._UNIVERSES["TEST_UNIVERSE"] = module._UNIVERSES["TEST_UNIVERSE"]
    argv = ["report_price_catalog_coverage.py", "--db-path", str(tmp_path / "db"), "--universe", "TEST_UNIVERSE", "--start", "2024-01-02"]

    assert _run(module, monkeypatch, tmp_path, "--shard-index", "0", "--shard-count", "2") == 0
    monkeypatch.setattr(sys, "argv", argv)
    assert coverage.main() == 1
    assert "zero bars for ['BBB', 'DDD']" in capsys.readouterr().err

    assert _run(module, monkeypatch, tmp_path, "--shard-index", "1", "--shard-count", "2") == 0
    monkeypatch.setattr(sys, "argv", argv)
    assert coverage.main() == 0
