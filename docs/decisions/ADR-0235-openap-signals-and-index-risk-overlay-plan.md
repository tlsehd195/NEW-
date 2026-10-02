# ADR-0235: OpenAP signal ingestion and index+risk-overlay plan

**Status:** Proposed
**Date:** 2026-10-02
**Deciders:** account owner (동동), Claude Code session

**Related documents:** `docs/decisions/ADR-0214` (new-factor research reopened),
`docs/decisions/ADR-0222`/`ADR-0228` (locked windows, TEST_4),
`src/strategy_research/locked_windows.py`, `ADR-0217` (macro filter design,
still unwired).

## Context

동동 asked (2026-10-02) which of four ways to make a new "test" for
strategy research were feasible, now that the US unlocked research window
is nearly exhausted (only 2000-01-01..2013-03-21 remains open per
`locked_windows.py`). Investigation (see project thread "해외 주식 데이터
출처 확인") found:

- Overseas daily price data (option 2) needs a paid provider (e.g. EODHD)
  beyond the four sources already wired in; account owner has not yet
  decided to pay for this.
- Pre-2013 short-interest / non-13F guru-holdings data (option 3) does
  not appear to exist from any free or paid source found.
- Option 1 (Open Source Asset Pricing / Chen & Zimmermann signal panel)
  and option 4 (index-hold + risk-management reframe) need no new paid
  data and can proceed now.

## Decision

### 1. OpenAP signal ingestion

- Download the OpenAP signal panel (free, no WRDS license required, via
  the `OpenSourceAP.DownloadR`-equivalent CSV distribution) into
  `data/external/openap/` (gitignored raw cache; only the ingestion
  script and a coverage report are committed).
- Build a `permno -> ticker` mapping (CRSP permno is OpenAP's row key;
  this project's price data is ticker-keyed) using a public
  permno-ticker crosswalk. Expect incomplete coverage for delisted
  names, the same class of gap `ADR-0224` already measured for Tiingo.
- Screen only signals this project has not already implemented under a
  different name (cross-check against `TEST_2`/`TEST_3`'s
  `observed_by` lists and `ADR-0214`'s factor set) to avoid re-testing
  known candidates.
- Walk-forward screening runs only inside the still-open window
  (2000-01-01..2013-03-21, `earliest_locked_window_start()`), with
  `final_exam=false` as the default for every screening run, per
  RULE 0.8. No new window gets locked until a pre-registered finalist
  list is ready for a one-time held-out exam (the `ADR-0228` pattern).

### 2. Index-hold + risk-management reframe

- This is not alpha search, so it does not consume the locked-window
  budget: the comparison is index exposure sizing (how much of the
  portfolio is in SPY vs. cash/bonds) against plain buy-and-hold SPY,
  not a new factor against SPY.
- First candidate overlay: promote the existing macro filter rules
  (`ADR-0217`, currently observe-only — Sahm rule etc., all previously
  INCONCLUSIVE as return predictors) to an exposure-sizing rule, scored
  on risk-adjusted terms (Sharpe, max drawdown) rather than excess
  return, since the goal is drawdown reduction, not beating SPY's CAGR.
- A design note with the specific sizing rule and its evaluation metric
  will follow as this ADR's first "Decision 2" amendment or a successor
  ADR, before any backtest code is written, so the risk-vs-return
  tradeoff is explicit up front (same "decide the judging rule before
  running the backtest" discipline as `ADR-0228`).

### 2a. Pre-registered overlay candidates (fixed before any backtest)

`ADR-0220` already showed the 12 macro rules are INCONCLUSIVE (best DSR
0.25) and the one lead, the Sahm rule, rests on 5 exposure changes, so
promoting it is not justified. The overlay track therefore tests only
two standard, parameter-free rules with decades of public evidence:

- `sma_10m`: hold SPY while the month-end close is above its 10-month
  average, otherwise hold cash (checked monthly, trade next open).
- `vol_target_10`: SPY weight = min(1, 10% / trailing 21-day realized
  volatility), no leverage.

Both earn the FRED `DGS3MO` rate on cash (`ADR-0227`), pay the backtest
engine's default transaction costs (as `ADR-0220`), and run only on
2000-01-01..2013-03-20. `vol_target_10` re-weights only when the held
share is 10 points off target; `sma_10m` decides on the first trading day
of each month from the previous month-end closes. Trial count: 2.
Code: `src/macro_filter/overlays.py`, `scripts/run_index_overlay_validation.py`,
`run_index_overlay_validation.yml`.

Pass rule: max drawdown at least 15 points shallower than SPY buy-and-hold
AND Sharpe not lower AND CAGR no more than 1.5 points lower. Passing does
not mean validated: this window holds only two bear markets (2000-02 and
2008-09), so a pass is reported as research-window evidence only.

## Consequences

- No locked window is touched by either track.
- OpenAP ingestion adds a new external data dependency (one more
  crosswalk-matching gap to document, like `ADR-0224`'s Tiingo
  coverage table) but no new paid service.
- The risk-overlay track changes what "success" means for that one
  strategy family (risk-adjusted vs. excess return) — this must stay
  scoped to that family; existing factor screening keeps the current
  excess-return bar.
- Options 2 (해외 주식) and 3 (공매도/구루 데이터) stay blocked: 2 needs
  the account owner to pay for and provision a provider like EODHD; 3
  has no known data source at any price for the 2000-2013 window and is
  not planned further unless a new source surfaces.

## Findings (2026-10-02, real probes from GitHub runners)

- **KRX (option 2, Korea) is blocked from GitHub runners.**
  FinanceDataReader's `KRX-DELISTING` listing came back empty and a direct
  POST to `data.krx.co.kr` (`MDCSTAT23801`) returned HTTP 400, so the free
  route needs a Korean network or a KRX login that was not tried. Its cache
  repo (`FinanceData/fdr_krx_data_cache`) holds delisting lists, not
  delisted price history. Option 2 stays unproven for Korea and unavailable
  for Japan/Europe without a paid provider.
- **Yale 13F 1999-2017 dataset (option 3) is not downloadable.** The page
  lists the files but no links ("evaluating hosting options, contact the
  authors") and answers HTTP 410 to a runner. An earlier note in this
  thread called it a free CSV download; that was wrong. The remaining free
  route is parsing EDGAR's pre-2013 plain-text 13F filings for a short
  list of guru filers (not started; existing 13F code reads only the XML
  era).
- **OpenAP works from a runner** (`openassetpricing` package): 331 signals
  documented, plus the paper-style long-short portfolio returns
  (`dl_port("op")`). Over 2000-01-01..2013-03-20, 165 of the 212 signals
  with a long-short series are rated "clear" by OpenAP, and 56 of those had
  an original sample ending in 1999 or earlier, so this window is true
  out-of-sample for them. With 56 looks the Harvey-Liu-Zhu bar is |t| > 3:
  AnnouncementReturn (t 6.0), DivYieldST (5.6), ChangeInRecommendation
  (4.5), AccrualsBM (4.3) and ExchSwitch (3.4) clear it. The classics are
  dead here: Accruals t 0.8, Size 1.2, 12-month momentum 0.2. These are
  full-universe long-short returns including small caps, not long-only
  S&P 500 results, and only DivYieldST is computable from data this
  project already holds (prices plus dividends); the others need earnings
  dates, analyst data or a pre-2009 fundamentals history.

