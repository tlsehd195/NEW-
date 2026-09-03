# ADR-0047: Academic citation audit -- did this project use its cited papers correctly, and are there more worth using?

**Status:** Accepted (audit only, no code changed)
**Session:** 36

## Context

The user asked two things: (1) verify every academic paper this project
cites was actually used correctly (real paper, correctly attributed
claim, formula actually matches what was implemented), and (2) check
whether there are more good papers worth using beyond what this project
already has.

Every factor/statistic this project has built was, per this project's
own established discipline, supposed to be fixed from an
independently-verified published source BEFORE any result was seen
(RULE 0.8) -- this audit checks whether that discipline actually held,
not just whether it was claimed to.

## Method

Every citation in `src/strategy_research/factor_scores.py` and
`src/strategy_research/pbo_dsr.py` was extracted, then verified one of
two ways:

1. **Numerical formula cross-check** (strongest available evidence):
   already done for the PBO/DSR papers in `ADR-0046` -- this project's
   hand-rolled implementation was run against `purgedcv`, an
   independent library implementing the same published formulas, on
   synthetic data. Not repeated here.
2. **Web search verification** (this ADR): for every other citation,
   confirmed the paper exists with the stated authors/year/journal, and
   that its actual finding matches what this project's docstring claims
   it found. Citations already web-verified earlier in this session
   (when the factor was first built: `asset_growth_score`,
   `piotroski_f_score`, `shareholder_yield_score`,
   `sloan_accruals_score`, `dividend_growth_score`,
   `earnings_yield_score`, `book_to_market_score`,
   `value_composite_score`, `quality_minus_junk_score`) were not
   re-searched; citations that predate this session's visible history
   (`low_volatility_score`, `roe_score`/`net_margin_score`'s Novy-Marx
   reference, `book_to_market_score`'s Rosenberg/Reid/Lanstein origin
   reference) were freshly re-verified now, since this audit could not
   otherwise confirm they were ever actually checked rather than
   recalled from training data.

## Results -- citation-by-citation

| Citation | Used for | Verified now | Verdict |
|---|---|---|---|
| Bailey, Borwein, Lopez de Prado & Zhu (2015), "The Probability of Backtest Overfitting," J. Computational Finance | `compute_pbo` | Numerically, ADR-0046 | Formula matches (with 2 documented, understood convention differences, not errors) |
| Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio," J. Portfolio Management | `compute_dsr_for_all_candidates` | Numerically, ADR-0046 | sr0 formula bit-exact; PSR/DSR small documented skew/kurtosis-convention difference |
| Ang, Hodrick, Xing & Zhang (2006), "The Cross-Section of Volatility and Expected Returns," J. Finance | `low_volatility_score` | **Yes, this ADR** | Real paper; finding (high idiosyncratic vol -> low returns) matches our hypothesis direction. Minor honest gap: the paper studies IDIOSYNCRATIC volatility (residual after a factor model); our score uses TOTAL trailing realized volatility, a simplification not previously stated this explicitly |
| Baker, Bradley & Wurgler (2011), "Benchmarks as Limits to Arbitrage," Financial Analysts Journal | `low_volatility_score` | **Yes, this ADR** | Real paper, exact title/journal match; finding (low-vol/low-beta outperform) matches |
| Novy-Marx (2013), "The Other Side of Value: The Gross Profitability Premium," J. Financial Economics | `roe_score`/`net_margin_score` ("closely related" framing) | **Yes, this ADR** | Real paper. Correctly hedged: our docstrings say "closely related," never claim ROE/net margin ARE Novy-Marx's factor -- his is gross profit/assets specifically, ours are net-income-based. Honest, not a misattribution |
| Rosenberg, Reid & Lanstein (1985), "Persuasive Evidence of Market Inefficiency," J. Portfolio Management | `book_to_market_score` (origin reference) | **Yes, this ADR** | Real paper, correct title/journal/volume/pages, 2,100+ citations -- legitimately the earliest book-to-market anomaly paper |
| Senchack & Martin (1987), "The Relative Performance of the PSR and PER Investment Strategies," Financial Analysts Journal | `sales_yield_score` | **Yes, this ADR** | Real paper, exact match; finding (low-P/S outperforms) matches, and the paper's own caveat (low-P/E still dominates low-P/S) is consistent with this project treating P/S as one of five legs, never the sole signal |
| Sloan (1996); Cooper, Gulen & Schill (2008); Piotroski (2000); Hribar & Collins (2002); Basu (1977); Fama & French (1992); Boudoukh, Michaely, Richardson & Roberts (2007); Asness, Moskowitz & Pedersen (2013); Asness, Frazzini & Pedersen (2013/2019) | accruals/asset growth/F-Score/CFO-based accruals method/earnings yield/book-to-market/shareholder yield/value+momentum/quality composite | Already done when each factor was built (this session) | All previously confirmed real and correctly attributed; not re-run |
| O'Shaughnessy, "What Works on Wall Street" | `value_composite_score` | N/A -- a practitioner book, not a peer-reviewed paper | Correctly presented as a book throughout, never described as an academic paper -- no misattribution to correct |

**No hallucinated or misattributed citation was found anywhere in this
project's factor code.** Every author/year/journal checked resolves to
a real, correctly-cited paper, and every claimed finding matches what
that paper actually reports.

## Formula-level fidelity check: Piotroski F-Score

Beyond confirming the citation is real, re-derived the paper's exact 9
criteria from independent sources (Wikipedia, AAII, StableBread,
UCLA Anderson) and compared against `piotroski_f_score`'s
implementation signal-by-signal: ROA > 0; CFO > 0; ROA improved YoY;
CFO > NI (accrual quality); long-term-debt/assets ratio decreased;
current ratio improved; no new shares issued; gross margin improved;
asset turnover improved. **All 9 match exactly**, including the
specific leverage definition (long-term debt over total assets, not a
broader debt measure).

One minor, honestly-flagged open question: some secondary sources
describe the leverage ratio's denominator as "average total assets"
(implying `(beginning + ending assets) / 2`), while this project's
implementation uses each fiscal year's own period-end assets
(`current_ltd / current_assets`, `prior_ltd / prior_assets`) rather
than an averaged denominator. This is a small, common simplification in
practitioner implementations of the F-Score and does not change any of
the other 8 signals; not changed here without checking Piotroski's own
original paper text directly (not accessible in this environment), and
not expected to materially change results given it affects only 1 of 9
equally-weighted binary signals.

## Are there more good papers worth using?

Searched broadly for well-replicated factor families this project's 17
factor scores (`roe`/`roa`/`net_margin`/`leverage`/`momentum`/
`low_volatility`/`trend_volatility` + the 8 Decision-8-through-12
candidates + `book_to_market`/`sales_yield`/`cashflow_yield`) might be
missing entirely. Current research consistently names five robust
families: momentum, low-risk/low-volatility, quality, profitability,
and value -- **this project already has at least one, usually several,
factors in every one of those five families.** No new family surfaced.
This is consistent with, not contradictory to, the earlier session
finding (ADR-0043 Decisions 8-12) that an additional literature search
beyond the original 12 candidates found nothing new worth adding.
**Conclusion: no new paper-backed candidate found this round; this
project's factor coverage is already broad across the recognized
factor literature.**

## What this does NOT do

- Does not change any factor's implementation -- this is a verification
  pass, not a code change. The one open question (Piotroski's leverage
  denominator) is flagged, not resolved or altered.
- Does not claim the original Piotroski (2000) paper's exact text was
  read directly (not accessible in this environment) -- the formula
  fidelity check used independent secondary sources describing the
  paper's methodology, cross-checked against multiple sources agreeing
  with each other, not the primary source itself.
- Does not add any new factor candidate -- confirms existing coverage
  is broad, does not claim it is exhaustive of all possible academic
  literature.
