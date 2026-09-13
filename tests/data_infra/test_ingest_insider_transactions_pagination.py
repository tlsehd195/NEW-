"""Real, executable tests for `_fetch_paginated_filing_list`
(`scripts/ingest_insider_transactions.py`) -- unlike
`test_ingest_insider_transactions_wiring.py`'s AST/source-text-only
discipline (necessary for the rest of that script, which makes real
network calls inside `main()`), this one function takes its
`data_provider` as a plain argument and makes no network call of its
own, so it can be imported and exercised directly against a stub
provider -- the same "import the module via spec_from_file_location,
call one pure helper function, never call main()" pattern
`test_run_long_horizon_validation_factor_wiring.py` already
established for that script's own `_price_factor_factory` etc.

**Session 37 continued -- rewritten for the real overnight-failure fix**:
the account owner's own real overnight run of this script failed on
84/87 symbols, every single failure a timeout or 503 on the OLD
`/cgi-bin/browse-edgar?...output=atom` filing-list endpoint (ADR-0088/
ADR-0089's own design) -- never on the per-filing detail fetches.
`_fetch_paginated_filing_list` now fetches the filing list from
`data.sec.gov/submissions/CIK....json` instead (the same host/endpoint
class `ingest_fundamentals_data.py` already used with zero failures
across the same 87 symbols), falling back to SEC's own documented
older-history files (`submissions_older_filing_files`) only when the
main response's `filings.recent` does not reach back far enough. This
file's stub provider and fixtures were rewritten to match; the ADR-
0088/ADR-0089 `start`-offset pagination behavior these tests used to
cover no longer applies (that CGI-bin endpoint is no longer called by
this function at all)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from helpers import utc

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ingest_insider_transactions.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("ingest_insider_transactions", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _submissions(entries: list[tuple], files: list[str] | None = None) -> dict:
    """`entries` is a list of `(accession_number, filing_date_str, form)`
    tuples, matching SEC's real `filings.recent` parallel-array shape."""
    return {
        "filings": {
            "recent": {
                "accessionNumber": [e[0] for e in entries],
                "filingDate": [e[1] for e in entries],
                "form": [e[2] for e in entries],
            },
            "files": [{"name": f} for f in (files or [])],
        }
    }


def _older_file(entries: list[tuple]) -> dict:
    """Older-history files put the same arrays at the JSON top level
    (SEC's real documented shape), not nested under `filings.recent`."""
    return {
        "accessionNumber": [e[0] for e in entries],
        "filingDate": [e[1] for e in entries],
        "form": [e[2] for e in entries],
    }


class _StubProvider:
    """Records every call for assertions. `fetch_submissions` always
    returns the one main response; `fetch_submissions_file` looks up
    the requested older-history file by name."""

    def __init__(self, main: dict, files: dict[str, dict] | None = None) -> None:
        self._main = main
        self._files = files or {}
        self.calls: list[tuple] = []

    def fetch_submissions(self, cik):
        self.calls.append(("submissions", cik))
        return self._main

    def fetch_submissions_file(self, file_name):
        self.calls.append(("file", file_name))
        return self._files[file_name]


class TestSingleResponseCoversTheWholeWindow:
    def test_all_form_4_filings_from_recent_are_returned(self) -> None:
        module = _load_script()
        main = _submissions([
            ("0001-26-000001", "2023-06-01", "4"),
            ("0001-26-000002", "2023-05-01", "4"),
            ("0001-26-000003", "2023-04-01", "10-K"),  # not a Form 4 -- must be excluded
        ])
        provider = _StubProvider(main)

        filings = module._fetch_paginated_filing_list(
            provider, "0000320193", min_filing_date=utc(2010, 1, 1), max_filings=100,
        )

        assert {f["accession_number"] for f in filings} == {"0001-26-000001", "0001-26-000002"}

    def test_no_older_files_are_fetched_when_recent_already_reaches_min_filing_date(self) -> None:
        module = _load_script()
        main = _submissions([("0001-26-000001", "2009-01-01", "4")], files=["CIK0000320193-submissions-001.json"])
        provider = _StubProvider(main)

        module._fetch_paginated_filing_list(
            provider, "0000320193", min_filing_date=utc(2010, 1, 1), max_filings=100,
        )

        assert provider.calls == [("submissions", "0000320193")]  # never fetched the older file


class TestFallsBackToOlderHistoryFiles:
    def test_older_file_is_fetched_when_recent_does_not_reach_min_filing_date(self) -> None:
        module = _load_script()
        main = _submissions(
            [("0001-26-000001", "2023-06-01", "4")],
            files=["CIK0000320193-submissions-001.json"],
        )
        older = _older_file([("0001-25-000001", "2009-01-01", "4")])
        provider = _StubProvider(main, files={"CIK0000320193-submissions-001.json": older})

        filings = module._fetch_paginated_filing_list(
            provider, "0000320193", min_filing_date=utc(2010, 1, 1), max_filings=100,
        )

        assert {f["accession_number"] for f in filings} == {"0001-26-000001", "0001-25-000001"}
        assert provider.calls == [
            ("submissions", "0000320193"),
            ("file", "CIK0000320193-submissions-001.json"),
        ]

    def test_stops_fetching_older_files_once_min_filing_date_reached(self) -> None:
        module = _load_script()
        main = _submissions(
            [("0001-26-000001", "2023-06-01", "4")],
            files=["file-001.json", "file-002.json"],
        )
        file1 = _older_file([("0001-25-000001", "2009-01-01", "4")])  # already reaches min_filing_date
        file2 = _older_file([("0001-24-000001", "2005-01-01", "4")])
        provider = _StubProvider(main, files={"file-001.json": file1, "file-002.json": file2})

        module._fetch_paginated_filing_list(
            provider, "0000320193", min_filing_date=utc(2010, 1, 1), max_filings=100,
        )

        assert provider.calls == [("submissions", "0000320193"), ("file", "file-001.json")]

    def test_stops_once_older_files_are_exhausted(self) -> None:
        module = _load_script()
        main = _submissions(
            [("0001-26-000001", "2023-06-01", "4")],
            files=["file-001.json"],
        )
        file1 = _older_file([("0001-25-000001", "2015-01-01", "4")])  # still doesn't reach min_filing_date
        provider = _StubProvider(main, files={"file-001.json": file1})

        filings = module._fetch_paginated_filing_list(
            provider, "0000320193", min_filing_date=utc(2010, 1, 1), max_filings=100,
        )

        assert len(provider.calls) == 2  # never asked for a nonexistent third file
        assert {f["accession_number"] for f in filings} == {"0001-26-000001", "0001-25-000001"}


class TestDeduplicatesByAccessionNumber:
    def test_an_accession_repeated_in_an_older_file_is_not_duplicated(self) -> None:
        module = _load_script()
        main = _submissions(
            [("0001-26-000001", "2023-06-01", "4")],
            files=["file-001.json"],
        )
        file1 = _older_file([("0001-26-000001", "2023-06-01", "4"), ("0001-25-000001", "2009-01-01", "4")])
        provider = _StubProvider(main, files={"file-001.json": file1})

        filings = module._fetch_paginated_filing_list(
            provider, "0000320193", min_filing_date=utc(2010, 1, 1), max_filings=100,
        )

        assert [f["accession_number"] for f in filings].count("0001-26-000001") == 1


class TestMaxFilingsSafetyCap:
    def test_stops_once_the_cap_is_reached_even_if_min_filing_date_not_yet_reached(self) -> None:
        module = _load_script()
        main = _submissions(
            [("0001-26-000001", "2023-06-01", "4"), ("0001-26-000002", "2023-05-01", "4")],
            files=["file-001.json"],
        )
        file1 = _older_file([("0001-25-000001", "2015-01-01", "4"), ("0001-25-000002", "2014-01-01", "4")])
        provider = _StubProvider(main, files={"file-001.json": file1})

        filings = module._fetch_paginated_filing_list(
            provider, "0000320193", min_filing_date=utc(2010, 1, 1), max_filings=3,
        )

        assert len(filings) == 3  # truncated at the cap, not 4


class TestNoFilingsAtAll:
    def test_no_form_4_filings_and_no_older_files_returns_an_empty_list_not_an_error(self) -> None:
        module = _load_script()
        main = _submissions([("0001-26-000001", "2023-06-01", "10-K")])  # no Form 4 at all
        provider = _StubProvider(main)

        filings = module._fetch_paginated_filing_list(
            provider, "0000320193", min_filing_date=utc(2010, 1, 1), max_filings=100,
        )

        assert filings == []
        assert provider.calls == [("submissions", "0000320193")]  # no older files listed -- never looped forever
