# ADR-0006: Backtest Broker Architecture & Execution Timing Convention

**Status:** Accepted
**Date:** 2026-08-24
**Deciders:** Claude Code (Phase 2 session), pending project owner review
**Related documents:** `PROJECT_MASTER_PLAN.md` §9.1-9.4,
`docs/specifications/PHASE-2-backtesting.md` §3, §6, `src/data_infra/repository.py`

---

## Context

`PROJECT_MASTER_PLAN.md` requires that Backtest, Paper, and (eventually)
Toss brokers all implement the same `Broker Interface` so core trading
logic is never duplicated per environment (master plan §9.3-9.4;
Phase 2 initialization instruction §5). Phase 2 is the first phase that
actually simulates order execution, so this ADR fixes both (a) the
broker abstraction shape and (b) a harder, easy-to-get-wrong question:
**when, exactly, does a simulated order fill, and at what price** —
since an unrealistic answer here (e.g., filling at a price the strategy
could not actually have traded at) directly inflates backtest
performance in a way that would not survive contact with real markets.

## Decision

### 1. Broker Interface shape (minimal, for Phase 2)

```python
class BrokerInterface(Protocol):
    def submit_order(self, order: Order) -> Fill | None: ...
```

`BacktestBroker` is the only implementation in Phase 2. It composes
`OrderSimulator` (validation) and `FillSimulator` (pricing), both
already described in the Phase 2 spec §6, and depends only on
`DataRepository`/`AsOfDataView` for price data — no Toss- or
paper-broker-specific code exists anywhere in this path. A future
`PaperBroker`/`TossBroker` (Phase 13+) implements the same
`BrokerInterface`; `BacktestEngine`'s use of the broker does not change
when the concrete implementation is swapped, mirroring how Phase 1's
`DataRepository` was designed to allow swapping `InMemoryDataRepository`
for a real backend without touching consumers (ADR-0002).

### 2. Execution timing: decide at `T`'s close, fill at `T+1`'s close

A `Strategy` decides using data available as of checkpoint `T` (the
close of trading day `T`, once that bar's `available_time` has been
reached). The resulting order is filled using **checkpoint `T+1`'s
close** as the reference price — not `T`'s own close, and not `T+1`'s
open.

## Reasoning

Three candidate execution conventions were evaluated:

**Option A — fill at `T`'s own close (same bar as the decision).**
Rejected. The strategy's decision is itself computed from `T`'s close;
filling at that same price assumes zero-latency, frictionless execution
exactly at the strategy's own signal price. This is a well-known
backtesting pitfall that systematically overstates performance,
especially for any strategy that rebalances frequently — and it is
precisely the kind of "실제 체결가격을 알 수 없는 경우 임의로 유리한
가격을 사용" the Phase 2 instruction warns against, even though the
price itself is not technically future data.

**Option B — fill at `T+1`'s open.** This is the most common convention
in production backtesting systems (decide at today's close, execute at
tomorrow's open) and was the initial candidate. It was **rejected for
Phase 2** on a data-model ground specific to this project: Phase 1's
`PriceBar` (`src/data_infra/models.py`) carries exactly one
`available_time` for the entire bar — open, high, low, close, and volume
together. There is no field representing "the opening print became
knowable earlier than the rest of the bar's data." Implementing Option B
faithfully would require either (a) querying `T+1`'s open before `T+1`'s
`available_time` is reached — which `DataRepository`'s own look-ahead
guard (ADR-0004) correctly refuses to serve, so the query would return
nothing — or (b) bypassing that guard specifically for the open field,
which would silently reintroduce a real leakage risk (assuming
intraday-open information is available exactly when it is, in fact,
not distinguished from the rest of the bar's availability in our data).
Adopting Option B properly is possible, but requires a Phase 1 data
model change (a distinct `open_available_time` or equivalent finer
timestamp) that this Phase 2 session does not have standing to decide
unilaterally — see the Consequences section and the session's
`DECISION REQUIRED` report.

**Option C — fill at `T+1`'s close (adopted).** Requires no change to
Phase 1's data model or guard behavior: `T+1`'s close only becomes
queryable once `T+1`'s own `available_time` is reached, which is exactly
when the simulation's forward pass reaches that checkpoint anyway. This
gives one full trading day of decision-to-execution latency (more
conservative/realistic than Option A, and arguably more conservative
than Option B, since it does not assume the entire next session's
opening liquidity is capturable), at the cost of not modeling
same-morning execution. Given the choice between "realistic but requires
data model changes now" and "slightly more conservative but requires
nothing beyond what Phase 1 already built and tested," Option C is
adopted for Phase 2, with Option B flagged as a candidate future
refinement (see `DECISION REQUIRED` in the Phase 2 session report).

## Alternatives Considered

- **A single combined `simulate_order()` function instead of a
  Broker Interface + OrderSimulator + FillSimulator split**: Rejected —
  would not satisfy `PROJECT_MASTER_PLAN.md`'s requirement that Backtest/
  Paper/Toss brokers share one interface; validation (can this order even
  be placed) and pricing (what does it fill at) are also different
  concerns worth keeping separately testable (Phase 2 spec §16, tests 3-4
  vs the order/cash tests are independent).
- **Resting/working orders that persist across multiple future
  checkpoints until filled**: Rejected for Phase 2 — no baseline strategy
  needs it, and it adds meaningful state-machine complexity
  (`PROJECT_MASTER_PLAN.md` §1.3). An unfilled remainder is simply not
  executed; the strategy re-evaluates at its next step. Revisit if a
  future strategy genuinely needs persistent limit orders.
- **Assuming `T+1`'s open is available at `T+1`'s `available_time` minus
  some fixed offset (e.g., "available at market open, roughly N hours
  before the bar's recorded `available_time`")**: Rejected — inventing an
  offset not grounded in Phase 1's actual data semantics would be
  guessing, which the master plan explicitly warns against for adjacent
  cases (e.g., §9.3 on Toss endpoints: "추측해서 만들지 않는다"). The same
  discipline applies here.

## Consequences

### Positive

- No changes to Phase 1 code were required; the execution timing
  convention is fully compatible with the existing look-ahead guard,
  requiring no exception or bypass.
- Every fill is provably attributable to a price that was only knowable
  strictly after the corresponding decision was made — verified
  mechanically by `BacktestIntegrityChecker`'s execution-timing check
  (Phase 2 spec §12), not just by this document's argument.
- The Broker Interface abstraction means Phase 13's real Toss adapter
  work starts from a stable, already-exercised interface shape.

### Negative / Trade-offs

- One full trading day of decision-to-execution latency is more
  conservative than many production backtests (which typically use
  next-open). This will tend to slightly understate a strategy's
  realizable performance relative to a next-open convention, particularly
  for strategies sensitive to short-horizon timing. This is an accepted,
  documented trade-off in favor of correctness over favorable-looking
  results, consistent with this phase's stated goal ("실전에서 믿을 수
  있는 검증 방법을 만드는 것" over "높은 백테스트 수익률").
- If the project later wants next-open execution, it requires a Phase 1
  data model extension (a distinct open-availability timestamp) — this
  is flagged for the project owner, not decided here.

## Status of Implementation at Time of This ADR

Implemented in `src/backtest/broker.py` (`BrokerInterface`,
`BacktestBroker`), `src/backtest/orders.py` (`OrderSimulator`), and
`src/backtest/fills.py` (`FillSimulator`), exercised by
`tests/backtest/test_execution_timing.py`. `tests/backtest/
test_orders_fills.py` (cited here originally) no longer exists --
`OrderSimulator`/`FillSimulator`/`BacktestBroker` coverage has since
been distributed across several other test files instead of living in
one dedicated file (e.g. `tests/backtest/test_integrity.py`, `tests/
backtest/test_contribution.py`, `tests/backtest/test_portfolio.py`,
`tests/backtest/test_corporate_actions.py` -- ADR-0115, found via a
dangling-file-citation sweep; not individually re-verified as "the"
successor file since coverage is genuinely distributed, not moved to
one place).
