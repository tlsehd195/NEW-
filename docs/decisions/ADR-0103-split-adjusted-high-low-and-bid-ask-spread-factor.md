# ADR-0103: Split-adjusted high/low infrastructure and the Bid-Ask Spread factor

**Status:** Accepted
**Session:** 36 (continued)

## Context

ADR-0102 explicitly deferred `bidaskhl_21d` (a Corwin & Schultz 2012
high-low bid-ask spread estimator, appearing in both JKP's own
documentation and `OpenSourceAP/CrossSection`'s predictor catalogue)
for two stacked reasons: the estimator's exact formula was not given
inline anywhere this project had access to, and this project's own
`PriceBar` model had no split-adjusted high/low fields, which the
estimator's own 2-day `gamma` term needs to stay correct across a stock
split.

The account owner asked to pursue both blockers ("1 2 실행"):

1. **The formula was found and cross-verified** (not fabricated from
   memory): a third-party Python reimplementation's raw source
   (`github.com/ioannisrpt/Corwin_Schultz_2012`) and an independent web
   search summary both gave the identical closed-form `beta`/`gamma`/
   `alpha`/spread equations. The account owner separately confirmed
   both the Corwin & Schultz (2012) and Penman, Richardson & Tuna
   (2007) papers themselves are paywalled and inaccessible -- but for
   this specific factor, the paper itself was never actually the
   remaining blocker once the formula was independently verified this
   way; the `netdebt_me` factor (Penman/Richardson/Tuna) remains
   deferred, since ITS blocker genuinely was needing the original
   paper's own nuanced conclusion.
2. **The split-adjusted high/low infrastructure gap was real and is now
   fixed** -- this ADR's main subject.

## Decision

### Infrastructure: `PriceBar.adjusted_high`/`.adjusted_low`

Added as two new `Optional[float] = None` fields on `PriceBar`, with the
identical "raw is truth, adjusted is a separate optional view, never
substituted, never fabricated" discipline `adjusted_close` already
established (Phase 1 spec §5.2, now extended to cover them explicitly).

- **`TiingoDataProvider`**: Tiingo's EOD response already carries
  `adjHigh`/`adjLow` fields alongside `adjClose` in the SAME response
  already fetched for every other field -- zero new network requests,
  simply two more already-present fields nothing had parsed before.
- **`StooqDataProvider`**: unchanged, `None` for both -- Stooq's free
  tier supplies raw prices only, the same honest gap `adjusted_close`
  already has there.
- **`LocalFileDataProvider`**: two new optional CSV columns, `adj_high`/
  `adj_low`, added to `_OPTIONAL_COLUMNS` alongside the existing
  `adj_close`, for the account owner's own external-preprocessing
  workflow (ADR-0034).
- **Storage (`storage/serialization.py`, `PRICE_BAR_COLUMNS`)**: both
  fields added to the row (de)serialization and the Parquet column
  list.
- **Storage backward-compatibility (`storage/data_repository.py`)**:
  every `read_parquet(...)` call over the price-bars directory now
  passes `union_by_name=true`. `PriceBar`'s column set has grown before
  (`vwap`/`trade_count`) and will again; a Parquet file written before a
  given column existed has a genuinely different Arrow schema (missing
  the column entirely, not NULL in it), which a plain multi-file
  `read_parquet(glob)` is not guaranteed to reconcile. `union_by_name=
  true` makes that reconciliation explicit and safe, so an account
  owner's already-ingested real data is never broken by this (or any
  future) additive schema change -- proven by a dedicated regression
  test that manually writes an old-schema Parquet file alongside a
  newly-written one and confirms both read back correctly together.
- **Data quality (`data_infra/quality.py`)**: `_check_non_finite_values`
  extended to cover the two new optional fields, same treatment as
  `adjusted_close`.

### Factor: `bid_ask_spread_score`

**Hypothesis** -- Amihud & Mendelson (1986, "Asset Pricing and the
Bid-Ask Spread," Journal of Financial Economics 17(2): 223-249): a wider
bid-ask spread (a real transaction cost) predicts HIGHER subsequent
returns. This project has no real bid/ask quote data, so the spread
itself is ESTIMATED via Corwin & Schultz (2012, "A Simple Way to
Estimate Bid-Ask Spreads from Daily High and Low Prices," The Journal
of Finance 67(2): 719-760) -- the same measurement-vs-anomaly citation
split `OpenSourceAP/CrossSection`'s own `BidAskSpread.py` predictor
uses.

**Construction**: for each pair of consecutive trading days, `beta =
ln(H_t/L_t)^2 + ln(H_{t-1}/L_{t-1})^2`, `gamma = ln(max(H_t,H_{t-1}) /
min(L_t,L_{t-1}))^2`, `const = 3 - 2*sqrt(2)`, `alpha = (sqrt(2*beta) -
sqrt(beta))/const - sqrt(gamma/const)`, daily spread `= max(0,
2*(e^alpha-1)/(1+e^alpha))`. Averaged over a trailing 21-trading-day
window, requiring at least 12 valid daily estimates (the same
minimum-observations threshold `OpenSourceAP/CrossSection`'s own
monthly aggregation documents). Uses `adjusted_high`/`adjusted_low`
exclusively -- never raw `high`/`low` -- and returns `None` if any bar
in the window lacks them, rather than mixing adjusted and raw price
scales within the same computation.

Score is the RAW average estimated spread (not negated), matching
`illiquidity_score`'s own precedent for a positively-priced risk
quantity.

**Wired in before any real result exists (RULE 0.8)**: into
`compute_signal_ic_from_catalog.py`'s `_PRICE_ONLY_SCORES`
(`--score bid_ask_spread`) and `run_long_horizon_validation.py`'s
`_PRICE_FACTOR_CANDIDATES` (the pool's 43rd candidate).

## What this does NOT do

Does not implement `netdebt_me` (Penman, Richardson & Tuna 2007) --
still genuinely blocked on the paper's own nuanced conditional
conclusion, paywalled and unread. Does not backfill `adjusted_high`/
`adjusted_low` for any bars already ingested before this session by the
account owner in their own environment -- those bars simply read back
with `None` for the two new fields (the same schema-evolution behavior
the regression test below proves is safe, not an error) until re-
ingested from a provider that supplies them.

## Tests

`tests/data/test_models.py` (2 new: defaults, independent overrides).
`tests/data_infra/test_tiingo_provider.py` (2 new: parses
`adjHigh`/`adjLow`, leaves `None` when absent).
`tests/data_infra/test_file_import_provider.py` (1 new: `adj_high`/
`adj_low` CSV columns).
`tests/data/test_quality.py` (3 new: NaN detection, missing-is-not-
flagged).
`tests/storage/test_data_repository_persistence.py::TestPriceBarSchemaEvolution`
(1 new: old-schema and new-schema Parquet files coexist via
`union_by_name=true`).
`tests/strategy_research/test_factor_scores.py::TestBidAskSpreadScore`
(6 new: computed value against a hand-verified constant-band case,
sign convention, raw-high/low-is-ignored, missing-adjusted-fields,
insufficient-observations, unknown-security).
`test_run_long_horizon_validation_factor_wiring.py`'s `_EXPECTED_NAMES`
extended to 35 names across 6 candidate tables. Full suite re-run: see
`PROJECT_STATUS.md` for the exact count.
