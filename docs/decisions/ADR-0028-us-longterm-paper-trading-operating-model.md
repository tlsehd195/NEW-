# ADR-0028: US Long-Term Paper Trading Operating Model (Phase 22)

**Status:** Accepted

## Context

Phase 21 closed out the Toss broker adapter's implementable surface
(`ADR-0027`); real Toss operational verification remains and will
remain blocked in this environment because no real credentials exist.
Phase 22's instruction accepts that constraint and asks that every
*other* part of the system be hardened toward "10,000,000 KRW virtual
capital can repeatedly run US-equity long-term Paper Trading on
real-market-data-shaped infrastructure" — explicitly not toward Live
readiness, and explicitly not by inventing a "profitable" strategy.

This ADR is the single documentation home the Phase 22 instruction
(section 36) asks for, covering eight decisions made this phase. Each
section states the decision, the alternatives actually weighed, and
what remains open.

## Decision 1 — Stooq as the second (fallback) market data provider

**Decision**: implement `StooqDataProvider` (`src/data_infra/providers/
stooq.py`) as a second `DataProvider`, composed with Tiingo via
`FallbackDataProvider` (`src/data_infra/providers/fallback.py`).

**Evidence tier**: Tier 2 (ADR-0025's own evidentiary discipline) — the
no-API-key CSV endpoint shape (`stooq.com/q/d/l/?s=<symbol>.us&i=d`)
comes from independent secondary documentation, not a Tier 1 official
API spec (Stooq publishes no formal API reference this session could
locate or verify network access to). Actual network reachability of
`stooq.com` from a production environment is **UNKNOWN**, exactly like
Tiingo's own status in ADR-0025 — this ADR does not claim otherwise.

**Alternatives considered**:
- Alpha Vantage / Financial Modeling Prep (ADR-0025's other Tier-2
  candidates) — rejected for the same reasons ADR-0025 already gave
  (stricter free-tier rate limits, less certain long-history coverage);
  no new evidence surfaced this phase to revisit that.
- No fallback at all (single-provider dependency) — rejected because
  the instruction explicitly asks for a documented fallback path, and
  a single point of failure is a worse Paper Trading experience even
  though nothing forces the choice technically.

**Limitation accepted, not hidden**: Stooq's CSV response carries no
corporate-action fields at all (no split factor, no dividend cash) —
`StooqDataProvider.normalize()` sets `adjusted_close=None` always, and
`metadata()["supports_corporate_actions"] = False`. It has no
`fetch_corporate_actions`/`normalize_corporate_actions` methods. A
symbol/date range served by Stooq (whether as primary or as fallback)
therefore has strictly less information than the same range served by
Tiingo — this is disclosed via provenance, never silently backfilled or
guessed.

**Fallback disclosure discipline**: `FallbackDataProvider.fetch()`
stamps each raw record with which provider actually answered
(`_answered_by`), and `normalize()` routes each record back through its
own answering provider's normalization — so `PriceBar.provenance.source`
always names the true origin. A caller can always tell whether a given
bar came from Tiingo or Stooq; the two providers disagreeing on the same
symbol/date is never silently arbitrated (today, disagreement simply
isn't checked across both — `FallbackDataProvider` only calls the
secondary when the primary raises, not to cross-validate on every call,
since a per-call double-fetch would double request volume against both
providers' free tiers for no operational gain in a fallback-not-
consensus design).

## Decision 2 — Paper Trading operating model: explicit-time runner, no daemon

**Decision**: `run_buy_and_hold_paper_session` (`src/broker/paper/
us_longterm_runner.py`) takes an explicit `buy_time: datetime` argument
and never reads wall-clock time anywhere in its body. It runs one
allocation pass and returns — no `while True` / polling loop is built
this phase.

**Rationale**: every other point-in-time-safe entry point in this
codebase (`data_infra.provider.IngestionRunner.run`,
`backtest.total_return.build_total_return_benchmark_points`) already
follows this shape; a runner that reads `datetime.now()` would be the
first wall-clock-dependent entry point in the trading path and would
break the reproducibility property Phase 22's instruction explicitly
requires (same input -> identical result). A real scheduler (cron,
a daemon, an event loop) is a legitimate future addition, but it is
orchestration *around* this function, not a change to the function
itself — deferred, not designed speculatively here.

## Decision 3 — Buy & Hold as the single REFERENCE PAPER STRATEGY

**Decision**: Buy & Hold (`run_buy_and_hold_paper_session`) is the one
baseline this phase implements and calls "baseline," never "alpha" or
"strategy" in isolation. It allocates the session's current cash
equally across the configured symbol universe at a single caller-
supplied `buy_time`, one MARKET BUY per symbol, and never trades again.

**Alternatives weighed** (instruction section 16's own criteria):

| Criterion | Buy & Hold | Simple Momentum | Rule-based (e.g. SMA crossover) |
|---|---|---|---|
| Turnover | Lowest possible (one trade per symbol, ever) | Recurring rebalances required | Recurring signal checks + trades |
| Understandability | Trivial — no parameters to justify | Requires a lookback window choice, itself a hidden parameter | Requires threshold/window choices |
| Reproducibility | Deterministic given `buy_time` + prices | Deterministic given full price history + params | Deterministic given full price history + params |
| Cost-model compatibility | One fill per symbol — cost/slippage applies cleanly, minimal compounding | Repeated fills compound cost/slippage effects, harder to reason about honestly at this stage | Same compounding concern as Momentum |
| Leakage-testability | Trivial to prove no lookahead (one static reference price at one static time) | Requires proving the lookback window itself never crosses `as_of_time` — more surface area for a leakage bug | Same surface-area concern as Momentum |
| Long-term-horizon fit | Directly matches "long-term investment" framing | Momentum is typically a shorter-horizon signal; repurposing it long-term is itself an unvalidated design choice | Depends entirely on chosen rule's horizon — another unvalidated choice |

**Why Buy & Hold wins on this system's actual current state**: every
other candidate requires a parameter (a lookback window, a threshold)
that this project has not backtested or validated for this pilot
universe — choosing one now would be exactly the "invent a strategy and
imply it works" the instruction (section 35) forbids. Buy & Hold needs
no such parameter. It is not claimed to outperform anything; it exists
so the full Paper Trading lineage (order construction, cost/slippage,
Journal, Monitoring, Performance Report) has *something* real to carry
end to end, and so any future rule-based or momentum candidate has an
honest, low-complexity baseline to be compared against once it is
actually researched (Walk-Forward/PBO deferral, `docs/research/
walk-forward-pbo-dsr.md`, is unchanged by this phase — no such candidate
exists yet).

**Cost/slippage reuse**: the runner constructs a real
`risk.models.RiskCheckedPosition` and calls the existing, unmodified
`broker.validation.build_validated_order` and
`broker.paper.session.PaperTradingSession`/`broker.pipeline.
submit_validated_order` — Phase 2's `TransactionCostModel`/
`SlippageModel` apply to every Buy & Hold fill exactly as they would to
any other order type. No cost is assumed to be zero.

## Decision 4 — Risk policy defaults adopted as real configuration values

**Decision**: `max_daily_loss = 0.02` (as a fraction, per
`LIVE-RISK-POLICY.md`'s Phase 20 proposal shape), `max_turnover = 2.0`,
`max_order_frequency_per_hour = 6` are recorded as this phase's
**INITIAL CONSERVATIVE SYSTEM DEFAULT** — more conservative than Phase
20's own proposal (`0.02` / `3.0` / `30`), per the instruction's
explicit direction this phase. See `LIVE-RISK-POLICY.md`'s Phase 22
section for the full numeric rationale; these values are not repeated
here to avoid two documents drifting out of sync. **These are still not
financial truth and still require human ratification before real Live
use** — nothing in code auto-applies them to a real account, and Live
activation remains independently blocked by the Toss capability gap
regardless.

## Decision 5 — None-semantics: Option B adopted for the two safety-gate-visible fields

**Decision**: `evaluate_safety_gate` (`src/broker/live/safety_gate.py`)
now treats `LiveTradingConfig.max_daily_loss is None` and
`LiveTradingConfig.max_order_frequency_per_hour is None` as
`SAFETY GATE FAILURE` conditions (`risk_limit_not_configured_max_daily_
loss`, `risk_limit_not_configured_max_order_frequency_per_hour`) —
Option B of the Phase 17-20 "None-semantics" DECISION REQUIRED, per the
instruction's explicit direction this phase. **Scope is deliberately
narrow**: only the two `LiveTradingConfig` fields the safety gate
already had visibility into. `RiskConfig.max_turnover` is a separate
config object the gate has no structural access to today (it lives on
the Risk Engine's config, not `LiveTradingConfig`) — extending the gate
to see it would be new plumbing, not a semantics flip, and is left
genuinely open (see `LIVE-RISK-POLICY.md`).

**Paper Trading is unaffected**: `evaluate_safety_gate` is a Live-only
function; nothing in `broker.paper.*` calls it, and this phase's Buy &
Hold runner does not either. Paper Trading was never required to
enforce this.

## Decision 6 — SPY TOTAL_RETURN benchmark: unchanged, limitations reaffirmed

No change to ADR-0026's decision this phase. Restated for completeness
per instruction section 36: SPY remains the S&P 500 proxy, `TOTAL_
RETURN` remains the target return type, and `BENCHMARK_UNAVAILABLE`
remains the honest result whenever real dividend data for the benchmark
period is not available — never silently computed as `PRICE_RETURN`
and presented as if it were the requested `TOTAL_RETURN`.

## Decision 7 — FX handling: USD-denominated Paper account, no fabricated rate

**Decision**: the Phase 22 Paper Trading capital is represented as
`us_longterm_config.PAPER_CAPITAL_USD = 10_000.0` — an explicitly-
labeled, round, order-of-magnitude USD stand-in for the user's stated
`10,000,000` KRW target, **not a currency conversion**. This is the
instruction's own explicitly-permitted alternative to fabricating an
FX rate (section 14: "USD-denominated Paper account를 별도로 지원하는
것도 허용한다"). `MARKET-DATA-FX-REFERENCE.md` is updated this phase to
record this choice as the path actually taken, alongside its existing,
unchanged "no rate recorded" status (still true — no real KRW/USD rate
was found accessible or verifiable this session).

**Why not a labeled reference-only rate instead**: the instruction
offered either path. A reference-only rate would still require sourcing
a real, dateable, citable KRW/USD figure — every FX data source domain
checked was unreachable from this environment (unchanged since Phase
20), so that path remains blocked on the same access constraint that
blocks Tiingo/Stooq/Toss verification. The USD-account path requires no
external fact at all and carries strictly less risk of a stale or
misattributed number being mistaken for something current.

## Decision 8 — Point-in-time safety: no regression, reaffirmed

No change to the Phase 20 corporate-action leak fix or the raw/adjusted
separation this phase. The new Stooq provider adds no corporate-action
data at all (Decision 1), so it cannot introduce a new leak surface of
that kind; `FallbackDataProvider` performs no time-shifting or
backfilling of its own. `tests/integration/
test_us_longterm_paper_trading_lineage.py` exercises the full
`IngestionRunner -> DuckDBDataRepository -> as_of query` path with real
`as_of_time` arguments end to end, over and above the existing Phase 20
regression tests, which remain unmodified and passing.

## Consequences

- The system can now run a full, deterministic, real-data-shaped Paper
  Trading session (ingest -> point-in-time retrieve -> Buy & Hold ->
  Journal -> Monitoring -> Performance Report -> restart) for the
  16-symbol US long-term universe, entirely in USD, entirely without
  touching Live activation, Toss real calls, or any fabricated data.
- Nothing in this ADR changes whether Live Trading can activate — that
  remains independently blocked by the Toss operational-verification
  gap (`TOSS-API-GAP-ANALYSIS.md`), unaffected by any decision here.
- Two genuinely open items remain, tracked in `LIVE-RISK-POLICY.md`
  rather than resolved here: `RiskConfig.max_turnover`'s None-semantics
  (Option A vs. B, still undecided, out of the safety gate's current
  visibility), and ratification of the three numeric risk defaults by a
  human financially responsible for any eventual real account.
