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


class TestCikOverrides:
    """Real, observed motivation (Phase 33, ADR-0042): SEC's *current*
    ticker->CIK map resolved 'XOM' to a newly-registered holding-company
    CIK with only 4 filings (a holdco reorganization) instead of the
    operating company's own CIK, which carries 127 real Revenues
    entries. There is no general automatic fix for this -- only a
    manual per-symbol override, checked before falling back to
    resolve_cik."""

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

    def test_override_is_checked_before_resolve_cik_in_the_per_symbol_loop(self) -> None:
        source = _source()
        assert "if symbol in cik_overrides:" in source
        assert "cik = cik_overrides[symbol]" in source
        # Both branches must exist in the same conditional -- resolve_cik
        # is still the fallback, never removed.
        assert "cik = resolve_cik(symbol, ticker_map)" in source

    def test_manifest_records_which_ciks_were_overridden(self) -> None:
        assert "cik_overrides" in _manifest_keys(_tree())

    def test_per_symbol_result_records_cik_source(self) -> None:
        # Auditability: a caller reading the manifest must be able to
        # tell "ticker_map" resolution from a manual "override" without
        # re-deriving it -- not just that an override dict existed
        # somewhere in the run.
        source = _source()
        assert '"cik_source": cik_source' in source


class TestKnownCikOverridesAppliedByDefault:
    """A real run (Session 36) omitted `--cik-overrides XOM:0000034088`
    and silently re-triggered the exact bug ADR-0042 already documented
    and fixed once (XOM resolved to a near-empty holdco CIK again) --
    proof a manual per-run flag is not a durable fix for a *known,
    verified* correction. `_KNOWN_CIK_OVERRIDES` bakes it into the
    script itself so it no longer depends on a human remembering."""

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

    def test_cik_overrides_dict_seeded_from_known_overrides_before_parsing_args(self) -> None:
        source = _source()
        assert "cik_overrides: dict[str, str] = dict(_KNOWN_CIK_OVERRIDES)" in source

    def test_explicit_cik_overrides_flag_can_still_override_the_default(self) -> None:
        # The seeded dict is built, then the --cik-overrides parsing loop
        # runs and assigns into the same dict -- an explicit CLI entry
        # for XOM (or any symbol) still wins over the baked-in default.
        source = _source()
        seed_index = source.index("cik_overrides: dict[str, str] = dict(_KNOWN_CIK_OVERRIDES)")
        assign_index = source.index("cik_overrides[symbol.upper()] = cik.zfill(10)")
        assert seed_index < assign_index


class TestScriptIsSyntacticallyValid:
    def test_parses_without_error(self) -> None:
        _tree()  # raises SyntaxError on failure


class TestPerSymbolLoopSurvivesAValueErrorNotJustProviderErrors:
    """Regression guard: a REAL Stage 4 ingestion run (LMT, symbol
    12/24) crashed this ENTIRE script -- losing every already-fetched
    symbol's progress -- on a `FundamentalRecord.__post_init__`
    ValueError from one malformed upstream EDGAR entry, because the
    per-symbol loop's `except` clause only caught
    `TransientProviderError`/`PermanentProviderError`, not `ValueError`.
    `normalize_company_facts` (`src/data_infra/providers/sec_edgar.py`)
    now also skips the one specific malformed-entry shape found this
    way, but this script's own `except` clause is the correct second
    layer regardless -- checked directly here via source/AST inspection
    (this script is never imported/executed by the automated suite, see
    module docstring), the same discipline this file's other tests
    already use."""

    def test_the_per_symbol_except_clause_also_catches_value_error(self) -> None:
        # Source-text check, not a generic AST walk over every
        # ExceptHandler: this script also has an EARLIER, deliberately
        # narrower except (TransientProviderError, PermanentProviderError)
        # around the one-time ticker-map fetch (not per-symbol, and a
        # ValueError there is not the bug this guards against) -- a
        # blanket "every handler catching both provider errors must also
        # catch ValueError" check would wrongly flag that unrelated
        # clause too. Anchoring on the per-symbol loop's own
        # `records_persisted` line (unique to that loop) keeps this
        # check specific to the right except clause.
        source = _source()
        per_symbol_loop_start = source.index("records_persisted")
        except_index = source.index("except (", per_symbol_loop_start)
        line_end = source.index("\n", except_index)
        except_line = source[except_index:line_end]
        assert "ValueError" in except_line, (
            f"the per-symbol except clause ({except_line!r}) catches the provider errors "
            "but not ValueError -- a single malformed FundamentalRecord would once again "
            "crash the entire run instead of failing just that one symbol"
        )
