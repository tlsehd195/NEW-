"""Session 36 continued structural regression tests for
`scripts/ingest_insider_transactions.py` (ADR-0086).

This script is deliberately never imported or executed by the
automated test suite -- it makes a real network call to SEC EDGAR when
run (see its own module docstring), which this environment's egress is
blocked from making. These tests work entirely on its SOURCE TEXT/AST
-- never `import` it, never call `main()` -- the same discipline
`tests/data_infra/test_ingest_fundamentals_data_wiring.py` already
established for the sibling fundamentals ingestion script."""

from __future__ import annotations

import ast
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ingest_insider_transactions.py"


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


class TestTwoHostTransportsUsedCorrectly:
    """Session 37 continued: this script now deliberately uses TWO
    hosts, unlike its own original single-host design -- the real
    overnight-failure fix switched only the filing-LIST step to
    data.sec.gov (the same host/endpoint class ingest_fundamentals_
    data.py already used with zero failures), while every per-filing
    detail fetch stays on www.sec.gov, unchanged (never implicated in
    the real failures). Verify each call site uses the right one, not
    a mix that would silently 404 against the wrong host."""

    def test_ticker_map_and_per_filing_detail_calls_use_www_transport(self) -> None:
        source = _source()
        assert "provider.fetch_ticker_map(www_transport)" in source
        assert "provider.fetch_form4_index(cik, accession_number, www_transport)" in source
        assert "provider.fetch_form4_document(cik, accession_number, filename, www_transport)" in source

    def test_paginated_filing_list_call_site_uses_data_provider(self) -> None:
        source = _source()
        assert "_fetch_paginated_filing_list(\n                    data_provider, cik," in source

    def test_paginated_filing_list_helper_itself_uses_data_provider_submissions(self) -> None:
        source = _source()
        assert "data_provider.fetch_submissions(cik)" in source
        assert "data_provider.fetch_submissions_file(file_name)" in source

    def test_provider_constructed_with_www_transport(self) -> None:
        source = _source()
        assert "SecEdgarFundamentalsProvider(config, www_transport)" in source

    def test_data_provider_constructed_with_a_data_sec_gov_transport(self) -> None:
        source = _source()
        assert "SecEdgarHttpTransport(config.base_url, user_agent=config.user_agent)" in source
        assert "SecEdgarFundamentalsProvider(config, data_transport)" in source


class TestManifestReportsWhatEdgarActuallyReturned:
    def test_manifest_has_the_expected_keys(self) -> None:
        keys = _manifest_keys(_tree())
        assert {
            "data_status", "provider", "symbols", "min_filing_date",
            "max_filings_per_symbol", "unresolved_symbols",
            "total_transactions_persisted", "per_symbol_results", "content_checksum",
        } <= keys

    def test_manifest_declares_data_status_real(self) -> None:
        tree = _tree()
        manifest = _manifest_dict_node(tree)
        pairs = {k.value: v for k, v in zip(manifest.keys, manifest.values) if isinstance(k, ast.Constant)}
        assert isinstance(pairs["data_status"], ast.Constant)
        assert pairs["data_status"].value == "REAL"

    def test_manifest_declares_provider_sec_edgar_form4(self) -> None:
        tree = _tree()
        manifest = _manifest_dict_node(tree)
        pairs = {k.value: v for k, v in zip(manifest.keys, manifest.values) if isinstance(k, ast.Constant)}
        assert isinstance(pairs["provider"], ast.Constant)
        assert pairs["provider"].value == "sec_edgar_form4"


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

    def test_known_cik_overrides_dict_has_avb(self) -> None:
        """Real incident, 2026-09-19 sharded full-universe run (shard
        8): AVB genuinely dropped out of SEC EDGAR's live
        company_tickers.json after AvalonBay's 2026-08-17 merger into
        Vivmark Residential (new ticker VMRK) -- resolve_cik legitimately
        returned None, not a bug. The real CIK (0000915912) is the same
        one universe.py's own sector/exchange backfill already verified
        after hitting the identical ticker-map miss."""
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
                assert pairs.get("AVB") == "0000915912"
        assert found, "expected a _KNOWN_CIK_OVERRIDES = {...} dict literal"


class TestPerFilingProgressIsLogged:
    """Real incident (2026-09-18): a real JPM run's filing-list
    pagination finished (confirmed via its own progress_callback
    output), then this per-filing loop went silent for a long time --
    1863 individual filings each needing 2 real requests can take as
    long as the filing-list pagination itself, with zero visibility.
    Mirrors `_fetch_paginated_filing_list`'s own progress_callback fix,
    applied here as a periodic print (every `_FILING_PROGRESS_INTERVAL`
    filings, always on the first and last) rather than a callback,
    since this loop is inline in `main()` rather than a separably
    testable helper."""

    def test_progress_is_printed_at_a_regular_interval_inside_the_per_filing_loop(self) -> None:
        source = _source()
        loop_start = source.index("for j, filing in enumerate(filings, start=1):")
        loop_region = source[loop_start:loop_start + 1200]
        assert "_FILING_PROGRESS_INTERVAL" in loop_region
        assert "fetching filing {j}/{len(filings)}" in loop_region
        assert "flush=True" in loop_region

    def test_progress_print_happens_before_the_real_network_calls_for_that_filing(self) -> None:
        source = _source()
        loop_start = source.index("for j, filing in enumerate(filings, start=1):")
        progress_print_index = source.index("fetching filing {j}/{len(filings)}", loop_start)
        first_network_call_index = source.index("fetch_form4_index(", loop_start)
        assert progress_print_index < first_network_call_index


class TestPerFilingLoopSurvivesAValueErrorNotJustProviderErrors:
    """Same class of regression guard ingest_fundamentals_data.py's own
    per-symbol loop already carries, applied here at the per-FILING
    level (this script has 2 layers of granularity: a filing-list
    fetch failure degrades the whole symbol, but a single bad filing
    degrades only that filing, not the rest of the symbol's filings)."""

    def test_the_per_filing_except_clause_also_catches_value_error(self) -> None:
        source = _source()
        per_filing_loop_start = source.index("for j, filing in enumerate(filings, start=1):")
        except_index = source.index("except (", per_filing_loop_start)
        line_end = source.index("\n", except_index)
        except_line = source[except_index:line_end]
        assert "ValueError" in except_line, (
            f"the per-filing except clause ({except_line!r}) catches the provider errors "
            "but not ValueError -- a single malformed InsiderTransaction would crash the "
            "entire symbol's remaining filings instead of failing just that one filing"
        )

    def test_a_missing_primary_document_is_recorded_not_crashed(self) -> None:
        source = _source()
        assert "select_form4_primary_document" in source
        assert "filing_errors.append" in source
        assert "no ownership-document XML found" in source


class TestSingleTickerMapFetchSharedAcrossSymbols:
    def test_ticker_map_fetched_once_before_the_symbol_loop(self) -> None:
        source = _source()
        fetch_index = source.index("provider.fetch_ticker_map(www_transport)")
        loop_index = source.index("for i, symbol in enumerate(symbols, start=1):")
        assert fetch_index < loop_index
