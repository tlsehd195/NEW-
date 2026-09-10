# ADR-0102: Cash Holdings factor, and a full JKP catalogue review

**Status:** Accepted
**Session:** 36 (continued)

## Context

After ADR-0101 added 2 candidates from already-surfaced leads
(`age`, `opex_at`, `capex_abn`, etc.), the account owner asked directly
whether the ENTIRE JKP "Global Factor Data Documentation" PDF had been
reviewed. It had not -- only specific leads had been checked. The
account owner then explicitly instructed a full pass: "전부 확인하고
적용할만 한거 적용해" ("check everything, and apply whatever is worth
applying").

This ADR records that systematic review: Table 9 ("Factor and Cluster
Details," ~150 factors across 13 clusters, the document's own
cited-anomaly catalogue, lines ~4690-6560 of the local extraction) and
the earlier "Detailed Characteristic Construction" tables (lines
~656-4690) were both read through in full, not just grepped for
pre-identified terms.

**A structural finding that shaped the outcome**: past line ~5918, the
document's own section header changes to "Other Factors," and its own
notation matrix (Table 9's citation columns) stops for the roughly 150+
"growth in X scaled by AT/BE/ME" mechanical variants that follow
(`debt_gr3`, `fnl_gr1a`, `ncol_gr1a`, `cash_gr1a`, `capx_gr3a`, and
dozens more) -- these are JKP's own systematic transformation
methodology applied uniformly across balance-sheet/income-statement
line items, not individually-tested, individually-cited academic
findings the way every other cluster's entries are. This confirms
ADR-0101's earlier decision to skip that whole family was correct, now
on direct evidence rather than inference.

**Two other candidates seriously considered and explicitly rejected**,
recorded here rather than silently dropped:

- **`bidaskhl_21d`** (the Corwin-Schultz high-low bid-ask spread
  estimator): this project HAS the needed daily high/low price data
  (`PriceBar.high`/`.low`). But the document itself does not give the
  estimator's own formula inline -- it says only "High-low bid ask
  estimator created using code from Corwin and Schultz (2012)," pointing
  to the external paper's own two-day beta/gamma algorithm. Reconstructing
  a precise multi-step statistical estimator from memory of the cited
  paper, rather than from this session's own verified documentation, is
  a different and less-verified risk than the paper-formula
  cross-checks this session has done for every other factor -- deferred,
  not rejected, pending either obtaining that paper directly or finding
  the exact algorithm spelled out somewhere accessible.
- **`netdebt_me`** (net debt scaled by market equity, cited to Penman,
  Richardson & Tuna 2007): that paper's own actual contribution --
  decomposing book-to-price into an operating and a financial-leverage
  component -- is a more nuanced finding about how leverage INTERACTS
  with the book-to-price effect, not a simple "net debt to price
  predicts returns" univariate claim. Implementing this with confidence
  in the correct sign would require reading the paper directly, which
  this session has not done -- deferred, not rejected.
- **`at_be`** (book leverage, `Assets/BookEquity`): rejected outright
  (not deferred) -- algebraically a monotonic transform of
  `leverage_score`'s own `Liabilities/Equity` ratio (`AT/BE ==
  Liabilities/Equity + 1`), so it would rank securities identically
  under Spearman IC. Not a new signal.
- **`rd_sale`** (R&D scaled by Sales): rejected outright -- Table 9's
  own ordered citation list matches this to the SAME paper (Chan,
  Lakonishok & Sougiannis 2001) this project already cites for
  `rd_expenditure_score` (R&D scaled by Market Equity). Same underlying
  academic finding, different JKP scaling choice -- not independent
  literature.
- **`rd5_at`** / **`ni_ivol`**: both need substantially more complex
  constructions (a 5-year declining-balance R&D capitalization; a
  rolling-window regression with grouped RMSE) than this project's
  existing single-period-ratio pattern -- deferred pending a dedicated
  design pass, not attempted blind.

## Decision

**`cash_holdings_score`** (Palazzo 2012, "Cash Holdings, Risk, and
Expected Returns," Journal of Financial Economics 104(1): 162-185):
`cash_at = CASH_t / AT*_t`, RAW (not negated). Palazzo's own finding is
a risk-based explanation for a POSITIVE relation: cash-rich firms carry
more valuable growth options, more exposed to the same aggregate shocks
that drive market returns, so cash predicts HIGHER subsequent returns --
not a "safety" story. The same "opposite sign convention" situation
ADR-0101 already documents for `operating_leverage_score`.

**Verified two independent ways** before trusting it: (1) the exact
formula appears inline in the document's own "New Variables from HXZ"
section; (2) Table 9's "Low Leverage" cluster lists its citations in
the SAME order as its abbreviation list two pages earlier -- aligning
`cash_at` with `Palazzo (2012)`, independently confirmed by the exact
matching entry in the document's own References section. Needs ZERO new
data: `CashAndCashEquivalentsAtCarryingValue` (already ingested for
`net_operating_assets_score`) and `Assets`.

Wired into `compute_fundamentals_ic_from_catalog.py`'s `_SCORES`
(`--score cash_holdings`) and `run_long_horizon_validation.py`'s
`_FUNDAMENTALS_FACTOR_CANDIDATES` (the pool's 42nd candidate) **before
any real result exists**, per RULE 0.8.

## What this does NOT do

Does not implement `bidaskhl_21d`, `netdebt_me`, `at_be`, `rd_sale`,
`rd5_at`, or `ni_ivol` -- see the rejections/deferrals above. Does not
implement any of the ~150 "Other Factors" mechanical growth/scaling
transforms -- see the structural finding above. Does not claim this
document has nothing left to offer: `bidaskhl_21d`/`netdebt_me`/
`rd5_at`/`ni_ivol` remain real, deferred candidates if a future session
obtains the Corwin-Schultz paper directly, reads Penman/Richardson/Tuna
(2007) in full, or designs the more complex multi-period constructions
those last two need.

## Tests

`tests/strategy_research/test_factor_scores.py::TestCashHoldingsScore`
(5 tests). `test_run_long_horizon_validation_factor_wiring.py`'s
`_EXPECTED_NAMES` extended to 34 names across 6 candidate tables. Full
suite re-run: see `PROJECT_STATUS.md` for the exact count.
