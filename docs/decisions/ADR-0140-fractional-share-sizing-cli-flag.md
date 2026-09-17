# ADR-0140: Expose `PositionSizingConfig.lot_size` as `--lot-size`

**Status:** Accepted
**Date:** 2026-09-17
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `src/risk/sizing.py` (unmodified -- the config
field this ADR exposes already existed), `src/orchestration/paper_strategies.py`

---

## Context

The account owner flagged a real gap while reviewing the reports this
session started from: Toss Securities (their own real target broker)
supports fractional-share purchases, but nothing in this project's own
Paper Trading path appeared to let a caller size a position in
anything but whole shares.

Investigating before writing any code (RULE 0.8) found the gap was
narrower than it looked: `risk.sizing.DeterministicPositionSizer.size()`
already computes `quantity = math.floor(raw_quantity / config.lot_size)
* config.lot_size` -- `PositionSizingConfig.lot_size` is already a
plain `float`, not hardcoded to `1`, so a caller passing `lot_size <
1.0` already produces a genuinely fractional quantity from this
formula alone. A repo-wide search for an `int(...)`-cast quantity
anywhere in the order/fill/accounting path (`ValidatedOrder.quantity`,
`Fill.quantity`, `Position.quantity`, the Toss adapter's own
`"quantity": str(order.quantity)` serialization) found none -- every
one of them is already a plain `float` throughout. The actual gap was
narrower and purely a wiring one: `orchestration.paper_strategies.
build_run_cycle_components` always constructed its own
`PositionSizingConfig()` inline, with no parameter letting any caller
reach `lot_size` at all, and `scripts/run_paper_trading_cycle.py` had
no flag to set it even if that parameter had existed.

## Decision -- thread a `sizing_config` parameter through, add `--lot-size`, default unchanged

`build_run_cycle_components` gained one new optional keyword parameter,
`sizing_config: Optional[PositionSizingConfig] = None`, defaulting to
`PositionSizingConfig()` (unchanged, `lot_size=1.0`) when omitted --
every existing caller (`run_multi_strategy_paper_trading_cycle.py`,
every existing test) is unaffected. `scripts/run_paper_trading_cycle.py`
gained a new `--lot-size` flag (default `1.0`), builds a
`PositionSizingConfig(lot_size=args.lot_size)`, and passes it through.
`--lot-size` is included in the run's own reproducibility checksum and
in the JSON report, matching the exact precedent `risk_config` already
established for `--max-sector-weight`/`--max-order-notional` (any input
that changes results must be in the checksum).

`scripts/run_multi_strategy_paper_trading_cycle.py` was NOT given the
same flag in this pass -- a deliberate, disclosed scope choice (this
ADR's own account-owner-raised gap was about the one script real
production traffic runs through), not an oversight; the new
`sizing_config` parameter is there for it to use whenever that becomes
needed.

## Consequences

### Positive

- A real, working path to fractional-share sizing exists now, end to
  end through Paper Trading's own order/fill/accounting path, with a
  real end-to-end test proving a genuinely fractional quantity results
  (not just that the flag is accepted).
- No new risk introduced to the default path: `--lot-size`'s own
  default (`1.0`) reproduces every existing behavior exactly, confirmed
  by a full suite re-run.

### Negative / Trade-offs

- This is Paper Trading only -- whether the account owner's own real
  Toss Securities account actually accepts a fractional quantity on a
  real Live order is a fact about Toss's own API, not verified here
  (Live trading remains on hold, unrelated to this ADR).
- `run_multi_strategy_paper_trading_cycle.py` does not yet expose this
  flag -- left for whenever multi-strategy fractional sizing is
  actually needed.

## Tests

`tests/orchestration/test_paper_strategies.py` (2 new tests: default
`lot_size` unchanged, a custom `sizing_config` is forwarded to the real
`position_sizer` instance). `tests/orchestration/test_run_paper_trading_cycle_cli.py::
TestFractionalShareSizing` (3 new tests: default `--lot-size` still
produces whole-share quantities, a fractional `--lot-size` produces a
real, non-integer held quantity in an end-to-end run, and a different
`--lot-size` changes the run's own reproducibility checksum). Full
suite re-run clean after these changes.

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed.
