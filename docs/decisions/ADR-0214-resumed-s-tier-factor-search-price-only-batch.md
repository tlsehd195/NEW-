# ADR-0214: Resumed S-tier factor search -- intermediate momentum, price delay, frog-in-the-pan

**Status:** Accepted
**Date:** 2026-09-26
**Deciders:** account owner ("새 팩터 탐색 ... 해줘"), Claude Code session

**Related documents:** `ADR-0107`/`0108`/`0109` (the last S-tier round),
`ADR-0209` (51-candidate human review; this search was its deferred
finding 3), `ADR-0212`/`ADR-0213` (Stage 5 2000-onward price catalog and
`price_only` validation mode), `src/strategy_research/locked_windows.py`.

## Context

`ADR-0209` found none of the 51 candidates worth marking VALIDATED and
deferred a fresh search for top-tier ("S-tier") factors, paused since
`ADR-0107`~`0109`. The existing 52 factor functions already cover most
canonical anomalies (value, size, 12-1 momentum, reversal, low risk,
profitability, investment, accruals, distress, liquidity, skewness,
seasonality, issuance, insider, short interest, 13F).

This round is limited to **price-only** candidates on purpose:

1. They need zero new data, so the Stage 5 203-symbol 2000-onward
   catalog now being ingested (`ADR-0213`) can evaluate them in its
   `price_only` run, the longest real history this project has.
2. `TEST_1`/`TEST_2` lock 2020-08-28..2026-08-27, so every new
   candidate can only be studied before 2020-08-28. A longer pre-2020
   window matters more for price factors than for fundamentals, whose
   own XBRL history starts around 2009-2010 anyway.

Three widely cited papers, each testing a mechanism none of the
existing factors measures, were chosen:

| name | paper | what it measures | direction |
|---|---|---|---|
| `intermediate_momentum` | Novy-Marx (2012), JFE 103(3): 429-453 | return from 12 to 7 months ago, ignoring the last 6 | higher is better |
| `price_delay` | Hou & Moskowitz (2005), RFS 18(3): 981-1020 | D1: share of market co-movement that arrives with a 1-4 week lag | higher is better |
| `frog_in_the_pan` | Da, Gurun & Warachka (2014), RFS 27(7): 2171-2218 | momentum scaled by how continuously (many small moves vs. a few jumps) it built up | higher is better |

## Decision

Add `intermediate_momentum_score`, `price_delay_score` and
`frog_in_the_pan_score` to `strategy_research.factor_scores` and wire
all three into `run_long_horizon_validation.py`'s
`_PRICE_FACTOR_CANDIDATES`, `compute_signal_ic_from_catalog.py` and
`verify_signal_ic_with_alphalens.py`, before any real result exists
(RULE 0.8). Each function's docstring carries the formula, source and
simplifications; the points a reviewer should know:

- **Formula verification.** Novy-Marx's "12 to 7 months prior" window
  and Da et al.'s `ID = sgn(PRET) * (%neg - %pos)` were checked via
  WebFetch (the latter against the authors' own working paper). Hou &
  Moskowitz's PDF host is not on this sandbox's network allowlist, so
  D1 uses the standard, widely reproduced definition
  (`1 - R2_restricted / R2_unrestricted`, weekly returns, 4 lags) and
  says so in its docstring rather than claiming a primary-source check.
- **Frog-in-the-pan as one score.** The paper uses a double sort. The
  score here is `PRET * -ID`, which matches the sign of all four
  corners of that sort (continuous winners best, continuous losers
  worst, discrete losers above discrete winners since the paper's
  high-ID momentum spread is negative). `-ID` alone was rejected during
  implementation because the synthetic test showed it ranks continuous
  losers as high as continuous winners (ID measures continuity, not
  direction). That was a construction error caught by a unit test on
  synthetic data, not a reaction to any real-data result.
- **Market proxy.** SPY, like every other market-co-movement factor
  here, instead of the CRSP value-weighted index.

## Preliminary real-data IC (research window only)

Computed with `compute_signal_ic_from_catalog.py` on the existing
`research-catalogs-v1` price catalog (RESEARCH_UNIVERSE, 87 symbols),
`--start 2011-01-01`, default `--end` = `earliest_locked_window_start()`
= 2020-08-28, so it never touches `TEST_1`/`TEST_2`. Default 2-month
step, 21-day forward horizon.

| factor | cross-sections | mean IC | IC IR | approx. t (IR x sqrt(n)) | positive IC share |
|---|---|---|---|---|---|
| `intermediate_momentum` | 57 | 0.0251 | 0.103 | 0.78 | 52.6% |
| `price_delay` | 58 | 0.0058 | 0.029 | 0.22 | 48.3% |
| `frog_in_the_pan` | 57 | 0.0269 | 0.113 | 0.86 | 54.4% |

All three point in the papers' direction, but none is statistically
distinguishable from zero on this sample. `price_delay` is closest to
nothing at all, which is not surprising: the paper's delay premium is
concentrated in small, neglected stocks, and this universe is 87 large
caps where almost all price discovery happens within the week.

This is a diagnostic, not validation: 87 surviving large caps, about
57 cross-sections, no transaction costs. The real test is the Stage 5
`price_only` walk-forward run (2000-01-01..2020-08-28) with PBO/DSR
across all candidates, which will include these three automatically.

## What this does NOT do

- Does not mark anything VALIDATED or change any live/paper strategy.
- Does not re-run `run_full_validation.yml`; the next Stage 5
  `price_only` dispatch picks the new candidates up.
- Adds three more candidates to the multiple-testing pool, which PBO/DSR
  already account for.

## Tests

9 new tests in `tests/strategy_research/test_factor_scores.py`
(`TestIntermediateMomentumScore`, `TestPriceDelayScore`,
`TestFrogInThePanScore`), each checking direction on synthetic data, an
exact formula value or bound, and `None` on insufficient history.
`test_run_long_horizon_validation_factor_wiring.py`'s `_EXPECTED_NAMES`
extended by the three names. Full suite run before merge.
