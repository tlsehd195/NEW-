"""Real, executable tests for `failed_symbols_from`
(`scripts/ingest_fundamentals_data.py` / `scripts/ingest_insider_
transactions.py`, Session 37 ADR-0115 external review N-13) -- unlike
these scripts' own AST/source-text-only wiring tests (necessary for the
rest of each script, which makes real network calls inside `main()`),
this one function takes a plain list and makes no network call of its
own, so it can be imported and exercised directly, the same "import via
spec_from_file_location, call one pure helper function, never call
main()" pattern `test_ingest_insider_transactions_pagination.py`
already established.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestFundamentalsFailedSymbolsFrom:
    def test_no_errors_returns_empty(self) -> None:
        module = _load_script("ingest_fundamentals_data")
        results = [
            {"security_id": "AAA", "cik": "1", "cik_source": "ticker_map", "records_persisted": 3, "error": None},
            {"security_id": "BBB", "cik": "2", "cik_source": "ticker_map", "records_persisted": 5, "error": None},
        ]
        assert module.failed_symbols_from(results) == []

    def test_a_per_symbol_fetch_error_is_reported_even_when_others_succeed(self) -> None:
        """Session 37 (ADR-0115, external review N-13): before this fix,
        a symbol whose fetch/parse raised (recorded with a non-None
        `error` here) never made it into `unresolved_symbols`, so
        `main()`'s exit code stayed 0 as long as at least one OTHER
        symbol succeeded."""
        module = _load_script("ingest_fundamentals_data")
        results = [
            {"security_id": "AAA", "cik": "1", "cik_source": "ticker_map", "records_persisted": 3, "error": None},
            {"security_id": "BBB", "cik": "2", "cik_source": "ticker_map", "records_persisted": 0, "error": "TransientProviderError: timeout"},
        ]
        assert module.failed_symbols_from(results) == ["BBB"]

    def test_an_unresolved_cik_symbol_is_also_reported(self) -> None:
        module = _load_script("ingest_fundamentals_data")
        results = [
            {"security_id": "AAA", "cik": None, "cik_source": None, "records_persisted": 0, "error": "ticker not found in SEC EDGAR company_tickers.json"},
        ]
        assert module.failed_symbols_from(results) == ["AAA"]


class TestInsiderTransactionsFailedSymbolsFrom:
    def test_no_errors_returns_empty(self) -> None:
        module = _load_script("ingest_insider_transactions")
        results = [
            {"security_id": "AAA", "cik": "1", "cik_source": "ticker_map", "filings_seen": 2, "transactions_persisted": 3, "error": None},
        ]
        assert module.failed_symbols_from(results) == []

    def test_a_per_symbol_filing_list_fetch_error_is_reported_even_when_others_succeed(self) -> None:
        module = _load_script("ingest_insider_transactions")
        results = [
            {"security_id": "AAA", "cik": "1", "cik_source": "ticker_map", "filings_seen": 2, "transactions_persisted": 3, "error": None},
            {"security_id": "BBB", "cik": "2", "cik_source": "ticker_map", "filings_seen": 0, "transactions_persisted": 0, "error": "PermanentProviderError: 403"},
        ]
        assert module.failed_symbols_from(results) == ["BBB"]
