# ADR-0149: Pending-order TTL/auto-cancel and VolumeScaledSlippageModel as the Paper Trading default

**Status:** Accepted
**Date:** 2026-09-17
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0137-wire-advance-simulation-into-run-cycle.md`
(the retry wiring this ADR completes), `docs/decisions/ADR-0148` (the
immediately preceding fix batch), `src/backtest/costs.py` (ADR-0007,
where `VolumeScaledSlippageModel` was already implemented)

---

## Context

A "Paper Trading 원리와 기능 성능 평가" (100-point evaluation) report,
uploaded earlier this session, scored this subsystem 79.5/100 and named
three "운영 배선·완결성" gaps under "구현됐는데 마지막 배선이 없는 기능":
(a) `advance_simulation` never called in production (closed by
ADR-0137), (b) the performance report never wired into the daily cycle
(closed by ADR-0136), and (c) two items ADR-0137 did NOT close:

1. **No TTL/expiry for a stuck order.** ADR-0137 made a still-open order
   retry forever via `advance_simulation`, but an order whose security
   permanently loses liquidity (or leaves the universe) now retries
   forever with no way to give up — a real zombie-order risk, worse
   than before ADR-0137 in one sense: it now consumes a real
   `_attempt_fill` call, and the participation cap it competes for,
   every single cycle, indefinitely.
2. **`VolumeScaledSlippageModel` implemented but never used.**
   `backtest.costs.VolumeScaledSlippageModel` (ADR-0007) already models
   slippage that scales with an order's own participation rate in the
   execution bar, but `PaperTradingConfig.slippage_model()` hardcoded
   `FixedBpsSlippageModel` regardless — every Paper Trading fill got
   the same flat slippage whether it consumed 1% or 100% of that bar's
   liquidity, understating the real cost of a large/illiquid fill
   relative to the same `max_participation` cap the fill simulator
   itself enforces.

## Decision

**TTL:** `PaperTradingConfig.pending_order_ttl_days: Optional[int] =
None` (new field, opt-in). `PaperBrokerAdapter.advance_simulation`
checks it before attempting a fill: if an order's age (`as_of -
record.requested_at`, its ORIGINAL submission time, never reset by a
partial fill) is at least `pending_order_ttl_days`, it is cancelled via
the same path `_cancelled`/`BrokerOrderStatus.CANCELED` `cancel_order`
already produces — one cancellation vocabulary, not two. `None` (the
default) preserves ADR-0137's exact behavior: no TTL, indefinite retry.
Exposed as `--pending-order-ttl-days` on both `run_paper_trading_cycle.py`
and `run_multi_strategy_paper_trading_cycle.py`, threaded into each
run's own reproducibility checksum alongside `--lot-size`.

Deliberately opt-in, not a new default: "how long is too long before
giving up" is a real risk-policy decision this config should not make
silently on a caller's behalf, unlike ADR-0137's retry wiring (which
was purely additive — nothing it does was reachable before, so there
was no existing behavior to preserve either way) or ADR-0136's report
wiring (a pure read, no behavior change at all).

**Slippage:** `PaperTradingConfig.slippage_model()` now returns
`VolumeScaledSlippageModel(base_bps=self.slippage_bps,
impact_coefficient_bps=self.slippage_impact_coefficient_bps)` instead
of `FixedBpsSlippageModel(bps=self.slippage_bps)`. New field
`slippage_impact_coefficient_bps: float = 100.0` (matching
`VolumeScaledSlippageModel`'s own default) is the extra bps charged at
100% bar participation; `slippage_bps` keeps its existing meaning (the
flat rate at zero participation), so an existing `slippage_bps`
override is unaffected in what it represents. Unlike the TTL, this IS
changed as a new unconditional default: no test in this repository
asserted an exact slippage value (only `> 0`/relative comparisons,
confirmed by direct grep before changing this), so nothing already
depended on the flat-rate behavior, and the flat model was never a
deliberate choice recorded in any ADR — it was simply what `config.py`
happened to hardcode before `VolumeScaledSlippageModel` existed.

## Consequences

### Positive

- A Paper Trading order that genuinely cannot fill (delisted security,
  permanently illiquid) can now be given a real, operator-chosen
  expiry instead of silently consuming a fill attempt and a share of
  the participation cap every cycle forever.
- Every Paper Trading fill's slippage now reflects how much of that
  bar's own liquidity it actually consumed, closing the gap between
  the participation cap the fill simulator enforces and the cost model
  that's supposed to price the risk of hitting that cap.

### Negative / Trade-offs

- TTL tracking is not restart-durable in the same sense fills are:
  `record.requested_at` (the basis for the age check) is itself durably
  persisted (`PaperOrderRecord`, unchanged), so TTL correctness across
  a restart is unaffected — this is a straightforward consequence of
  reusing already-durable state, not a new gap.
- Paper Trading fill prices will now differ slightly from before this
  change for any fill whose participation rate is meaningfully above
  zero (previously flat 5bps; now 5bps + up to 100bps more at full
  participation) — an intentional, more realistic change, not a
  regression, but worth noting for anyone diffing historical vs. new
  report numbers.

## Tests

`tests/broker/paper/test_paper_adapter.py::TestPendingOrderTTL` (4 new
tests): TTL `None` retries forever, an order older than its TTL is
cancelled instead of retried, an order younger than its TTL still
retries normally, a already-`FILLED` order is never touched by TTL.

`tests/broker/paper/test_paper_config.py::TestSlippageModel` (3 new
tests) + 2 new validation tests (`slippage_impact_coefficient_bps`
negative rejection, `pending_order_ttl_days` positive-if-set + defaults
to disabled).

`tests/orchestration/test_run_paper_trading_cycle_cli.py::
TestPendingOrderTTLFlag` (2 new tests): flag defaults to `None` in the
report JSON, and threads through when set.

Full suite re-run clean: 3167 passed (up from 3155 before this ADR).

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed.
