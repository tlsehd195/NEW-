# ADR-0091: Distribution Days added as a sixth Regime axis

**Status:** Accepted
**Session:** 36 (continued)

## Context

Second of the 5 items identified from comparing this project against
`dragon1086/prism-insight` (see ADR-0090's Context for the full
background), per the account owner's "전부 적용" instruction.
`prism-insight` uses IBD's "distribution day" count as a market-wide
correction-risk warning: a day where a major index declines on volume
higher than the prior day's signals institutional selling; 5+ such days
within a rolling window ("under pressure") or 7+ ("confirmed
correction") are IBD's own long-published thresholds.

This project already has a Market Regime layer (Phase 5,
`docs/specifications/PHASE-5-market-regime.md`) with 5 axes (Trend,
Volatility, Liquidity, Correlation, Stress), explicitly documented as
"an example classification scheme" rather than a closed set
(`regime.enums.RegimeAxis`'s own docstring, PROJECT_MASTER_PLAN.md
section 7.6: "최종 regime 모델은 실험을 통해 결정하며"). Distribution
Days is architecturally a sixth axis of the same kind, not a new
subsystem: like every existing axis, it needs only price+volume history
already flowing through `AsOfDataView`/`PricePoint`, and the layer's own
generic design (every consumer -- `RegimeRepository`,
`CompositeRegimeObservation`, `RegimeConditionedStrategy` -- operates on
`RegimeAxis` via a dict or `AXIS_STATE_ENUM` lookup, never a hardcoded
list of 5) meant adding it needed no consumer-side changes.

## Decision

Added `RegimeAxis.DISTRIBUTION` and `DistributionState`
(NORMAL/ELEVATED/HIGH/UNKNOWN, mirroring `StressState`'s own naming --
both are "how much selling pressure" classifications from different
evidence) to `regime/enums.py`, wired into `AXIS_STATE_ENUM`.

`regime.features.compute_distribution_days` (new function): counts days
within a trailing `config.distribution_window` (default 25 trading days,
IBD's own convention) where the daily return is `<=
config.distribution_decline_threshold` (default -0.2%, IBD's own
threshold) AND that day's volume exceeds the prior day's. `count >=
distribution_high_count` (default 7) -> HIGH, `>= distribution_warning_
count` (default 5) -> ELEVATED, else NORMAL. All four thresholds are
IBD's own long-published values, not fit to any data this project
holds, and live in `RegimeConfig` like every other axis's thresholds
(never hardcoded in `features.py`).

Needs both price and volume, so a subject with no volume at all (e.g. a
`BenchmarkPoint`-derived series) is honestly UNKNOWN -- the same gap
`compute_liquidity` already documents and handles identically. Wired
into `RegimeDetector.compute_composite` exactly like the other 5 axes:
a new `_lookback_days_for(RegimeAxis.DISTRIBUTION)` case and a new
`dist_obs` added to the `axes` dict. Deliberately NOT added to
`_composite_label`'s curated `(trend, volatility)` -> label table --
that table is documented as intentionally small (Phase 5 spec section
6: "가능한 상태 조합을 무한히 늘리지 않는다"), and Distribution is
available to any consumer directly via `composite.get(RegimeAxis.
DISTRIBUTION)` without needing a label-table entry.

Like every other axis, this is descriptive infrastructure, not a
trading signal wired into any strategy -- `RegimeConditionedStrategy`
(the one strategy that consumes Regime today) still only reads TREND,
unchanged by this ADR. Whether Distribution predicts anything for this
project's specific universe is untested and unclaimed here, consistent
with Phase 5 spec section 9's explicit "이것을 근거로 Regime이 alpha를
만든다고 주장하지 않는다."

## What this does NOT do

Does not run any real evaluation of whether Distribution correlates
with subsequent drawdowns or strategy performance in this project's
data -- no such test exists yet, and none is claimed. Does not touch
`_composite_label`, `RegimeConditionedStrategy`, or any of the other 5
axes' code. Does not implement any of the other 3 remaining
`prism-insight`-derived items (lookahead-bias audit tool, reentry
cooldown, shadow-evaluation harness -- tracked separately).

## Tests

`tests/regime/test_features.py::TestDistributionDays` (6 tests, hand-
constructed synthetic series): no declines at all -> NORMAL, count 0;
an alternating decline/recovery series with exactly 5 distribution-day
transitions -> ELEVATED; a longer version with exactly 7 -> HIGH; a
sharp decline NOT on higher volume than the prior day is correctly not
counted; no volume data at all -> UNKNOWN (mirrors `TestLiquidity`'s own
equivalent case); insufficient history -> UNKNOWN. Two pre-existing
tests that hardcoded the axis count as a literal `5`
(`tests/regime/test_detector_composite.py::TestAxisIndependence`,
`tests/storage/test_regime_repository.py::TestIdempotency`) were updated
to `len(RegimeAxis)` -- every other regime test continued to pass
unmodified because the layer's own design never hardcoded the axis
count elsewhere. Full suite re-run, all tests pass.
