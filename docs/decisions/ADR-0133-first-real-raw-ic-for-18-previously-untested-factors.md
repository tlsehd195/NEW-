# ADR-0133: First Real Raw IC for 18 Previously-Untested Factors

**Status:** Accepted
**Date:** 2026-09-13
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0043-jkp-cross-section-additions.md` and every ADR
it references for these factors' own construction decisions (ADR-0086, ADR-0089, ADR-0098,
ADR-0099, ADR-0101, ADR-0104, ADR-0105, ADR-0106, ADR-0107, ADR-0108, ADR-0109)

---

## Context

This project's 45-factor `strategy_research.factor_scores` module had, as
of this ADR, a real backlog of factors added across many past sessions
whose construction was decided BEFORE any result existed (RULE 0.8) but
had never actually been run against real data once real price/
fundamentals catalogs existed. With the account owner's 87-symbol
`RESEARCH_UNIVERSE` price and fundamentals data now fully collected
(via Google Colab, real Tiingo/SEC EDGAR data, this session), the
account owner ran both existing raw-IC CLI scripts (`compute_signal_ic_
from_catalog.py` for price-only factors, `compute_fundamentals_ic_
from_catalog.py` for fundamentals-based ones) for real, in parallel
with the ongoing insider-transaction collection (a second Colab tab,
read-only against the same Drive-hosted catalogs -- no conflict).

## Decision -- Record the real, raw results honestly; no screening or rejection based on this alone

Consistent with this project's own established practice (e.g. the real
`rs_rating` raw IC result earlier this session, "이 raw IC 하나만으로
후보를 제외하거나 구성을 수정하지 않고... 전체 파이프라인에서 최종
판단하도록 둠"), raw IC is a screening/sanity input only -- final
VALIDATED/CANDIDATE/rejected judgment is reserved for the full
walk-forward/PBO/DSR pipeline (`run_long_horizon_validation.py`), not
yet re-run this session. All 18 results below are from
`RESEARCH_UNIVERSE`, `2010-01-01` to `TEST_1.start` (2023-04-28, the
script's own default, never overridden), 80 rebalance dates, 60-day
forward-return horizon.

### Price-only factors (`compute_signal_ic_from_catalog.py`)

| factor | observations | mean_ic | ic_information_ratio | positive_ic_ratio |
|---|---|---|---|---|
| `bid_ask_spread` | 79 | -0.0069 | -0.0314 | 45.57% |
| `coskewness` | 79 | -0.0004 | -0.0023 | 53.16% |
| `downside_beta` | 78 | 0.0187 | 0.0549 | 50.00% |
| `high_volume_return_premium` | 78 | -0.0068 | -0.0489 | 47.44% |
| `idiosyncratic_skewness` | 79 | 0.0116 | 0.0748 | 54.43% |
| `residual_momentum` | 74 | -0.0003 | -0.0013 | 54.05% |
| `return_seasonality` | 67 | 0.0004 | 0.0022 | 44.78% |

### Fundamentals-based factors (`compute_fundamentals_ic_from_catalog.py`)

| factor | observations | mean_ic | ic_information_ratio | positive_ic_ratio |
|---|---|---|---|---|
| `rd_expenditure` | 79 | 0.0083 | 0.0424 | 53.16% |
| `net_stock_issuance` | 80 | 0.0225 | 0.1004 | 52.50% |
| `net_operating_assets` | 80 | 0.0161 | 0.0888 | 51.25% |
| `operating_leverage` | 80 | -0.0046 | -0.0129 | 48.75% |
| `abnormal_investment` | 73 | -0.0102 | -0.0505 | 50.68% |
| `cash_holdings` | 80 | 0.0166 | 0.0796 | 52.50% |
| `share_turnover` | 79 | -0.0069 | -0.0333 | 53.16% |
| `asset_turnover_change` | 80 | 0.0092 | 0.0542 | 53.75% |
| `industry_momentum` | 79 | -0.0256 | -0.0874 | 45.57% |
| `ohlson_o` | 80 | -0.0124 | -0.0612 | 55.00% |
| `merton_dd` | 79 | 0.0469 | 0.1594 | 51.90% |

## Observations (descriptive only, not a screening decision)

Every `mean_ic` magnitude is small (|IC| < 0.05) and every
`ic_information_ratio` magnitude is well under 1 -- consistent with
this project's own prior raw-IC results at this same single-window,
87-symbol scale (e.g. `rs_rating`'s own `-0.0053`/`-0.0202` earlier
this session), not a sign that any of these 18 is unusually strong or
unusually broken. `merton_dd` (0.0469) and `net_stock_issuance`
(0.0225) have the largest-magnitude mean ICs here; `industry_momentum`
(-0.0256) is the largest-magnitude negative. None of this ADR's own
analysis assigns pass/fail status -- that remains the walk-forward/PBO/
DSR pipeline's job, not a single raw-IC snapshot's.

## Consequences

### Positive

- Closes a real, long-standing gap: 18 factors this project had built
  and wired into the CLI (across many earlier ADRs) but never actually
  run against real data, now all have a first real observation.
- Demonstrates this session's Google Colab pipeline can support
  read-only analysis work (a second, independent Colab tab) running
  concurrently with an active write-heavy collection job (insider
  transactions) against the same Drive-hosted catalogs with zero
  conflict -- a real, useful pattern for future sessions.

### Negative / Trade-offs

- Still only 87 symbols (`RESEARCH_UNIVERSE_STAGE4`), a real,
  previously-discussed limitation for cross-sectional IC's statistical
  power and for representativeness of the small/mid-cap segment where
  several of these literature-based effects are documented to be
  strongest. Not addressed by this ADR.
- `insider_buying`, `short_interest`, `institutional_ownership_change`
  (the three factors needing the insider/short-interest/institutional
  DBs) are still not included here -- `insider_buying`'s own real
  collection was still in progress at the time of this ADR (ADR-0132);
  `short_interest`'s DB has never been populated; `institutional_
  ownership_change` has only a single real filer (Berkshire Hathaway,
  ADR-0131) rather than universe-scale coverage.

## Status of Implementation at Time of This ADR

No code changes -- this ADR is a pure real-data-results recording
against already-existing, already-tested CLI scripts and factor
implementations. Full walk-forward/PBO/DSR re-run (covering these 18
plus every other factor added since the last such run) remains a
pending follow-up, not yet started.
