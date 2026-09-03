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

**Correction (ADR-0043 Decision 13):** this conclusion was wrong in one
specific, significant way. The user pushed back, asking specifically
about the most foundational ("S-tier"/"A-tier") papers rather than the
broader speciality literature this audit's search actually covered. A
targeted re-check found this project had **zero coverage of the Size
factor** -- Banz (1981)'s small-cap premium, one of the oldest and most
famous anomalies in asset pricing, the direct ancestor of the
Fama-French three-factor model's SMB factor, and (per the five-family
framing above) arguably a sixth independent family this audit's
"5 robust families" list omitted entirely (Size is priced on firm size
alone, distinct from Value/Quality's fundamentals-ratio construction).
The earlier "no new family surfaced" claim was a genuine miss, not a
hedge -- Size is exactly the kind of famous, easy-to-check anomaly a
citation audit like this one should have caught on its own. `size_score`
was built to close this gap (ADR-0043 Decision 13); see that decision
for the full build. Lesson for any future round of this audit: check
the canonical anomaly list by name (size, value, momentum, quality,
low-vol, profitability -- the "big six") explicitly, rather than only
searching for what related citations are already present, which is
exactly the blind spot that let this one through.

**Second correction (ADR-0043 Decision 14):** applying that exact
lesson -- checking the canonical anomaly list by name rather than only
what was already cited -- surfaced three more foundational papers this
project had never checked for: De Bondt & Thaler (1985, long-term
reversal), Jegadeesh (1990, short-term reversal), and Frazzini &
Pedersen (2014, Betting Against Beta / low-beta, distinct from the
already-built `low_volatility_score`). All three verified real and
built as `long_term_reversal_score`/`short_term_reversal_score`/
`low_beta_score`. See ADR-0043 Decision 14 for the full build. This
project's factor coverage is broader now across momentum's full
"return autocorrelation" family (momentum + both reversal horizons)
and the low-risk family (both total-vol and beta-based low-risk
premia) than the original "5-6 families" framing implied -- future
citation audits should treat momentum/low-risk each as a family with
multiple internally-distinct sub-anomalies, not a single checkbox.

**Third correction (ADR-0043 Decision 15):** two more findings, of a
different character from the first two corrections. First, a genuine
audit gap this ADR's original table should have caught: Novy-Marx
(2013) was already correctly and honestly cited in `net_margin_score`
("closely related... construction"), and this ADR's original citation
audit verified that hedge was accurate -- but never checked whether
the paper's OWN specific factor (gross profit/assets) had actually
been built anywhere. It had not. A citation being honestly hedged is
not the same as the paper's finding being implemented; this audit
should have flagged that gap explicitly rather than treating an
accurate hedge as equivalent to full coverage. Second, a genuinely new
family this project had zero prior coverage of: Amihud (2002)'s
illiquidity premium -- the first factor in this module's history to
use a `PriceBar`'s `volume` field at all. Both built as
`gross_profitability_score`/`illiquidity_score`; see ADR-0043 Decision
15. Liquidity should now be added to the "big six" (momentum/value/
quality/low-vol/size/liquidity) any future audit checks by name.

**Fourth correction (ADR-0043 Decision 16):** the user asked this
round for a genuinely thorough check, not just "more papers" -- two
kinds of gap turned up. First, three more famous, specific anomalies:
Altman (1968)'s Z-Score (applied per the Dichev 1998/Campbell-Hilscher-
Szilagyi 2008 distress-risk anomaly), George & Hwang (2004)'s 52-week-
high anomaly, and Bali, Cakici & Whitelaw (2011)'s MAX effect -- built
as `altman_z_score`/`fifty_two_week_high_score`/`max_effect_score`.
Second, and more significant for THIS audit's own credibility: a
script-level cross-check (every `*_score` function in
`factor_scores.py` against both CLI scripts' dispatch dicts) found 3
factor functions this project had ALREADY BUILT but never wired into
either CLI: `book_to_market_score`, `sales_yield_score`,
`cashflow_yield_score` (3 of `value_composite_score`'s 5 legs,
ADR-0043 Decision 12). Worse, `book_to_market_score`'s own docstring
explicitly claimed it was "independently testable on its own via
`compute_hybrid_ic_series`" -- a claim about CLI-level testability
that this audit, and every session since Decision 12, had simply never
verified against the actual CLI dispatch dicts. A citation audit that
only checks whether papers are cited correctly, without also checking
whether every factor a docstring claims is testable is ACTUALLY wired
for testing, will keep missing exactly this class of gap. Fixed: all 3
legs added to `_HYBRID_SCORES`. See ADR-0043 Decision 16 for the full
account and the wiring cross-check methodology, which should be
repeated at the start of any future round of this audit, not just at
the end of a productive one.

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
