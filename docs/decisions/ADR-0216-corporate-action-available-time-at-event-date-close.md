# ADR-0216: Corporate actions become available at their event-date close

**Status:** Accepted
**Date:** 2026-09-26
**Deciders:** account owner, Claude Code session

**Related documents:** `docs/decisions/ADR-0210` (13F backfill), PR #158
(`SplitAdjustedInstitutionalHoldingRepository`), `docs/decisions/ADR-0115`
(corporate actions applied before fills), `docs/decisions/ADR-0196` F-3
(`bar_available_time` 20:00 UTC convention). Supersedes the Session 36
"corporate action `available_time` is always `ingestion_time`" rule in
`tiingo.py`/`alphavantage.py`.

## Context

The 2026-09-26 full validation run
(`docs/research/reports/full-validation-20260926T151224Z.json`) reported
`institutional_split_adjustments_applied: 0`. The first guess was that
the `research-catalogs-v1` price catalog had no split events. That was
wrong. Opening the real catalog showed 34 SPLIT/REVERSE_SPLIT rows
(AAPL 2014-06-09 7:1, MA 2014 10:1, V 2015 4:1, NKE 2012/2015 2:1, and
more) and 5,429 DIVIDEND rows, **all stamped `available_time =
2026-09-11`**, the backfill's ingestion time.

`get_corporate_actions` drops anything with `available_time > as_of_time`,
so every historical as-of query saw none of them. The raw price bars of
the same days are stamped at their own session close
(`bar_available_time`), so they stayed visible. Backtests therefore saw
the post-split raw price drop without the split:

- A real AAPL buy-and-hold from 2014-05-01 to 2014-07-31 on this catalog
  reported a **-84.3% max drawdown** (the 7:1 split read as a loss).
  After the fix, the same run reports -4.1%.
- `BacktestEngine` never paid a dividend, and the SPY benchmark labeled
  `REAL_TOTAL_RETURN` was built from `spy_actions` fetched as of the run
  end (2020), so it was really price-only.
- The 13F split adjustment (PR #158) applied 0 splits.

So every walk-forward fold and held-out result computed from this catalog
before this ADR carries these distortions. That covers all 51 or more
candidates in the 2026-09-24/25/26 reports, not only
`institutional_ownership_change`.

## Decision

1. `data_infra.provider.corporate_action_available_time(event_date,
   ingestion_time) = min(ingestion_time, bar_available_time(event_date))`.
   Tiingo and Alpha Vantage split/dividend normalization use it.
   `ingestion_time` is unchanged.
2. `scripts/repair_corporate_action_available_time.py` applies the same
   rule to catalogs that already exist. It runs an in-place UPDATE of the
   `corporate_actions` table, limited to tiingo/alphavantage rows, and is
   idempotent. It is not an appended copy, because `CorporateActionApplier`
   dedups on `source_record_id` and a second copy would be applied twice.
3. `run_full_validation.yml` runs that repair right after downloading the
   price catalog, so the existing `research-catalogs-v1` release does not
   need to be re-uploaded.
4. `SplitAdjustedInstitutionalHoldingRepository` applies only share-count
   splits. Tiingo also reports spin-off price adjustments as a
   `splitFactor` (HON 1.011/1.032 in 2018, PFE 1.054 in 2020, and others).
   These change no one's share count. A ratio counts as a split only when
   it, or its inverse, is within 0.1% of p/q with q ≤ 4. The backtest
   engine still applies those factors to positions, since there they
   approximate the spun-off value the holder received.

### Why this is point-in-time safe

A split or ex-dividend is declared before its ex-date and is public by
that day's close. The raw bar for that same day, already visible at that
close, embeds its price effect. Seeing the action at the same moment as
its own price effect adds no information the replay did not already
have. Showing the effect while hiding the action is the inconsistency
that produced the -84%. Under prompt ingestion (live operation),
`ingestion_time` is earlier and wins, so an action is never visible
before it happened. The Session 36 concern ("a late-discovered action
visible before we knew") applies equally to the backdated price bars,
which this project already accepts for historical replay.
`tests/integration/test_market_data_point_in_time.py` still passes
unchanged: an as-of query before the split's own event date still sees
nothing.

## Consequences

- Every earlier validation report built on `research-catalogs-v1` needs
  to be re-read against a post-fix run. Results follow below.
- A newly ingested catalog is correct without the repair step. The step
  stays a no-op there.
- Out of scope: MERGER/SPIN_OFF actions as their own types (ADR-0196 F-5),
  and the 20:00 UTC DST gap (ADR-0196 F-3).

## Results (post-fix re-run)

_Filled in below after the re-run._
