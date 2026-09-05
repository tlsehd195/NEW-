# ADR-0089: Form 4 pagination -- ADR-0088's `dateb` fix does not work, real fix uses `start`

**Status:** Accepted
**Session:** 36 (continued)

## Context

ADR-0088 added pagination to `ingest_insider_transactions.py` using
EDGAR's `dateb` query parameter (Tier 2 -- documented, never exercised
against a live paginated response before being trusted). The account
owner re-ran ingestion with it: total transactions rose from 4877 to
13798, which looked like progress, but the raw-IC screen
(`--score insider_buying --start 2010-01-01`) still returned
`observations=0`. A direct DB check showed why: the newly-ingested
data's actual date range was 2021-02-24..2026-09-04 -- pagination had
extended coverage somewhat, but nowhere near the `--min-filing-date`
target (2009-06-01), and most symbols' per-symbol logs showed exactly
one page (`count=100`) fetched before the loop stopped.

Diagnosed directly, not guessed at (per this project's own established
discipline for every real bug this session has hit): a live diagnostic
script fetched AAPL's Form 4 filing list twice -- once with `dateb=""`
(page 1) and once with `dateb` set to page 1's own oldest filing date
(page 2, exactly what `_fetch_paginated_filing_list` was doing). The
two responses were **byte-for-byte identical** -- same 100 accession
numbers, same order, 0 new entries in page 2. `dateb` does not filter
this endpoint's `output=atom` response at all. This explains ADR-0088's
real-run behavior exactly: `_fetch_paginated_filing_list`'s
"a page returns nothing new -> stop" condition fired after page 2 for
almost every symbol, having accumulated only page 1's own 100 filings
(the few symbols that reached ~199-200 filings did so via the
`max_filings`/partial-page paths interacting with this same underlying
non-filtering, not because `dateb` genuinely paged them further back).

## Decision

Replaced `dateb`-based paging with `start` -- EDGAR's classic 0-based
offset parameter for this same endpoint -- verified for real before
being trusted, the same way ADR-0086's original single-page shape was:
a second live diagnostic fetched `start=0` and `start=100` against
AAPL's real filing history. Result: `start=100` returned exactly the
next 100 filings chronologically, 0 overlap with `start=0`'s own 100
(page 1's oldest date 2024-04-03; page 2's newest date 2024-04-03,
oldest 2022-02-03 -- a clean, contiguous chronological continuation).

`SecEdgarFundamentalsProvider.fetch_form4_filing_list`'s `before_date`
parameter is replaced by `start: int = 0`; the method's own evidence
tier for this parameter moves from Tier 2 (ADR-0088) to Tier 1 (this
ADR) since it is now verified against a real paginated response.
`dateb` is still sent in the query string, always empty -- removing it
entirely would be a second, unverified change bundled into this same
fix, and it costs nothing to leave present but inert.

`_fetch_paginated_filing_list` in `ingest_insider_transactions.py` now
walks `start` forward by `page_size` each iteration instead of deriving
a `before_date` string from the oldest filing seen. The three stopping
conditions (`min_filing_date` reached, a partial page, no new filings)
are unchanged in shape -- only the pagination key changed -- and the
dedup-by-accession-number safety net is kept as a defensive measure
even though it is no longer expected to trigger under normal operation
(genuinely disjoint `start`-offset pages should never repeat an
accession number).

## What this does NOT do

Does not verify `start`-based pagination all the way back to 2009 for
every real symbol -- only the two-page AAPL diagnostic was run live
this session. The account owner's next real re-ingestion is the first
full exercise of the corrected loop across all 87 symbols; if some
symbol's real history behaves differently (e.g., a filer with more
filings than `--max-filings-per-symbol` allows), that surfaces as a
`max_filings`-capped result, not a fabricated success. Does not change
`insider_buying_score`, `InsiderTransaction`, or any other Form 4
provider method -- scoped entirely to filing-list retrieval, same as
ADR-0088.

## Tests

`tests/data_infra/test_sec_edgar_form4.py` -- the `before_date` tests
replaced with `start`-offset equivalents (query-string construction,
default value). `tests/data_infra/test_ingest_insider_transactions_pagination.py`
-- the stub provider and all 9 pagination tests re-keyed from
`before_date` strings to `start` integers (accumulation, min-date stop,
partial-page stop, no-new-filings stop, max-filings cap, empty-first-page
case) -- same real behavioral coverage as ADR-0088, now exercising the
corrected mechanism. `tests/data_infra/test_ingest_insider_transactions_wiring.py`
updated for the renamed call site. Full repository suite (2482 tests)
passes.
