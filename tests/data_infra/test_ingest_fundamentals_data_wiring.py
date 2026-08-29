"""Phase 33 structural regression tests for
`scripts/ingest_fundamentals_data.py` (ADR-0042).

This script is deliberately never imported or executed by the
automated test suite -- it makes a real network call to SEC EDGAR when
run (see its own module docstring), which this environment's egress is
blocked from making. These tests work entirely on its SOURCE TEXT/AST
-- never `import` it, never call `main()` -- the same discipline
`tests/data_infra/test_ingest_real_market_data_wiring.py` already
established for the price-data ingestion script."""

from __future__ import annotations

import ast
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ingest_fundamentals_data.py"


def _source() -> str:
    return _SCRIPT_PATH.read_text()


def _tree() -> ast.Module:
    return ast.parse(_source(), filename=str(_SCRIPT_PATH))


def _manifest_dict_node(tree: ast.Module) -> ast.Dict:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "manifest"
            and isinstance(node.value, ast.Dict)
        ):
            return node.value
    raise AssertionError("expected a `manifest = {...}` dict literal assignment")


def _manifest_keys(tree: ast.Module) -> set[str]:
    manifest = _manifest_dict_node(tree)
    return {k.value for k in manifest.keys if isinstance(k, ast.Constant)}


class TestNoWallClockReads:
    """Point-in-time / reproducibility discipline: `retrieved_at`/
    `ingestion_time` must come from the caller-supplied `--as-of`, never
    from `datetime.now()`/`datetime.utcnow()` (instruction section 13,
    already enforced the same way in `ingest_real_market_data.py`)."""

    def test_script_never_calls_datetime_now_or_utcnow(self) -> None:
        source = _source()
        assert "datetime.now(" not in source
        assert ".utcnow()" not in source


class TestUserAgentHasNoSilentDefault:
    """SEC's fair-access policy requires a genuine descriptive contact
    string -- this script must refuse to run without one explicitly
    supplied, not silently fall back to SecEdgarConfig's own
    test-only placeholder default."""

    def test_user_agent_argument_is_required(self) -> None:
        tree = _tree()
        found = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "--user-agent"
            ):
                found = True
                kwargs = {kw.arg: kw.value for kw in node.keywords}
                assert "required" in kwargs
                assert isinstance(kwargs["required"], ast.Constant)
                assert kwargs["required"].value is True
                assert "default" not in kwargs
        assert found, "expected a --user-agent argparse argument"


class TestManifestReportsWhatEdgarActuallyReturned:
    def test_manifest_has_the_expected_keys(self) -> None:
        keys = _manifest_keys(_tree())
        assert {
            "data_status", "provider", "symbols", "concepts", "unresolved_symbols",
            "total_records_persisted", "per_symbol_results", "content_checksum",
        } <= keys

    def test_manifest_declares_data_status_real(self) -> None:
        tree = _tree()
        manifest = _manifest_dict_node(tree)
        pairs = {k.value: v for k, v in zip(manifest.keys, manifest.values) if isinstance(k, ast.Constant)}
        assert isinstance(pairs["data_status"], ast.Constant)
        assert pairs["data_status"].value == "REAL"

    def test_manifest_declares_provider_sec_edgar(self) -> None:
        tree = _tree()
        manifest = _manifest_dict_node(tree)
        pairs = {k.value: v for k, v in zip(manifest.keys, manifest.values) if isinstance(k, ast.Constant)}
        assert isinstance(pairs["provider"], ast.Constant)
        assert pairs["provider"].value == "sec_edgar"


class TestUnresolvedSymbolsNeverSilentlyDropped:
    def test_unresolved_symbols_list_is_populated_when_resolve_cik_returns_none(self) -> None:
        source = _source()
        assert "unresolved_symbols.append" in source
        assert "resolve_cik(symbol, ticker_map)" in source


class TestScriptIsSyntacticallyValid:
    def test_parses_without_error(self) -> None:
        _tree()  # raises SyntaxError on failure
