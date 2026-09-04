"""Session 36 structural regression tests for
`scripts/fetch_sector_classifications.py` (ADR-0055).

This script is deliberately never imported or executed by the
automated test suite -- it makes a real network call to SEC EDGAR when
run (see its own module docstring), which this environment's egress is
blocked from making. These tests work entirely on its SOURCE TEXT/AST
-- never `import` it, never call `main()` -- the same discipline
`tests/data_infra/test_ingest_fundamentals_data_wiring.py` already
established for the sibling real-ingestion script this one mirrors."""

from __future__ import annotations

import ast
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "fetch_sector_classifications.py"


def _source() -> str:
    return _SCRIPT_PATH.read_text()


def _tree() -> ast.Module:
    return ast.parse(_source(), filename=str(_SCRIPT_PATH))


def _report_dict_node(tree: ast.Module) -> ast.Dict:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "report"
            and isinstance(node.value, ast.Dict)
        ):
            return node.value
    raise AssertionError("expected a `report = {...}` dict literal assignment")


def _report_keys(tree: ast.Module) -> set[str]:
    report = _report_dict_node(tree)
    return {k.value for k in report.keys if isinstance(k, ast.Constant)}


class TestScriptIsSyntacticallyValid:
    def test_parses_without_error(self) -> None:
        _tree()  # raises SyntaxError on failure


class TestNoWallClockReads:
    def test_script_never_calls_datetime_now_or_utcnow(self) -> None:
        source = _source()
        assert "datetime.now(" not in source
        assert ".utcnow()" not in source


class TestUserAgentHasNoSilentDefault:
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


class TestDoesNotWriteIntoUniversePy:
    """The one property this script's own docstring promises most
    explicitly -- real findings go to a JSON report, never a direct
    edit of `src/data_infra/universe.py`'s hand-curated SymbolMetadata
    literals. Checked by confirming the script only imports the two
    already-built universe constants (read-only lookups), never
    `SymbolMetadata`/`UniverseDefinition` themselves (which would be
    needed to construct or modify a universe definition)."""

    def test_imports_only_the_two_universe_constants(self) -> None:
        # The docstring itself discusses SymbolMetadata/UniverseDefinition
        # in prose (explaining why this script does NOT touch them) --
        # checked here at the AST level (real import statements and
        # constructor calls only), not a substring check that would
        # also flag those explanatory mentions.
        tree = _tree()
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert "SymbolMetadata" not in imported_names
        assert "UniverseDefinition" not in imported_names
        assert "SymbolMetadata(" not in _source()
        assert "UniverseDefinition(" not in _source()


class TestReportReflectsWhatEdgarActuallyReturned:
    def test_report_has_the_expected_keys(self) -> None:
        keys = _report_keys(_tree())
        assert {
            "universe_name", "as_of", "symbols_requested", "unresolved_symbols",
            "per_symbol_results", "content_checksum",
        } <= keys


class TestUnresolvedSymbolsNeverSilentlyDropped:
    def test_unresolved_symbols_list_is_populated_when_resolve_cik_returns_none(self) -> None:
        source = _source()
        assert "unresolved_symbols.append" in source
        assert "resolve_cik(symbol, ticker_map)" in source


class TestCikOverrides:
    def test_cik_overrides_argument_exists(self) -> None:
        tree = _tree()
        found = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "--cik-overrides"
            for node in ast.walk(tree)
        )
        assert found, "expected a --cik-overrides argparse argument"

    def test_known_cik_overrides_dict_exists_and_has_xom(self) -> None:
        tree = _tree()
        found = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "_KNOWN_CIK_OVERRIDES"
                and isinstance(node.value, ast.Dict)
            ):
                found = True
                pairs = {k.value: v.value for k, v in zip(node.value.keys, node.value.values)}
                assert pairs.get("XOM") == "0000034088"
        assert found, "expected a _KNOWN_CIK_OVERRIDES = {...} dict literal"


class TestPerSymbolLoopCatchesValueErrorAlongsideProviderErrors:
    """Same defensive discipline `ingest_fundamentals_data.py`'s own
    per-symbol loop now applies (a real crash from one malformed EDGAR
    entry took down an entire 24-symbol run there) -- applied here from
    the start rather than discovered the same way twice."""

    def test_the_per_symbol_except_clause_also_catches_value_error(self) -> None:
        source = _source()
        loop_start = source.index("for i, symbol in enumerate(symbols, start=1):")
        except_index = source.index("except (", loop_start)
        line_end = source.index("\n", except_index)
        except_line = source[except_index:line_end]
        assert "ValueError" in except_line
        assert "TransientProviderError" in except_line
        assert "PermanentProviderError" in except_line
