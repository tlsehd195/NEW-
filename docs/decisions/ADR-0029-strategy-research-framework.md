# ADR-0029: Strategy Research Framework (Phase 23)

**Status:** Accepted

## Context

Phase 22 delivered one reference baseline (Buy & Hold) and a hardened
real-market-data-shaped Paper Trading path, explicitly deferring actual
strategy research ("do NOT invent a new profitable strategy" was Phase
22's own instruction). Phase 23's instruction asks for the opposite:
research, implement, and honestly evaluate three additional long-term US
equity strategy candidates through a real Backtest -> cost -> benchmark
-> out-of-sample pipeline, while continuing to forbid any premature
"verified alpha" claim.

This ADR records the design decisions behind `src/strategy_research/`
and the honest limits of what this phase could actually evaluate, given
this environment's unchanged network-access constraint.

## Decision 1 — Reuse `backtest.strategy.Strategy` / `BacktestEngine`, build no parallel pipeline

Every new candidate (`LongTermMomentumStrategy`, `TrendVolatilityStrategy`,
`RiskControlledMomentumStrategy`) implements the existing, unmodified
`backtest.strategy.Strategy` Protocol from Phase 2 and plugs directly
into `backtest.engine.BacktestEngine` -- the same engine
`BuyAndHoldStrategy`/`SimpleMomentumStrategy` already use. `strategy_research`
adds no new portfolio accounting, order simulator, fill simulator, cost
model, or benchmark engine. This was the only design considered
seriously: instruction section 21 explicitly requires reusing the
existing backtest engine, and Phase 2's `Strategy` Protocol was already
built generically enough ("a future ML-based strategy plugs in here
without BacktestEngine changing," Phase 2 spec section 5) to make a
parallel implementation both unnecessary and a direct violation of the
project's reuse discipline.

## Decision 2 — Three candidates, each with a stated hypothesis, each rebalanced by calendar time

`SimpleMomentumStrategy` (Phase 2) rebalances by decision-step count
(`rebalance_every`), appropriate for its short lookback but not for a
long-term, low-turnover mandate where "every N daily checkpoints" would
silently change trading frequency if the checkpoint schedule ever
changed. Every Phase 23 candidate instead tracks calendar-month elapsed
time (`strategy_research._dates.add_months`) for both signal lookback
and rebalance cadence:

- **`LongTermMomentumStrategy`**: cross-sectional trailing-return
  momentum (Jegadeesh & Titman 1993 in spirit), long-only, top-N
  equal-weight. Hypothesis, parameter range, and citation are recorded
  in the module's own docstring, not repeated here.
- **`TrendVolatilityStrategy`**: price-above-moving-average trend filter
  + a realized-volatility ceiling (Faber-style tactical allocation in
  spirit). Equal-weight among whatever currently qualifies; explicitly
  allowed to hold zero positions when nothing qualifies.
- **`RiskControlledMomentumStrategy`**: the same momentum ranking as
  candidate 1, but inverse-volatility-weighted with a capped maximum
  position weight local to the strategy's own allocation logic.

Every parameter range is documented as a discrete set in the owning
module (`LOOKBACK_MONTHS_RANGE`, `VOL_THRESHOLD_RANGE`, etc.) and
enforced by `__post_init__` validation -- not an unbounded continuous
range, and not brute-force searched by any code in this package
(instruction section 15's explicit warning about parameter search
creating a multiple-testing problem).

## Decision 3 — `RiskControlledMomentumStrategy.max_position_weight` is NOT `risk.config.RiskConfig`

Instruction section 17 explicitly warns against confusing a research
strategy's internal allocation logic with the production Risk Engine.
`RiskControlledMomentumStrategy` computes its own inverse-volatility
weights and caps them locally, entirely inside `generate_orders`; it
never imports, reads, or writes anything from `src/risk/`. The two
happen to solve a structurally similar problem (position concentration
control) under a similar name, which is exactly why this ADR states the
non-relationship explicitly rather than leaving it to be assumed.

## Decision 4 — Train/Validation/Test split and Walk-Forward window generation, kept as pure date-range functions

`strategy_research.splits` provides `build_chronological_split`
(TRAIN → VALIDATION → TEST, strictly time-ordered, never a random
shuffle -- a randomized split would leak future information into
"train" for a time series) and `generate_walk_forward_windows` (rolling
train/test window generator). Both are pure functions over dates only,
with no data-access dependency, so they are fully testable regardless of
this phase's real-data access status -- and both were in fact tested
that way (`tests/strategy_research/test_splits.py`, 9 tests, no fixture
data needed).

## Decision 5 — Walk-Forward EVALUATION deferred; the window-generation MECHANISM is not

Instruction section 25 asks this phase to "review" a minimal Walk-Forward
implementation if real data is sufficient, and to DEFER honestly
otherwise. This phase's real-data status (Decision 7 below) makes that
straightforward: **no real historical price series was obtainable this
session**, so no real walk-forward *evaluation* was run, and none is
claimed. What is NOT deferred is the *mechanism*: `generate_walk_forward_windows`
exists, is deterministic, is tested (including its honest empty-list
behavior when history is insufficient), and is ready to be pointed at
real data the moment `scripts/ingest_real_market_data.py` (Decision 8)
is run somewhere with network access. This mirrors the distinction
Phase 18's `docs/research/walk-forward-pbo-deflated-sharpe.md` already
draws between "the structural prerequisite exists" and "the technique
has actually been applied" -- that document's own trigger conditions
(9.1: "a trainer that claims genuine predictive skill," "multiple
candidates being compared for the same promotion decision") are a
model-evolution-level question, distinct from but analogous to this
phase's strategy-level version of the same gap.

## Decision 6 — PBO / Deflated Sharpe: still DEFER, no new trigger reached

Phase 23 introduces three new candidates, which does raise this
project's multiple-testing exposure (now 4 strategies total including
Buy & Hold, tracked honestly in `ResearchLog`). This is real, and is why
`ResearchLog.parameter_combination_count()` exists as a reportable
number rather than being left implicit. It does not, however, meet the
bar `walk-forward-pbo-deflated-sharpe.md` section 9.1 sets for actually
adopting PBO/Deflated Sharpe correction: that requires trial results to
correct against, and this phase produced no real-data trial results at
all (Decision 7) -- there is nothing yet to apply a selection-bias
correction to. DEFER stands, for the same underlying reason (real data
access), not because the multiple-testing count is considered
acceptable on its own.

## Decision 7 — Real market data: reachability re-verified, still BLOCKED

This session re-confirmed via the environment's egress proxy status
(`curl "$HTTPS_PROXY/__agentproxy/status"`, not a guess) that
`api.tiingo.com`, `stooq.com`, and `openapi.tossinvest.com` all still
return a 403 CONNECT rejection -- unchanged since Phase 20. No real
ingestion was possible this session. Every metric this phase's own test
suite computes is against the SYNTHETIC deterministic fixture in
`tests/strategy_research/research_helpers.py` (explicitly labeled, never
disguised as real data) -- these prove the pipeline is wired correctly
(no leakage, correct cost/benchmark integration, reproducibility,
persistence), never that any candidate performs well on real US equity
data. See `docs/research/STRATEGY-RESEARCH-REPORT.md` for the full,
honest classification of all four candidates as a result.

## Decision 8 — `scripts/ingest_real_market_data.py`: a real-network CLI, never run by this repository's own tests

Per instruction section 6's explicit fallback path ("실제 ingestion
단계는 외부 접근 가능 환경에서 재실행할 수 있도록 CLI/script/documentation을
제공한다"), this phase adds a standalone script wiring the existing,
unmodified `FallbackDataProvider`/`IngestionRunner`/`DuckDBDataRepository`/
`DataQualityFramework` together against real provider APIs, writing a
JSON reproducibility manifest. It reads its API key only from
`MARKET_DATA_API_KEY` (never a CLI argument, never written to a file),
never reads wall-clock time (the ingestion `end` date is a required CLI
argument), and is excluded from this repository's automated test
boundary by construction -- no test file in this repository imports it.

## Consequences

- The system now has three additional, deterministic, leakage-safe,
  cost-aware long-term strategy candidates connectable to the same
  Backtest → Paper Trading path Phase 22 already proved end-to-end, with
  no duplicate accounting/risk/benchmark logic introduced.
- No candidate is classified `PROMISING_CANDIDATE` or `REJECTED` this
  phase -- `CandidateClassification` structurally has no
  `PROVEN_ALPHA`/`VERIFIED_ALPHA` member, and `classify_candidate`
  forces `INCONCLUSIVE` whenever `has_real_evaluation_data=False`
  (which is every evaluation this phase actually ran).
- Real strategy evaluation, walk-forward evaluation, and PBO/DSR
  adoption all remain blocked on the same, single, already-known
  constraint: real market-data network access from this environment.
  `scripts/ingest_real_market_data.py` is the concrete path to unblock
  all three, the moment that constraint lifts.
