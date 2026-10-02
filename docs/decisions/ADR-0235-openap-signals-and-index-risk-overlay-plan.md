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
