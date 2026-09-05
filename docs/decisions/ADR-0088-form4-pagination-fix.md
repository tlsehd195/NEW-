# ADR-0088: SEC Form 4 ingestion pagination -- real gap found from actual usage, fixed

**Status:** Accepted
**Session:** 36 (continued)

## Context

The account owner ran `scripts/ingest_insider_transactions.py` for
real (ADR-0086) against all 87 `RESEARCH_UNIVERSE_STAGE4` symbols,
default `--filings-per-symbol 40`. Ingestion itself succeeded (4877
transactions, 86/87 symbols resolved -- `AVB` unresolved, the same
known CIK gap `ingest_fundamentals_data.py` already has). Running the
raw-IC screen next (`compute_fundamentals_ic_from_catalog.py --score
insider_buying --start 2010-01-01`, the standard start every other
factor in this project has been screened against) returned
`observations=0`.

Diagnosed directly against the real ingested catalog rather than
guessed at:

```
MIN(transaction_date), MAX(transaction_date), COUNT(*)
  -> (2023-09-15, 2026-09-04, 4877)
```

The ingested data's ENTIRE date range sits inside
`strategy_research.locked_windows.TEST_1` (2023-04-28..2026-08-27) --
not merely "too shallow," but almost completely overlapping the
project's own held-out TEST window. `compute_fundamentals_ic_from_
catalog.py`'s own TEST-1 refusal (by design, no override) correctly
restricted the raw-IC request to `[2010-01-01, TEST_1.start)`, and
that range genuinely had zero rows of insider data to score against.

Root cause: `fetch_form4_filing_list` (and therefore
`ingest_insider_transactions.py`) made exactly ONE EDGAR request per
symbol, capped at `count` filings -- the classic "most recent N"
`browse-edgar` Atom feed response, with no mechanism to page further
back. For 87 real, actively-traded large-cap symbols, 40 filings turns
out to only reach back a few years from "now" (`--as-of 2026-09-05`),
nowhere near 2010.

## Decision

Added real pagination (Tier 2 -- EDGAR's own long-documented `dateb`
query parameter, never exercised against a live paginated response
this session, unlike the Tier 1 single-page shape ADR-0086 already
verified):

`SecEdgarFundamentalsProvider.fetch_form4_filing_list` gained a
`before_date: Optional[str]` parameter (`"YYYY-MM-DD"`, EDGAR's `dateb`
format) -- `None` reproduces the exact pre-ADR-0088 single-page
behavior unchanged.

`scripts/ingest_insider_transactions.py` gained
`_fetch_paginated_filing_list`: fetches pages oldest-boundary-first,
re-calling with `before_date` set to the OLDEST `filing_date` seen so
far, deduplicating by `accession_number` across pages (defensive
against EDGAR's own boundary-inclusion semantics being either
inclusive or exclusive -- unverified this session, so the loop treats
"a page returns nothing new" as the correct stop condition regardless
of which it turns out to be). Stops on whichever of three conditions
comes first: the oldest filing reaches `--min-filing-date` (new flag,
default `2009-06-01` -- 6 months before this project's standard
2010-01-01 raw-IC start, giving `insider_buying_score`'s own trailing-
6-month window room to see data at the very start of that range), a
page returns nothing new, or `--max-filings-per-symbol` (new flag,
default 3000, a safety cap against an extremely active filer's history
running unbounded) is reached.

`--filings-per-symbol` is replaced by `--min-filing-date`/`--page-size`
/`--max-filings-per-symbol` -- a clean interface change, not a
backward-compatible shim: this script has been run exactly once, by
one person, this same session, so there is no external caller whose
existing invocation needs to keep working unchanged.

## What this does NOT do

Does not verify the `dateb`/pagination behavior against a real,
multi-page EDGAR response -- this session's own network is still
blocked. The account owner's next real re-run of `ingest_insider_
transactions.py` is the first real exercise of this code path; if
EDGAR's actual `dateb` semantics differ from what `_fetch_paginated_
filing_list`'s dedup-and-stop-on-no-progress design defends against,
that will surface as either fewer transactions than expected or a
`filing_errors` entry, not silent corruption (every existing per-
filing error-handling and idempotent-natural-key persistence behavior
is unchanged). Does not change anything about `insider_buying_score`
itself, `InsiderTransaction`, `DuckDBInsiderRepository`, or the 4 other
Form 4 provider methods -- this ADR is scoped entirely to filing-list
retrieval depth.

## Tests

`tests/data_infra/test_sec_edgar_form4.py` -- 2 new tests: `before_date`
reaches the `dateb` query param correctly, and `None` reproduces the
exact prior single-page query. `tests/data_infra/test_ingest_insider_
transactions_pagination.py` (new file, 9 tests) -- real, executable
tests of `_fetch_paginated_filing_list` against a stub provider:
accumulation across pages, the second page's `before_date` derived
correctly from the first page's oldest filing, all three stop
conditions (`min_filing_date` reached, a partial page, no new filings
returned) independently verified, the `max_filings` safety cap, and
the empty-first-page case. `tests/data_infra/test_ingest_insider_
transactions_wiring.py` updated for the renamed CLI flags and call
site. Full repository suite (2482 tests) passes.
