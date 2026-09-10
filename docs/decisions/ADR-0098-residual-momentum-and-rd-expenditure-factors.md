# ADR-0098: Residual Momentum and R&D Expenditure Anomaly factors

**Status:** Accepted
**Session:** 36 (continued)

## Context

Following the completion of the 5 dragon1086/prism-insight-derived
items (RS Rating through the shadow evaluation harness, ADR-0090
through ADR-0094), the user asked for a broader search: find other
GitHub/web projects similar to this one, sorted by star count, and
identify anything worth borrowing strategy-wise. That search (WebSearch/
WebFetch, deliberately not `mcp__github__search_repositories`, since
this session's repository scope is restricted to `tlsehd195/new-` and a
repo-argument-less GitHub search tool could reach beyond it) surveyed
microsoft/qlib (~47k stars), TradingAgents (~99k), ai-hedge-fund,
Hummingbot, Qbot, Abu, and `paperswithbacktest/awesome-systematic-
trading` (13.4k stars) -- a curated database of published, academic-
paper-backed systematic trading strategies with real backtested
results, philosophically the closest match to this project's own
"cite real papers, RULE 0.8, no fabrication" discipline. Cross-
referencing its strategy list against this project's ~30+ already-
implemented factors surfaced two genuinely new, not-yet-covered, low-
implementation-cost candidates, both chosen and their construction
fixed before any result exists (RULE 0.8):

1. **Residual Momentum** (Blitz, Huij & Martens 2011, "Residual
   Momentum," Journal of Financial Economics 108(3): 506-521) --
   price-only, needing no new data ingestion.
2. **R&D Expenditure Anomaly** (Chan, Lakonishok & Sougiannis 2001,
   "The Stock Market Valuation of Research and Development
   Expenditures," The Journal of Finance 56(6): 2431-2456) -- needs
   exactly one new XBRL concept (`ResearchAndDevelopmentExpense`)
   added to the fundamentals ingestion's default concept list, the
   identical "zero additional real network requests" pattern
   `EarningsPerShareDiluted` already established for `sue_score`
   (ADR-0084).

The user's follow-up message ("저기서 찾은거 적용하고") authorized
proceeding with these two specifically -- they were already flagged as
the lowest-cost, highest-priority pair in the prior turn's research
report.

## Decision

**`strategy_research.factor_scores.residual_momentum_score`**:
regresses a security's daily returns against `BENCHMARK_SYMBOL` ("SPY")
via the same `Cov/Var` OLS beta/alpha estimator `low_beta_score`/
`idiosyncratic_volatility_score` already use, but over an
**out-of-sample split**: beta/alpha are estimated on an EARLIER,
non-overlapping `estimation_days` window (default 252, ~12 months),
then applied to compute residuals over the immediately FOLLOWING
`formation_days` window (default 63, ~1 quarter, reusing `rs_rating_
score`'s own "R63" unit for vocabulary consistency rather than the
original paper's 11-month formation window). Score = `mean(formation
residuals) / std(formation residuals)`.

**A real estimator subtlety, caught by reasoning about the math before
any test was run against it -- still RULE 0.8, since this is a
correctness fact about OLS itself, not an empirical peek**: a first
design that estimated alpha/beta and computed "momentum" residuals over
the IDENTICAL window would have produced a score of ~0 for every
security, always, because an intercept-including OLS regression's own
residuals sum to exactly zero over its own estimation sample by
construction. The out-of-sample estimation/formation split above is
the fix, and matches how the literature's own rolling-factor-loading
approach avoids the identical problem.

**`strategy_research.factor_scores.rd_expenditure_score`**: `Research
AndDevelopmentExpense / market_cap` ("R&D-to-market"), the same market-
cap construction `sales_yield_score`/`book_to_market_score` already
use. The numerator reads a genuinely absent
`ResearchAndDevelopmentExpense` tag as `0.0` (real zero R&D spending),
never `None`, via `_fy_flow_or_zero` -- the identical reasoning that
helper's own docstring already gives for `shareholder_yield_score`'s
dividend/buyback/issuance concepts.

**Both wired in before any real result exists (RULE 0.8)**:
`residual_momentum` into `compute_signal_ic_from_catalog.py`'s
`_PRICE_ONLY_SCORES` and `run_long_horizon_validation.py`'s
`_PRICE_FACTOR_CANDIDATES`; `rd_expenditure` into `compute_fundamentals
_ic_from_catalog.py`'s `_HYBRID_SCORES` and `run_long_horizon_
validation.py`'s `_HYBRID_FACTOR_CANDIDATES`; `ResearchAndDevelopment
Expense` added to `ingest_fundamentals_data.py`'s `_DEFAULT_CONCEPTS`.

## What this does NOT do

Does not use the Fama-French 3-factor model (market, SMB, HML) the
original Residual Momentum paper regresses against -- no independently
-constructed SMB/HML series exists for this project's 63-security
universe, the same limitation `idiosyncratic_volatility_score` already
states for its own market-only regression. Does not use Chan,
Lakonishok & Sougiannis' own R&D-CAPITAL (amortized multi-year stock)
construction -- a single latest-fiscal-year flow is used instead, the
same simplification `shareholder_yield_score`'s numerator already
makes for its own flow concepts. Does not continue the broader
GitHub/web search for more borrowable strategies -- that is a separate,
ongoing thread per the user's own "더 찾아볼 수 있으면 찾아봐" instruction.

## Tests

`tests/strategy_research/test_factor_scores.py::TestResidualMomentumScore`
(3 tests: an out-of-sample winner scores higher than an out-of-sample
loser -- built by giving WINNER/LOSER an IDENTICAL price path to SPY
during the estimation portion (beta=1, alpha=0 by construction) and
only diverging during the formation tail, so the test itself proves the
out-of-sample design actually produces a nonzero, discriminating score;
insufficient paired history returns `None`; missing benchmark data
returns `None`) and `::TestRdExpenditureScore` (5 tests: computes the
ratio correctly; a genuinely absent concept reads as `0.0` not a missing
score; higher R&D intensity scores higher; missing shares/price both
return `None`). `tests/strategy_research/test_run_long_horizon_
validation_factor_wiring.py`'s `_EXPECTED_NAMES` extended to 27 names.
Full suite re-run, 2543 tests pass (up from 2535 after ADR-0097).
