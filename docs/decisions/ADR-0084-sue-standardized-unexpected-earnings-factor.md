# ADR-0084: SUE (Standardized Unexpected Earnings) added, wired blind before any real result

**Status:** Accepted
**Session:** 36 (continued)

## Context

The account owner asked to resume strategy research after learning
that none of the 30 candidates tested so far (Session 36's Phase 33
20-literature-candidate batch plus the original 9-candidate pool --
value, quality, momentum/reversal, low-risk, size, liquidity,
financial-health/distress, shareholder yield, and cross-sectional
composites of these) reached `EvidenceLevel.VALIDATED`; 2 reached
`CANDIDATE` (`altman_z`, `rank_average_ensemble`) but failed their own
held-out TEST. Given how exhaustively the classic equity-factor
literature had already been covered, the next candidate needed to be a
genuinely different category, not a cosmetic variant of something
already tested (`compute_signal_ic_from_catalog.py`'s own module
docstring already warns against exactly that).

Two genuinely new, data-feasible categories were identified and
presented to the account owner: (1) Standardized Unexpected Earnings /
post-earnings-announcement drift, computable from data already
partially ingested (SEC EDGAR quarterly filings); (2) insider trading
signals (SEC Form 4), needing a NEW data source not yet verified
accessible. The account owner chose to do both, SUE first. This ADR
covers SUE only.

## Decision

Added `strategy_research.factor_scores.sue_score` -- Foster, Olsen &
Shevlin 1984's Standardized Unexpected Earnings ("Earnings Releases,
Anomalies, and the Behavior of Security Returns," The Accounting
Review), the mechanism behind the post-earnings-announcement drift
documented by Bernard & Thomas 1989 (Journal of Accounting Research):

```
SUE = (EPS_q - EPS_{q-4}) / stdev(trailing 8 such YoY differences)
```

Uses the seasonal-random-walk definition of "expected earnings" (no
I/B/E/S analyst consensus needed or available). Needs
`EarningsPerShareDiluted` at QUARTERLY granularity -- the first score
in `factor_scores.py` needing quarter-level rather than fiscal-year-
level data, requiring a new `_quarterly_records` helper (parallel to
the existing `_fy_records`, deduping by `period_end` to the
latest-filed value so a restatement never shifts the positional "4
quarters ago" lookup every later quarter's score depends on).

**Zero additional real network requests**: `SecEdgarFundamentalsProvider.
fetch_company_facts` already fetches one company's entire company-facts
JSON per request regardless of which concepts are asked for --
`EarningsPerShareDiluted` was simply never parsed out of that response
before. Added to `ingest_fundamentals_data.py`'s `_DEFAULT_CONCEPTS`,
same zero-extra-request justification every earlier concept addition
in this project has used.

Wired into both places every earlier candidate is wired into, before
any real IC result exists for it (RULE 0.8, same "wire it in blind"
discipline ADR-0051/ADR-0053/ADR-0054 already established): `--score
sue` in `compute_fundamentals_ic_from_catalog.py`, and the walk-forward
candidate pool in `run_long_horizon_validation.py`
(`_FUNDAMENTALS_FACTOR_CANDIDATES`).

## What this does NOT do

Does not run raw IC screening or walk-forward/PBO/DSR against real
data -- this session's own outbound network is blocked to SEC EDGAR
(the same long-standing constraint `ingest_fundamentals_data.py`'s
module docstring already documents), so no real result can be produced
here. The account owner needs to re-run `scripts/
ingest_fundamentals_data.py` (with `EarningsPerShareDiluted` now
included by default) in an environment with real network access before
`--score sue` can compute anything against real data. Does not decide
or predict whether `sue_score` will match its literature-predicted
sign -- stated here, before that real run, specifically so this ADR
cannot later be read as having cherry-picked the hypothesis after
seeing a result. Does not build the insider-trading candidate (tracked
separately, pending a data-feasibility check).

## Tests

`tests/strategy_research/test_factor_scores.py::TestSueScore` (6
tests, synthetic fixtures only): a clear positive YoY surprise scores
positive, a clear negative surprise scores negative, perfectly flat
YoY earnings returns `None` (never a fabricated z-score against zero
variance), fewer than 12 known quarters returns `None`, a quarter
filed after `as_of_time` is correctly excluded (point-in-time safety,
mirroring every other score in this module), and a superseded
earlier-filed duplicate for the same `period_end` is correctly ignored
in favor of the latest-filed value. Full suite re-run, all tests still
pass (SUE's own 6 plus every pre-existing test unaffected).
