"""Real, executable tests for
`scripts/ingest_stockanalysis_wayback_delisted_prices.py`.

The three HTML fixtures below are the ACTUAL fragments recovered
during the real 2026-09-19 recon session against Wayback Machine
snapshots of `stockanalysis.com/stocks/avb/` (AvalonBay Communities) --
not synthesized approximations -- confirming the three real site
layouts this script's own parser must handle. The real network calls
(CDX query, snapshot fetch) are mocked; everything downstream (parsing,
PriceBar construction, real DuckDB/Parquet persistence via
DuckDBDataRepository.append_bars, the manifest) is exercised for real,
mirroring `test_ingest_fama_french_factors.py`'s "import the script,
call main() against a real temp catalog" pattern."""

from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import pytest

from storage.config import StorageConfig
from storage.data_repository import DuckDBDataRepository
from storage.engine import StorageEngine

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ingest_stockanalysis_wayback_delisted_prices.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("ingest_stockanalysis_wayback_delisted_prices", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Real fragment, era A (~2020-08 to ~2021-04), from the real
# 20200806221508 AVB snapshot.
_REAL_ERA_A_FRAGMENT = """
<div id="sp">Stock Price: <span id="cpr">$150.97</span> <span class="scurr">USD</span>
<table>
<tbody>
<tr><td>Trading Day</td><td id="qDay">Aug 6, 2020</td></tr>
<tr><td>Last Price</td><td id="qLast">$150.97</td></tr>
<tr><td>Previous Close</td>
"""

# Real fragment, era C (~2021-10 to ~2023-03), from the real
# 20220808230809 AVB snapshot -- note the Svelte scoped-class hash
# (svelte-vtorfu) is build-specific and must be matched generically.
_REAL_ERA_C_FRAGMENT = """
<div class="wrap svelte-vtorfu"><div class="svelte-vtorfu"><div class="p svelte-vtorfu">206.44</div>
<div class="pc text-green-700 svelte-vtorfu">+1.53 (0.75%)</div>
"""

# Real fragment, era B (~2023-04 onward), from the real 20240913193622
# AVB snapshot.
_REAL_ERA_B_FRAGMENT = """
<div class=""> <div class="text-4xl font-bold inline-block">233.52</div>
<div class="font-semibold inline-block text-2xl text-green-vivid">+1.82 (0.79%)</div>
"""

# Real fragment, era B with extra Tailwind classes added in a later
# real redesign (the 20250328092949 AVB snapshot) -- confirms the
# wildcard between "font-bold" and "inline-block" is load-bearing.
_REAL_ERA_B_LATER_FRAGMENT = """
<div class=""> <div class="text-4xl font-bold transition-colors duration-300 inline-block">213.14</div>
<div class="font-semibold inline-block text-2xl text-red-vivid">-0.95 (-0.44%)</div>
"""

_REAL_CDX_RESPONSE = [
    ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
    ["com,stockanalysis)/stocks/avb", "20200806221508", "https://stockanalysis.com/stocks/avb/", "text/html", "200", "UCDDRUKFSK445XOM755USLCMOHYX6H75", "11096"],
    ["com,stockanalysis)/stocks/avb", "20230426002316", "https://stockanalysis.com/stocks/avb", "unk", "308", "3I42H3S6NNFQ2MSVX7XZKYAYSCX5QBYJ", "357"],
    ["com,stockanalysis)/stocks/avb", "20240913193622", "https://stockanalysis.com/stocks/avb/", "text/html", "200", "OFIUOG2UVA3ZAZRGMURKR4HBN3BCXECK", "26716"],
]


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestExtractPrice:
    def test_matches_real_era_a_layout(self) -> None:
        module = _load_module()
        assert module.extract_price(_REAL_ERA_A_FRAGMENT) == pytest.approx(150.97)

    def test_matches_real_era_c_layout_with_generic_svelte_hash(self) -> None:
        module = _load_module()
        assert module.extract_price(_REAL_ERA_C_FRAGMENT) == pytest.approx(206.44)

    def test_matches_real_era_b_layout(self) -> None:
        module = _load_module()
        assert module.extract_price(_REAL_ERA_B_FRAGMENT) == pytest.approx(233.52)

    def test_matches_real_era_b_layout_with_extra_classes_added_later(self) -> None:
        module = _load_module()
        assert module.extract_price(_REAL_ERA_B_LATER_FRAGMENT) == pytest.approx(213.14)

    def test_returns_none_when_no_known_pattern_matches(self) -> None:
        module = _load_module()
        assert module.extract_price("<html><body>no price here</body></html>") is None


class TestParseCdxTimestamp:
    def test_parses_the_real_fourteen_digit_utc_format(self) -> None:
        module = _load_module()
        assert module._parse_cdx_timestamp("20200806221508") == datetime(2020, 8, 6, 22, 15, 8, tzinfo=timezone.utc)


class TestFetchSnapshotList:
    def test_filters_to_real_200_text_html_snapshots_only(self, monkeypatch) -> None:
        module = _load_module()
        body = json.dumps(_REAL_CDX_RESPONSE).encode()
        monkeypatch.setattr(module.urllib.request, "urlopen", lambda request, timeout: _FakeResponse(body))
        snapshots = module.fetch_snapshot_list("AVB")
        assert len(snapshots) == 2  # the real 308 redirect row is excluded
        assert all(s["statuscode"] == "200" for s in snapshots)

    def test_empty_cdx_response_returns_empty_list(self, monkeypatch) -> None:
        module = _load_module()
        monkeypatch.setattr(module.urllib.request, "urlopen", lambda request, timeout: _FakeResponse(b"[]"))
        assert module.fetch_snapshot_list("ZZZZ") == []


class TestMainEndToEnd:
    def test_ingests_real_recovered_prices_across_two_eras_into_a_real_catalog(self, tmp_path, monkeypatch, capsys) -> None:
        module = _load_module()
        cdx_body = json.dumps(_REAL_CDX_RESPONSE).encode()
        html_bodies = {
            "20200806221508": _REAL_ERA_A_FRAGMENT.encode(),
            "20240913193622": _REAL_ERA_B_FRAGMENT.encode(),
        }

        def fake_urlopen(request, timeout):
            url = request.full_url if hasattr(request, "full_url") else request
            if "cdx/search" in url:
                return _FakeResponse(cdx_body)
            for ts, body in html_bodies.items():
                if ts in url:
                    return _FakeResponse(body)
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(module.time, "sleep", lambda s: None)

        db_path = tmp_path / "wayback_catalog"
        exit_code = module.main(["--symbols", "AVB", "--as-of", "2026-09-19", "--db-path", str(db_path)])
        assert exit_code == 0

        engine = StorageEngine(StorageConfig(root_dir=db_path))
        repository = DuckDBDataRepository(engine)
        bars = repository.get_bars("AVB", datetime(2000, 1, 1, tzinfo=timezone.utc), datetime(2100, 1, 1, tzinfo=timezone.utc), as_of_time=datetime(2100, 1, 1, tzinfo=timezone.utc))
        assert len(bars) == 2
        prices = sorted(b.close for b in bars)
        assert prices == [pytest.approx(150.97), pytest.approx(233.52)]
        assert all(b.open == b.high == b.low == b.close for b in bars)
        assert all(b.volume == 0.0 for b in bars)
        assert all(b.provenance.source == "stockanalysis_com_via_wayback_machine" for b in bars)
        engine.close()

        manifest = json.loads((db_path / "wayback_ingestion_manifest.json").read_text())
        assert manifest["total_bars_written"] == 2
        assert manifest["per_symbol_results"][0]["bars_persisted"] == 2

    def test_a_snapshot_matching_no_pattern_is_recorded_as_a_parse_failure_not_silently_dropped(self, tmp_path, monkeypatch) -> None:
        module = _load_module()
        cdx = [
            ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
            ["com,stockanalysis)/stocks/zzzz", "20220101000000", "https://stockanalysis.com/stocks/zzzz/", "text/html", "200", "X", "1"],
        ]
        cdx_body = json.dumps(cdx).encode()

        def fake_urlopen(request, timeout):
            url = request.full_url if hasattr(request, "full_url") else request
            if "cdx/search" in url:
                return _FakeResponse(cdx_body)
            return _FakeResponse(b"<html>no price here</html>")

        monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(module.time, "sleep", lambda s: None)

        db_path = tmp_path / "wayback_catalog"
        exit_code = module.main(["--symbols", "ZZZZ", "--as-of", "2026-09-19", "--db-path", str(db_path)])
        assert exit_code == 0  # a per-snapshot parse failure is not a fatal run failure

        manifest = json.loads((db_path / "wayback_ingestion_manifest.json").read_text())
        result = manifest["per_symbol_results"][0]
        assert result["bars_persisted"] == 0
        assert result["parse_failures"] == 1
        assert "no known real price pattern matched" in result["parse_failure_detail"][0]["error"]

    def test_snapshot_list_fetch_failure_is_recorded_as_a_failed_symbol(self, tmp_path, monkeypatch) -> None:
        module = _load_module()

        def fake_urlopen(request, timeout):
            raise urllib.error.URLError("egress blocked")

        monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(module.time, "sleep", lambda s: None)

        db_path = tmp_path / "wayback_catalog"
        exit_code = module.main(["--symbols", "AVB", "--as-of", "2026-09-19", "--db-path", str(db_path)])
        assert exit_code == 1

        manifest = json.loads((db_path / "wayback_ingestion_manifest.json").read_text())
        assert manifest["per_symbol_results"][0]["error"] is not None

    def test_running_twice_is_idempotent(self, tmp_path, monkeypatch) -> None:
        module = _load_module()
        cdx_body = json.dumps(_REAL_CDX_RESPONSE).encode()
        html_bodies = {
            "20200806221508": _REAL_ERA_A_FRAGMENT.encode(),
            "20240913193622": _REAL_ERA_B_FRAGMENT.encode(),
        }

        def fake_urlopen(request, timeout):
            url = request.full_url if hasattr(request, "full_url") else request
            if "cdx/search" in url:
                return _FakeResponse(cdx_body)
            for ts, body in html_bodies.items():
                if ts in url:
                    return _FakeResponse(body)
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(module.time, "sleep", lambda s: None)

        db_path = tmp_path / "wayback_catalog"
        module.main(["--symbols", "AVB", "--as-of", "2026-09-19", "--db-path", str(db_path)])
        module.main(["--symbols", "AVB", "--as-of", "2026-09-19", "--db-path", str(db_path)])

        engine = StorageEngine(StorageConfig(root_dir=db_path))
        repository = DuckDBDataRepository(engine)
        bars = repository.get_bars("AVB", datetime(2000, 1, 1, tzinfo=timezone.utc), datetime(2100, 1, 1, tzinfo=timezone.utc), as_of_time=datetime(2100, 1, 1, tzinfo=timezone.utc))
        assert len(bars) == 2  # not duplicated
        engine.close()
