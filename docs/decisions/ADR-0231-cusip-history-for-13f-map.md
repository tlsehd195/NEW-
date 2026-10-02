# ADR-0231: Every CUSIP a company has used in the 13F ownership map

**Status:** Accepted (done 2026-10-02: map run 36962309499, backfill run 36962851090)
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
3. **Acceptance (revised 2026-10-02 after the first rebuild).** In each
   sampled file, among share rows (`SSHPRNAMTTYPE` SH, no `PUTCALL`)
   whose issuer name matches, the valid CUSIP (check digit) with the
   most shares held is that file's dominant CUSIP for the ticker. The
   common stock dwarfs preferreds, notes and typo CUSIPs, so this picks
   the common line of each era. A dominant CUSIP is kept unless OpenFIGI
   resolves it to a ticker that is neither this one nor a former one
   (`sp500_ticker_renames.csv`); unresolved ones are kept and logged. A
   CUSIP kept for two tickers is dropped from both. The first rebuild
   (run 36941450358) used an issuer-prefix rule instead and pulled in
   preferreds, notes and option lines (43 CUSIPs for AT&T); its name
   normalisation also turned "INC/DE" into "INCDE", which missed BAC,
   WFC, QCOM and NEM. Punctuation now becomes a space and state
   suffixes are stripped.
   Debt issues (letters in CUSIP characters 7-8, e.g. Tesla's
   convertible notes) are never dominant.
4. **Reviewed overrides.** The second rebuild (run 36959779750, 86/87
   names) showed what name matching alone cannot settle: a ticker whose
   predecessor filed under another CIK and name (Alphabet/Google,
   Linde plc/Praxair) and a different company sharing the name (Linde AG
   before 2018, Broadcom Corp before Avago bought it, Dow Chemical before
   Dow Inc). `docs/research/reference/sec_13f_cusip_overrides.csv` lists
   each correction with its reason (`predecessor_name`,
   `exclude_cusip`). Avago itself is not added as a predecessor of AVGO:
   its pre-2016 13F lines are not checked.
5. **Map format** becomes `{ticker: [cusip, ...]}`.
   `backfill_institutional_holdings_from_sec_bulk.py` reads both
   formats (`load_cusip_to_ticker`) and sums every CUSIP of a ticker per
   quarter. `aggregate_holdings` already counts filers by accession, so
   a filer reporting both the old and new line counts once.
6. **No silent failures.** OpenFIGI item errors and HTTP 429 are
   retried. Every unmatched ticker is printed with its reason and the
   OpenFIGI answer for its candidates.

Then the map is rebuilt (`build_institutional_ownership_cusip_map.yml`,
timeout raised to 90 minutes) and the backfill re-run, which replaces
both committed files.

## Consequences

- Known limit: a company whose old line OpenFIGI resolves to a ticker
  that is neither its own nor in the rename list loses that line. The
  build log prints each rejection and each CUSIP kept without OpenFIGI
  confirmation.
- Tests: `tests/data_infra/test_sec_13f_cusip_history.py`.

## Result (2026-10-02)

- Map (run 36962309499): 86 of 87 names. AVB is not in SEC's ticker
  file. Multi-CUSIP names: AVGO, EQIX, GE, GOOGL (Google era), LIN
  (Praxair era), RTX (UTX), WELL.
- Backfill (run 36962851090): 4,353 rows, 2013-06..2026-03. Every name
  that was missing or late now starts at 2013-06 except AVGO (2015-12,
  Broadcom Ltd; the Avago era is not included) and DOW (2019-03, a new
  company). Quarter-to-quarter jumps that remain are stock splits,
  which `split_adjusted_institutional_holdings` already corrects.
