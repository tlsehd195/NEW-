# ADR-0152: Encode regime axis observations into `DecisionSnapshot.features`

**Status:** Accepted
**Date:** 2026-09-17
**Deciders:** Claude Code (session continued)
**Related documents:** `docs/decisions/ADR-0141-wire-decision-snapshot-features.md`
(the immediately preceding fix, whose own "Negative / Trade-offs"
section named exactly this gap)

---

## Context

ADR-0141 wired `PredictionOutput`'s five numeric fields into
`DecisionSnapshot.features`, but explicitly disclosed a trade-off it
did not close: "regime axis observations (categorical, e.g.
`LiquidityState`) are not encoded into numeric features here; doing so
would need a real encoding scheme this ADR does not design, left for a
future session." `run_cycle` already computes a full
`CompositeRegimeObservation` per security per cycle (Trend, Volatility,
Liquidity, Correlation, Stress, Distribution) and discards everything
but its use in `decision_agent.decide`/`position_sizer.size` — none of
it reached the Trade Journal's own features for the Learning Engine to
train against.

## Decision — `_regime_features()`, value and state encoded independently, UNKNOWN never fabricated

New `orchestration.paper_runner._regime_features(regime:
CompositeRegimeObservation) -> Optional[dict]`, merged with the
existing `_prediction_features()` output via a new
`_decision_features(prediction, regime)` combiner, called at the same
`record_decision(features=...)` call site ADR-0141 already wired.

Each axis in `regime.axes` contributes two independent kinds of
feature, since `RegimeObservation.value` (numeric) and `.state`
(categorical) are independent facts — confirmed by reading
`regime.features.compute_volatility`, which can return a real `.value`
(the raw annualized vol estimate) while `.state` is still `UNKNOWN`
(insufficient percentile history to classify it):

- **`.value`**: included as `regime_<axis>_value` whenever not `None`
  — no new computation, the exact value `RegimeObservation` already
  carries.
- **`.state`**: one-hot encoded as `regime_<axis>_is_<state>` — one key
  per state that axis can REALLY take (from `regime.enums.
  AXIS_STATE_ENUM`, excluding `UNKNOWN` itself), `1.0` for the active
  state and `0.0` for every other real state of that SAME axis. The
  entire one-hot block for an axis is OMITTED when that axis's own
  state is `UNKNOWN` — an all-zero block would read downstream as
  "confidently observed none of these states," a different (false)
  claim from "this axis was never classified." This mirrors ADR-0141's
  own `None`-omission discipline for `_prediction_features`, applied
  here to a categorical field instead of a numeric one.

## Consequences

### Positive

- `LinearRegressionTrainer` (and any future trainer) now sees regime
  context alongside prediction context for every real Paper Trading
  decision — a strictly larger, more informative feature set, with the
  same never-fabricate guarantee ADR-0141 already established.
- The one-hot scheme is a drop-in for any future `RegimeAxis` this
  project adds (it reads `AXIS_STATE_ENUM` rather than hardcoding a
  state list per axis), and for any axis not yet observed for a given
  security/cycle (simply absent from `regime.axes`, contributing
  nothing — no special-casing needed).

### Negative / Trade-offs

- One-hot encoding widens the feature space per axis (up to 4 keys for
  Volatility) rather than a single ordinal number — deliberate: an
  ordinal encoding (e.g. `LOW=0, NORMAL=1, HIGH=2, EXTREME=3`) would
  assert a false linear-distance relationship between categories a
  linear model would silently exploit, which this project's own "no
  code path may claim results it cannot justify" standard rules out
  without evidence that distance is actually meaningful.
- Backtest's own `Strategy`/`OrderIntent.features` path (ADR-0048's
  original context) remains a separate, still-unwired execution path —
  out of scope here, same disclosed boundary ADR-0141 already stated.

## Tests

`tests/orchestration/test_paper_runner.py::TestDecisionSnapshotFeatures`
(+4 tests): a real (non-UNKNOWN) state one-hot-encodes correctly and
excludes an UNKNOWN axis entirely; `.value` can be present even when
`.state` is `UNKNOWN` (confirmed independently, not assumed); all-axes-
unknown-and-valueless returns `None` not `{}`; a real `run_cycle`
decision snapshot carries both prediction and regime keys together.

Full suite re-run clean: 3179 passed (up from 3175).

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed.
