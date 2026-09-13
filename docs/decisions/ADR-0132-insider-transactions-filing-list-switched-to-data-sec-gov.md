# ADR-0132: Insider Transaction Filing-List Fetching Switched from the Old CGI-bin Endpoint to `data.sec.gov`

**Status:** Accepted
**Date:** 2026-09-13
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0086-sec-form4-insider-transactions.md`,
`docs/decisions/ADR-0088-form4-pagination.md`, `docs/decisions/ADR-0089-form4-pagination-start-offset-fix.md`,
`docs/decisions/ADR-0131-sec-13f-real-format-and-free-cusip-resolution.md`

---

## Context

The account owner ran `scripts/ingest_insider_transactions.py` for real,
overnight, against all 87 `RESEARCH_UNIVERSE` symbols (plus `AVB` via
`--cik-overrides`). Real result: **84/87 symbols failed**, total
runtime several hours. Every single failure's own error message was a
`timed out after 10.0s` (one `HTTP 503`) on
`fetch_form4_filing_list`'s `/cgi-bin/browse-edgar?action=getcompany&
...&output=atom` call -- **never** on the per-filing
`fetch_form4_index`/`fetch_form4_document` calls (`/Archives/edgar/
data/.../index.json` and the filing XML itself), which had zero
failures across the same real run. A same-day, same-account re-run of
just 3 of the failed symbols (`AMZN`, `GOOGL`, `META`) succeeded
completely (40,571 transactions persisted, 0 failures), ruling out a
permanent block and pointing instead at that specific old endpoint's
real unreliability under sustained use, not a fundamental problem with
this project's approach.

The SAME account owner's `scripts/ingest_fundamentals_data.py` run,
calling `data.sec.gov`'s modern REST API for the exact same 87
symbols, had **zero failures**. This is the real, decisive evidence:
the failure is specific to the old `/cgi-bin/browse-edgar` atom-feed
endpoint (ADR-0088/ADR-0089's own design), not to SEC EDGAR generally
or to this project's request pattern/rate.

## Decision -- Switch the filing-LIST step (only) to `data.sec.gov/submissions/CIK##########.json`

`_fetch_paginated_filing_list` (`scripts/ingest_insider_transactions.py`)
now fetches a filer's Form 4 filing list from `data.sec.gov/submissions/
CIK##########.json` (`SecEdgarFundamentalsProvider.fetch_submissions`,
already existed for `get_sector()`'s own purpose) via a NEW,
DEDICATED provider instance (`data_provider`) constructed with a
`data.sec.gov` transport, alongside the EXISTING `provider`/
`www_transport` pair the per-filing detail fetches keep using
unchanged. Two new pure functions in `sec_edgar.py`:

- `form4_filings_from_submissions(raw)` -- filters the response's
  `filings.recent` parallel arrays (`form`/`accessionNumber`/
  `filingDate`) to `form == "4"`, returning `{"accession_number",
  "filing_date"}` per filing -- the identical shape
  `fetch_form4_filing_list` already returned, so no other caller code
  needed to change. Also auto-detects the OLDER-history file shape
  (same arrays at the JSON top level rather than nested under
  `filings.recent`) so one function serves both cases.
- `submissions_older_filing_files(raw)` -- extracts the file names SEC
  names for a prolific filer's history beyond what `filings.recent`
  holds (`filings.files`), fetched via a new `fetch_submissions_file`
  provider method only when `filings.recent` alone does not reach back
  to `--min-filing-date`.

`--page-size`/`--start` (ADR-0088/ADR-0089's own CGI-bin-specific
pagination) no longer apply and were removed -- `data.sec.gov`'s own
pagination (the `filings.files` older-history mechanism) replaces
`start`-offset paging entirely. The per-filing detail fetches
(`fetch_form4_index`, `select_form4_primary_document`,
`fetch_form4_document`) are **deliberately unchanged** -- they were
never implicated in the real failures, and touching working code
alongside a real fix would be an unverified, unnecessary risk.

## Honesty about evidence tier

`form4_filings_from_submissions`/`submissions_older_filing_files` are
Tier 2 (SEC's long-stable, publicly documented `submissions` shape,
including the older-history `filings.files` mechanism) -- **neither
has been exercised against a real response in any environment yet**,
unlike `fetch_form4_filing_list` (Tier 1, verified against a real atom
feed, ADR-0086/ADR-0089). This sandboxed session cannot reach
`data.sec.gov` to verify directly. The account owner must run this
against at least one real symbol (ideally one whose Form 4 history is
known to be large enough to exercise the `filings.files` fallback,
e.g. a symbol already observed needing the old pagination to reach
2009) before trusting it for a full re-run, the same discipline this
project has applied to every other real external format.

## Consequences

### Positive

- Directly targets the real, observed failure (the old list endpoint
  specifically), rather than a broad, unverified guess (e.g. "just
  slow down the whole script" or "just retry more").
- Reuses `data.sec.gov` infrastructure already proven reliable this
  session (87/87 real fundamentals symbols, zero failures) rather than
  inventing a new pattern.
- `--page-size`/`--start`, now-dead parameters, were removed rather
  than left as silently-ignored CLI flags (this project's own
  established discipline against dead parameters, e.g. the earlier
  `broker/pipeline.py` restart-unsafe allocator fix).

### Negative / Trade-offs

- Real, unverified assumption: `filings.recent` typically holds
  roughly the most recent ~1000 filings of ANY type (not just Form 4)
  per SEC's documented behavior -- for a filer with very high Form-4
  volume relative to other filing types, `filings.recent` might
  contain fewer Form 4s than the old endpoint's `count=100`-per-page
  pagination would have surfaced before needing to fall back to
  `filings.files`. Not expected to change final coverage (the fallback
  exists exactly for this), but untested against a real deep-history
  filer as of this ADR.
- The old `/cgi-bin/browse-edgar` endpoint's real unreliability under
  sustained use is not itself explained (why the first few symbols
  succeeded and the rest failed) -- disclosed as an open question, not
  papered over with a confident-sounding but unverified theory.

## Tests

46 new/rewritten tests: 8 in `test_sec_edgar_form4.py`
(`form4_filings_from_submissions`) + 4 (`submissions_older_filing_
files`), all pure/no-network. `test_ingest_insider_transactions_
pagination.py` fully rewritten (8 tests) against the new stub provider
shape (`fetch_submissions`/`fetch_submissions_file` instead of paged
`fetch_form4_filing_list`) -- same behavioral coverage (accumulation,
dedup, three stopping conditions, empty case) applied to the new
control flow. `test_ingest_insider_transactions_wiring.py`'s two-host
assertions updated to match (renamed `TestSingleHostTransportUsedThroughout`
to `TestTwoHostTransportsUsedCorrectly`, reflecting the module's own
docstring update). Full suite re-run clean after these changes.

## Status of Implementation at Time of This ADR

Code change complete and locally tested (no network calls in the test
suite, matching every other real-provider script in this project).
**Not yet verified against a real response** -- the account owner must
run this against at least one real symbol on their own environment
before resuming the full 79-symbol re-collection this ADR's own
Context section describes as still in progress.
