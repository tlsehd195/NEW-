# ADR-0231: Every CUSIP a company has used in the 13F ownership map

**Status:** Accepted (code merged; map rebuild and backfill re-run pending)
**Date:** 2026-10-02
**Deciders:** account owner (asked for the 13F mapping fix, 2026-10-02), Claude Code session

## Context

ADR-0131 left one known problem: holdings are matched to a ticker
through the single CUSIP that company uses today. The 2026-09-26 map
(`docs/research/reference/institutional_ownership_cusip_map.json`, from
run 36235366882) and backfill
(`institutional_holdings_combined.csv`, 2013-06..2026-03) show two
consequences:

- **Missing early quarters.** A company whose CUSIP changed has no
  holdings before the change. The backfill starts AVGO at 2018-03,
  EQIX 2014-12, GE 2021-06, GOOGL 2015-09, RTX 2020-03 and WELL 2015-09
  (DOW 2019-03 is genuinely a new company). `institutional_ownership_
  change` would read the first quarter as a jump from zero.
- **12 of 87 names unmapped:** AMT, AVB, BAC, HON, LIN, NEM, OXY, QCOM,
  SLB, VLO, WFC, XOM. Name-matching found candidates for 79 names, but
  the OpenFIGI step turned every per-item error into "no match"
  silently, so the cause is not in the log (an OpenFIGI rate limit is
  the likely cause, but this is inferred). AVB is missing from SEC's
  ticker file.

13F data starts in 2013 Q3, so this does not affect the open research
window (2000..2013-03-21). It does affect any 13F-based run over later
years and the paper loop's inputs.

## Decision

`data_infra.providers.sec_13f_cusip_history` (pure functions), used by
`scripts/build_institutional_ownership_cusip_map.py`:

1. **Names over time.** Each company is matched under its current SEC
   name and every `formerNames` entry in its EDGAR submissions summary.
   Matching is whole-word (`GE` no longer matches `GENERAL MILLS`).
2. **Files over time.** Candidates come from one 13F file per year
   (legacy `YYYYq3` 2013-2023, then the `01jun` window each year) plus
   the two newest windows, instead of only the newest one.
3. **Acceptance.** A name-matched CUSIP is kept for a ticker if OpenFIGI
   resolves it to that ticker or one of its former tickers
   (`sp500_ticker_renames.csv`), or if OpenFIGI no longer resolves it
   and it shares the 6-character issuer prefix of an accepted CUSIP
   (same issuer, new issue number, e.g. a reverse split). A CUSIP
   claimed by two tickers is dropped from both.
4. **Map format** becomes `{ticker: [cusip, ...]}`.
   `backfill_institutional_holdings_from_sec_bulk.py` reads both
   formats (`load_cusip_to_ticker`) and sums every CUSIP of a ticker per
   quarter. `aggregate_holdings` already counts filers by accession, so
   a filer reporting both the old and new line counts once.
5. **No silent failures.** OpenFIGI item errors and HTTP 429 are
   retried. Every unmatched ticker is printed with its reason and the
   OpenFIGI answer for its candidates.

Then the map is rebuilt (`build_institutional_ownership_cusip_map.yml`,
timeout raised to 90 minutes) and the backfill re-run, which replaces
both committed files.

## Consequences

- Known limit: a company whose old line OpenFIGI resolves to a ticker
  that is neither its own nor in the rename list is still missed. The
  build log names each such case.
- Tests: `tests/data_infra/test_sec_13f_cusip_history.py`.
