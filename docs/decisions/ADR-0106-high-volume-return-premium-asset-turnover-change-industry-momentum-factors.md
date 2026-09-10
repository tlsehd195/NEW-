# ADR-0106: High-Volume Return Premium, Asset Turnover Change and Industry Momentum factors

**Status:** Accepted
**Session:** 36 (continued)

## Context

The account owner asked to keep expanding the factor pool as broadly as
possible ("가능한 많이 전략을 더 찾아봐"), continuing directly from
ADR-0105. Three more well-known, single-paper-cited anomalies were
verified via WebSearch (citation, exact finding, and predicted sign)
before any construction was written, per RULE 0.8, all computable from
data this project already ingests or one new small, project-owned
public accessor (no new external data acquisition):

1. **Gervais, Kaniel & Mingelgrin (2001), "The High-Volume Return
   Premium," The Journal of Finance 56(3): 877-919** -- stocks with
   unusually high recent trading volume (relative to their own normal
   baseline) tend to appreciate over the following month.
2. **Fairfield & Yohn (2001), "Using Asset Turnover and Profit Margin to
   Forecast Changes in Profitability," Review of Accounting Studies 6:
   371-385, and Soliman (2008), "The Use of DuPont Analysis by Market
   Participants," The Accounting Review 83(3): 823-853** -- a
   year-over-year increase in asset turnover (Sales/Assets) predicts
   higher subsequent profitability, and Soliman finds the market only
   partially prices this in, leaving predictable abnormal returns in
   the same direction.
3. **Moskowitz & Grinblatt (1999), "Do Industries Explain Momentum?"
   The Journal of Finance 54(4): 1249-1290** -- the past return of a
   security's own industry group predicts its future return, and
   explains much of individual-stock momentum's own profitability.

## Decision

**`high_volume_return_premium_score`** (price-only,
`(security_id, as_of_time, data: AsOfDataView, recent_days=5, baseline_days=50)`):
`average_volume(recent_days) / average_volume(baseline_days immediately
before) - 1`, RAW (not negated). A fourth independent volume/liquidity
proxy alongside `illiquidity_score`, `bid_ask_spread_score` and
`share_turnover_score` -- about a RECENT CHANGE in a security's own
volume relative to its own baseline, not price impact, range, or a
turnover level.

**`asset_turnover_change_score`** (fundamentals-only,
`(security_id, as_of_time, repository)`): `current FY (Revenues/Assets)
- prior FY (Revenues/Assets)`, RAW. Uses `Revenues`/`Assets`, both
already ingested for other factors. Structurally similar to `sue_score`/
`sloan_accruals_score` (a fundamental-momentum/under-reaction story),
applied to a DuPont-derived signal instead.

**`industry_momentum_score`** (universe-level,
`(security_ids, as_of_time, fundamentals_repository, price_repository, lookback_days=126)`):
every security's score is its own industry's equal-weighted average
trailing return (industry from `data_infra.universe.get_sector`, SEC
EDGAR SIC text, ADR-0058), RAW. A NEW small public accessor,
`get_sector(symbol) -> Optional[str]`, was added to `data_infra/
universe.py` as a thin wrapper around the existing `_real_symbol_
metadata(symbol).sector` -- reaching into that underscore-prefixed,
module-private function directly from `factor_scores.py` would have
been a layering violation; this is the first factor in this module
needing any sector/industry classification at all. A security with no
confirmed sector, or whose industry has fewer than 2 members with a
computable return, is excluded (never a fabricated industry group of
one).

**Wired in before any real result exists (RULE 0.8)**:
`high_volume_return_premium` added to `_PRICE_ONLY_SCORES`/
`_PRICE_FACTOR_CANDIDATES` (needs zero new plumbing); `asset_turnover_
change` added to `_SCORES`/`_FUNDAMENTALS_FACTOR_CANDIDATES` (identical
shape to `net_stock_issuance_score`); `industry_momentum` added to
`_UNIVERSE_SCORES`/`_UNIVERSE_FACTOR_CANDIDATES` (identical call shape
to `quality_minus_junk_score`/`value_composite_score`/`combined_factor_
score`, `fundamentals_repository` accepted but unused). `_EXPECTED_
NAMES` extended from 39 to 42.

## What this does NOT do

Does not implement Gervais-Kaniel-Mingelgrin's own more elaborate
standardized-unexpected-volume regression model -- uses a simple
ratio-to-prior-baseline instead, the same "deliberate simplification"
discipline `low_beta_score`/`idiosyncratic_volatility_score` already
apply to their own literature. Does not value-weight industry
portfolios or exclude a security from its own industry's average the
way Moskowitz & Grinblatt's own construction does -- equal-weights and
includes every same-industry member, a simplification this project's
comparatively small universe makes acceptable (every included return is
already fully realized as of `as_of_time`, so this is not a look-ahead
violation). Does not attempt Ohlson (1980)'s O-Score, Mohanram (2005)'s
G-Score, or a Kaplan-Zingales/Whited-Wu financial-constraints index --
all three need either external macro data this project has no access
to, or a specific coefficient set this session could not verify from an
accessible primary source, and guessing either would violate this
project's "never fabricate provider capabilities/coefficients"
discipline.

## Tests

12 new tests in `tests/strategy_research/test_factor_scores.py`
(`TestHighVolumeReturnPremiumScore` 3, `TestAssetTurnoverChangeScore` 5,
`TestIndustryMomentumScore` 4), 2 new tests in `tests/data_infra/
test_universe.py` (`TestGetSector`). `test_run_long_horizon_validation_
factor_wiring.py`'s `_EXPECTED_NAMES` extended to 42 names across the
same 7 candidate tables. Full suite re-run: 2699 passed (2685
pre-existing + 14 new).
