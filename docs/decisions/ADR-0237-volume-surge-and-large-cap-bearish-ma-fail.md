# ADR-0237: Volume surge/price absorption and large-cap bearish MA candidates: screening FAIL

**Status:** Accepted (done 2026-10-02: both candidates FAIL in the open-window screen; no held-out window spent)
**Date:** 2026-10-08
**Deciders:** account owner (two ideas proposed in project chat, 2026-10-02), Claude Code session

## Context

The account owner proposed two new price-only candidate ideas for the open
research window (2000-01-01..2010-07-29, price-only; ADR-0230 locked
TEST_5 and left this as the remaining open range):

1. **거래량 급증 + 가격 둔감** ("volume surge, muted price move"): buy
   names where recent average volume is >=3x its own 60-day baseline
   while price has moved <3%. Checked against existing candidates:
   distinct from `high_volume_return_premium_score` (Gervais, Kaniel &
   Mingelgrin 2001 — that factor rewards a volume spike *combined with*
   the resulting return, not a muted one) and from `price_delay_score`
   (Hou & Moskowitz 2005 — delay in reaction to market-wide information,
   not a volume/price-impact ratio for a single name). Grounded in Kyle
   (1985) (informed traders size orders to minimize price impact) and
   Llorente, Michaely, Saar & Wang (2002) (volume-return dynamics
   distinguish informed accumulation from noise trading).
2. **대형주 역배열** ("large-cap names in bearish MA alignment"): buy the
   highest-(proxy-)market-cap names whose 5/20/60-day moving averages are
   in strict bearish order (short < mid < long). Market cap is not
   available before 2010 (shares-outstanding data starts then), so
   average dollar volume over the 60-day window is used as the size
   proxy instead, with that limitation stated in the docstring. Checked
   against existing candidates: distinct from momentum and
   `low_beta`/`betting_against_correlation`. The honest caveat, disclosed
   up front: Brock, Lakonishok & LeBaron (1992) tested MA-crossover rules
   on this exact kind of signal and found trend-*following* (buying the
   golden cross) beat fading the dead cross — the opposite direction of
   this hypothesis — and Zarowin (1990) found reversal effects
   concentrated in small firms, arguing against a large-cap-specific
   version. The candidate was still screened as proposed, with these
   caveats recorded rather than silently dropped.

Both were implemented as single-security `PriceFactorFn`s (not
`UniverseScoreFn`) so they run under `price_only=true`
(`_UNIVERSE_FACTOR_CANDIDATES` and friends are gated behind
`fundamentals_repository is not None` and would not run in this window).
Thresholds and MA periods were fixed before any result was seen (RULE
0.8): volume ratio >=3.0, price-change threshold 0.03, MA periods 5/20/60.

## Decision

Add both as new entries in `_PRICE_FACTOR_CANDIDATES`
(`scripts/run_long_horizon_validation.py`):
`volume_surge_price_absorption` (`factor_scores.volume_surge_price_absorption_score`)
and `large_cap_bearish_ma` (`factor_scores.large_cap_bearish_ma_score`).
Screen them together with all existing price-only candidates in one
combined run (point-in-time S&P 500, release
`research-price-catalog-sp500-pit-2000`, 2000-01-01..2010-07-29,
`final_exam=false`), per the project's batching rule — one pipeline run
for both rather than two.

A candidate only proceeds toward a held-out TEST if it clears the
fold-consistency bar (positive-return folds >=60% across >=2 distinct
regimes) **and** PBO < 0.5 **and** DSR >= 0.95.

## Consequences

- If neither clears the bar, no held-out TEST window is spent and no
  promotion to the unseen-names exam happens.
- Tests: `tests/strategy_research/test_factor_scores.py::TestVolumeSurgePriceAbsorptionScore`,
  `::TestLargeCapBearishMaScore`.

## Result (2026-10-02, run 37018917148,
`docs/research/reports/full-validation-20261002T151747Z.json`)

- **volume_surge_price_absorption**: FAIL. Did not clear the
  fold-consistency bar — 57% positive folds (27/47), 3 regimes
  (`BULL`: 27, `BEAR`: 18, `NEUTRAL`: 2), below the required 60%. PBO/DSR
  were not meaningfully reached. Walk-forward median net cumret +1.62%.
- **large_cap_bearish_ma**: FAIL. Cleared the fold-consistency bar (68%,
  32/47 positive folds, same 3 regimes) but failed the robustness gate:
  PBO 0.53 (must be < 0.5), DSR 0.10 (must be >= 0.95). Walk-forward
  median net cumret +3.01%. Consistent with the Brock-Lakonishok-LeBaron
  (1992) caveat disclosed at pre-registration — fading a bearish MA
  alignment in large caps does not hold up as real alpha here.
- No held-out TEST window was spent; TEST-1 and TEST-2 unseen-names exams
  remain unused. The open research window stays 2000-01-01..2010-07-29.
