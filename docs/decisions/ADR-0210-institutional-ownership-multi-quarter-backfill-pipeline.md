# ADR-0210: Multi-quarter, all-filer institutional-ownership backfill pipeline

**Status:** Accepted
**Date:** 2026-09-26
**Deciders:** account owner ("코드 짜봐"), Claude Code session

**Related documents:** `docs/decisions/ADR-0131` (single-filer 13F XML
parsing + CUSIP->ticker OpenFIGI resolution, the only real evidence
this pipeline had before today), `docs/decisions/ADR-0104` (the
`institutional_ownership_change_score` factor's own original design),
`docs/decisions/ADR-0209` (the human factor review that found
`institutional_ownership_change` had only ever been exercised against
one filer, Berkshire Hathaway -- ~28 securities, not this project's
87-symbol `RESEARCH_UNIVERSE`), `scripts/verify_sec_13f_bulk_dataset.py`
(the real, pre-registered verification run this design is built on).

## Context

`ADR-0209`'s human review flagged that `institutional_ownership_change`
cannot be a real, market-wide factor candidate until it aggregates
across ALL institutional 13F filers, not one. SEC's own bulk Form 13F
structured data sets (one ZIP per ~3-month FILING window, every
filer's Information Table) are the real, free path to that coverage --
`scripts/verify_sec_13f_bulk_dataset.py` confirmed the real file/column
format and a name-matching + OpenFIGI-confirmation approach that needs
no new, unverified capability. This ADR is the resulting production
pipeline.

## Decision

### 1. `src/data_infra/providers/sec_13f_bulk_dataset.py` (new, pure, no network)

- `generate_filing_windows(first_start_year, through_date) ->
  list[FilingWindow]`: the real, confirmed URL pattern
  (`https://www.sec.gov/files/structureddata/data/form-13f-data-sets/
  {DDmonYYYY}-{DDmonYYYY}_form13f.zip`) and the real 4-windows-per-year
  boundaries (`01mar-31may`, `01jun-31aug`, `01sep-30nov`,
  `01dec-*feb`), verified against two independently-confirmed real
  URLs (this project's own verification run, and a real WebSearch
  result for a different year).
- `parse_submission_rows`/`latest_submission_per_period`: real,
  disclosed amendment handling -- a `13F-HR/A` amendment for a given
  `(CIK, PERIODOFREPORT)` can land in a LATER window file than the
  original (real, confirmed: one window's real data spanned
  `PERIODOFREPORT` values from `31-DEC-2006` to the window's own
  contemporaneous quarter). Keeps only the latest-`FILING_DATE`
  submission per `(CIK, PERIODOFREPORT)`, never double-counts an
  original alongside its own later amendment.
- `aggregate_holdings`: sums `SSHPRNAMT` and counts distinct filers per
  `(security_id, quarter_end)`, restricted to CUSIPs the caller has
  already resolved -- never attempts CUSIP resolution itself, so a
  multi-million-row `INFOTABLE.tsv` is filtered without any per-row
  network call.

### 2. `scripts/build_institutional_ownership_cusip_map.py` (new, real network, one-time-ish)

Builds `{ticker: cusip}` for a given universe using ONLY
already-real-verified pieces:
- `data_infra.providers.sec_edgar.resolve_company_title` (new, mirrors
  `resolve_cik` exactly) reads a ticker's real company name straight
  out of `company_tickers.json` -- the SAME file
  `ingest_insider_transactions.py` already fetches for real every real
  run. No new network call type.
- Candidate CUSIPs come from text-matching that real name (suffix-
  stripped: `INC`/`CORP`/`CO`/...) against one recent bulk window's
  real `NAMEOFISSUER` field -- then EVERY candidate is confirmed
  through `openfigi_cusip_resolution`'s existing, real-verified
  CUSIP->ticker direction (`ADR-0131`) before being trusted. A
  coincidental name match alone can never mislabel a CUSIP -- it must
  ALSO resolve back to the exact expected ticker.
- An ambiguous ticker (multiple real OpenFIGI-confirmed CUSIPs) is
  excluded and flagged, never guessed.

### 3. `scripts/backfill_institutional_holdings_from_sec_bulk.py` (new, real network, the actual backfill)

Two-pass design (see the script's own module docstring for the full
"why" -- summarized: window-by-window dedup would miss a
later-window amendment superseding an earlier window's original).
Pass 1 downloads every requested window once, accumulating real
submissions and CUSIP-filtered infotable rows globally. Pass 2 runs
`latest_submission_per_period`/`aggregate_holdings` ONCE over the
global accumulation. Produces the exact
`security_id,quarter_end,institutional_shares,num_institutions`
combined-CSV schema `scripts/ingest_institutional_holdings.py
--combined-csv` already consumes unchanged (`ADR-0131`'s own existing
pipeline, no changes needed there).

A window this run requests but SEC never published is skipped with a
loud warning (this script does not know how far back SEC's real
archive goes) -- never silently treated as zero real data.

### 4. Two new `workflow_dispatch`-only GitHub Actions workflows

`build_institutional_ownership_cusip_map.yml` and
`backfill_institutional_holdings_from_sec_bulk.yml` -- this sandbox
cannot reach `www.sec.gov`/`api.openfigi.com` directly (`ADR-0131`'s
own disclosed limitation, unchanged). Each commits its real output
(`docs/research/reference/institutional_ownership_cusip_map.json`,
`.../institutional_holdings_combined.csv`) to the repo as a small,
durable reference artifact -- these are confirmed identifier/holdings
data, not a `*.duckdb`/`*.parquet` catalog, so this project's existing
exclusion of those from git is unaffected. The backfill workflow's
`timeout-minutes: 180` reflects a real cost: dozens of ~86MB real SEC
downloads, one per ~3-month window, back to `--start-year`.

## Deliberately NOT done in this ADR

- **Neither workflow has been run for real yet.** This ADR ships the
  pipeline; running `build_institutional_ownership_cusip_map.yml` then
  `backfill_institutional_holdings_from_sec_bulk.yml` for real, and
  wiring the resulting combined CSV into `ingest_institutional_
  holdings.py --combined-csv` (and from there into `run_long_horizon_
  validation.py`'s `institutional_ownership_change` candidate, which
  is ALREADY registered there but skipped without a `--institutional-
  db-path`) is the real next step, deliberately left as a follow-up so
  this diff stays reviewable and so the real backfill's actual output
  (row counts, coverage, any newly-discovered real format quirk) can
  be reported honestly rather than assumed.
- **`FILING_DATE`'s exact real format was not directly observed** by
  `verify_sec_13f_bulk_dataset.py` (it printed real column NAMES, not
  a raw `FILING_DATE` value) -- `_parse_sec_date` tries `PERIODOFREPORT`'s
  own confirmed `%d-%b-%Y` format first, then two other plausible SEC
  conventions, and raises loudly (never guesses silently) if none
  parse a real value. The real backfill run will confirm or correct
  this.

## Testing

- `tests/data_infra/test_sec_13f_bulk_dataset.py` (14 tests): window
  generation against the two independently real-confirmed URLs, leap-
  year December-window boundary, submission filtering/dedup (including
  the exact real scenario -- a late amendment in a later window still
  wins), aggregation (superseded accessions and unknown CUSIPs both
  correctly excluded).
- `tests/data_infra/test_sec_edgar_provider.py`: 3 new tests for
  `resolve_company_title`, mirroring `TestResolveCik` exactly.
- `scripts/build_institutional_ownership_cusip_map.py`/`scripts/
  backfill_institutional_holdings_from_sec_bulk.py` make real network
  calls and are therefore not exercised by the automated test suite,
  matching `convert_sec_13f_filings_to_combined_csv.py`'s own
  `ADR-0131` precedent.
- Full suite run before merge (branch-merge rule).
