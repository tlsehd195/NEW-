"""Real, executable tests for `_fetch_paginated_filing_list`
(`scripts/ingest_insider_transactions.py`, ADR-0089) -- unlike
`test_ingest_insider_transactions_wiring.py`'s AST/source-text-only
discipline (necessary for the rest of that script, which makes real
network calls inside `main()`), this one function takes its
`provider`/`transport` as plain arguments and makes no network call of
its own, so it can be imported and exercised directly against a stub
provider -- the same "import the module via spec_from_file_location,
call one pure helper function, never call main()" pattern
`test_run_long_horizon_validation_factor_wiring.py` already
established for that script's own `_price_factor_factory` etc.

**Why this needed a real behavioral test, not just AST checks**: this
function's real bug surface (accumulation across pages, dedup by
accession number, three different stopping conditions) cannot be
verified by matching source text the way the rest of that script's
simpler wiring can -- exactly the same reasoning
`test_run_long_horizon_validation_factor_wiring.py`'s own docstring
gives for testing the late-binding-closure behavior of its factory
functions directly rather than trusting source-text matching alone.

**ADR-0089 note**: this file originally keyed stub pages by a
`before_date` string (ADR-0088's design). A real re-ingestion run
proved EDGAR's `dateb` parameter does not filter this endpoint's atom
response at all -- every "next page" request came back byte-for-byte
identical to the first. `_fetch_paginated_filing_list` now walks a
`start` integer offset instead (verified for real against AAPL's live
filing history), so this file's stub keys by `start` instead."""

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


def _filing(accession: str, filing_date) -> dict:
    return {"accession_number": accession, "filing_date": filing_date, "filing_href": f"https://example.com/{accession}/"}


class _StubProvider:
    """Returns one pre-built page per call, keyed by the `start` offset
    the caller passes -- `0` for the very first call, then whatever
    the real function derives (`start += page_size` each time). Records
    every call for assertions."""

    def __init__(self, pages_by_start: dict) -> None:
        self._pages = pages_by_start
        self.calls: list[tuple] = []

    def fetch_form4_filing_list(self, cik, transport, *, count, start=0):
        self.calls.append((cik, transport, count, start))
        return self._pages.get(start, [])


class TestPaginationAccumulatesAcrossPages:
    def test_two_pages_are_both_collected(self) -> None:
        module = _load_script()
        page1 = [_filing("A1", utc(2023, 6, 1)), _filing("A2", utc(2023, 5, 1))]
        page2 = [_filing("A3", utc(2023, 4, 1)), _filing("A4", utc(2023, 3, 1))]
        provider = _StubProvider({0: page1, 2: page2})

        filings = module._fetch_paginated_filing_list(
            provider, "CIK", "transport-token", page_size=2,
            min_filing_date=utc(2023, 1, 1), max_filings=100,
        )

        assert {f["accession_number"] for f in filings} == {"A1", "A2", "A3", "A4"}

    def test_second_page_request_advances_start_by_page_size(self) -> None:
        module = _load_script()
        page1 = [_filing("A1", utc(2023, 6, 1)), _filing("A2", utc(2023, 5, 1))]
        provider = _StubProvider({0: page1, 2: []})

        module._fetch_paginated_filing_list(
            provider, "CIK", "transport-token", page_size=2,
            min_filing_date=utc(2020, 1, 1), max_filings=100,
        )

        starts_requested = [call[3] for call in provider.calls]
        assert starts_requested == [0, 2]


class TestStopsOnceMinFilingDateReached:
    def test_stops_after_the_page_containing_min_filing_date(self) -> None:
        module = _load_script()
        page1 = [_filing("A1", utc(2023, 6, 1)), _filing("A2", utc(2023, 5, 1))]
        page2 = [_filing("A3", utc(2010, 1, 1)), _filing("A4", utc(2009, 1, 1))]
        provider = _StubProvider({0: page1, 2: page2})

        filings = module._fetch_paginated_filing_list(
            provider, "CIK", "transport-token", page_size=2,
            min_filing_date=utc(2010, 1, 1), max_filings=100,
        )

        assert len(provider.calls) == 2  # never requested a third page
        assert {f["accession_number"] for f in filings} == {"A1", "A2", "A3", "A4"}

    def test_oldest_filing_exactly_equal_to_min_filing_date_still_stops(self) -> None:
        module = _load_script()
        page1 = [_filing("A1", utc(2010, 1, 1))]
        provider = _StubProvider({0: page1})

        module._fetch_paginated_filing_list(
            provider, "CIK", "transport-token", page_size=10,
            min_filing_date=utc(2010, 1, 1), max_filings=100,
        )

        assert len(provider.calls) == 1


class TestStopsOnPartialPage:
    def test_a_page_smaller_than_page_size_means_history_is_exhausted(self) -> None:
        module = _load_script()
        page1 = [_filing("A1", utc(2023, 6, 1)), _filing("A2", utc(2023, 5, 1))]  # only 2, page_size=5
        provider = _StubProvider({0: page1})

        filings = module._fetch_paginated_filing_list(
            provider, "CIK", "transport-token", page_size=5,
            min_filing_date=utc(2010, 1, 1), max_filings=100,
        )

        assert len(provider.calls) == 1  # never asked for a second page
        assert len(filings) == 2


class TestStopsWhenNoNewFilingsReturned:
    def test_a_page_with_only_already_seen_accessions_stops_the_loop(self) -> None:
        # Defensive guard, kept even after ADR-0089's real verification
        # that `start` pages are genuinely disjoint: if some other
        # boundary quirk ever causes a page to repeat prior filings,
        # this dedup-then-stop-on-no-progress check prevents an
        # infinite loop rather than trusting the offset alone.
        module = _load_script()
        page1 = [_filing("A1", utc(2023, 6, 1)), _filing("A2", utc(2023, 5, 1))]
        provider = _StubProvider({0: page1, 2: page1})  # same filings again

        filings = module._fetch_paginated_filing_list(
            provider, "CIK", "transport-token", page_size=2,
            min_filing_date=utc(2010, 1, 1), max_filings=100,
        )

        assert len(provider.calls) == 2
        assert {f["accession_number"] for f in filings} == {"A1", "A2"}  # not duplicated


class TestMaxFilingsSafetyCap:
    def test_stops_once_the_cap_is_reached_even_if_min_filing_date_not_yet_reached(self) -> None:
        module = _load_script()
        page1 = [_filing("A1", utc(2023, 6, 1)), _filing("A2", utc(2023, 5, 1))]
        page2 = [_filing("A3", utc(2023, 4, 1)), _filing("A4", utc(2023, 3, 1))]
        provider = _StubProvider({0: page1, 2: page2, 4: [_filing("A5", utc(2023, 2, 1))]})

        filings = module._fetch_paginated_filing_list(
            provider, "CIK", "transport-token", page_size=2,
            min_filing_date=utc(2010, 1, 1), max_filings=4,
        )

        assert len(filings) == 4  # stopped at the cap, never fetched the 3rd page's worth beyond it


class TestNoFilingsAtAll:
    def test_empty_first_page_returns_an_empty_list_not_an_error(self) -> None:
        module = _load_script()
        provider = _StubProvider({0: []})

        filings = module._fetch_paginated_filing_list(
            provider, "CIK", "transport-token", page_size=40,
            min_filing_date=utc(2010, 1, 1), max_filings=100,
        )

        assert filings == []
        assert len(provider.calls) == 1
