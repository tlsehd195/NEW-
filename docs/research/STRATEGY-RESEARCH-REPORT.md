# Strategy Research Report (Phase 23)

See `docs/decisions/ADR-0029-strategy-research-framework.md` for the
design rationale behind everything summarized here. This document is the
instruction section 38 deliverable: an honest account of what was
researched, what data it ran against, and how each candidate is
classified -- explicitly never using the phrase "verified alpha" or
"proven alpha" anywhere below.

## DATA

- **Real provider access**: re-verified this session via the environment's
  egress proxy status (a direct check, not an assumption) --
  `api.tiingo.com`, `stooq.com`, and `openapi.tossinvest.com` all
  returned a 403 CONNECT rejection. **BLOCKED**, unchanged since Phase 20.
- **Real ingestion performed this session**: **NONE.** No real historical
  price series was fetched. `scripts/ingest_real_market_data.py` exists
  and is ready to run in an environment with real network access
  (instruction section 6's required fallback), but was not and could not
  be executed here.
- **Data period / symbol count actually evaluated**: N/A for real data.
  Pipeline-validation tests ran against a 5-symbol, ~3-year (783 trading
  day) **SYNTHETIC, closed-form deterministic fixture**
  (`tests/strategy_research/research_helpers.py`) -- explicitly labeled
  as such everywhere it appears, never presented as real market data.
- **Corporate action availability**: not evaluated this phase (no real
  data). Phase 20-22's existing corporate-action point-in-time safety is
  unchanged and unaffected by this phase's additions.
- **Benchmark availability**: unchanged from ADR-0026 -- SPY proxy,
  TOTAL_RETURN target, `BENCHMARK_UNAVAILABLE` remains the honest state
  whenever real SPY total-return data is absent. Not resolved this phase.
- **Limitations**: everything below is a statement about *pipeline
  correctness*, not about *real-world strategy performance*. No claim in
  this document should be read as evidence that any candidate would
  perform any particular way on real US equity data.

## STRATEGIES

For each candidate: hypothesis, parameters, and pipeline-validation
result (SYNTHETIC fixture only) -- never a real-performance claim.

### Buy & Hold (Phase 22 reference baseline, unmodified)

- **Role**: REFERENCE, not alpha. Unchanged this phase.
- **Real-data result**: none obtained this phase (unchanged from Phase 22).

### Long-Term Momentum (`strategy_research.long_term_momentum`)

- **Hypothesis**: cross-sectional trailing-return momentum, applied at
  low frequency (quarterly default) to match the project's long-term
  mandate.
- **Parameters**: `lookback_months` in {6,9,12,18}, `top_n`,
  `rebalance_months` in {1,3}. Default: 12-month lookback, quarterly
  rebalance, top 5.
- **Pipeline-validation result (SYNTHETIC fixture)**: correctly ranks a
  steadily trending-up synthetic series above a steadily trending-down
  one; rebalances at low frequency (fewer than 10 fills over an
  ~18-month synthetic window, versus ~370 available daily checkpoints);
  deterministic on replay. **No real-data CAGR/Sharpe/drawdown exists.**

### Trend + Volatility (`strategy_research.trend_volatility`)

- **Hypothesis**: an uptrending, lower-volatility name is more likely to
  continue trending favorably than a downtrending or high-volatility one.
- **Parameters**: `trend_lookback_months` in {6,9,12}, `vol_lookback_days`
  in {60,90,126}, `vol_threshold` in {0.25,0.35,0.45}. Default: 9-month
  trend lookback, 90-day vol lookback, 0.35 threshold, monthly rebalance.
- **Pipeline-validation result (SYNTHETIC fixture)**: correctly holds a
  trending-up/low-volatility synthetic name and correctly rejects both a
  trending-down name (fails trend filter) and a high-volatility flat
  name (fails volatility filter); correctly produces zero fills (not a
  fabricated fallback holding) when nothing in the universe qualifies.
  **No real-data CAGR/Sharpe/drawdown exists.**

### Risk-Controlled Momentum (`strategy_research.risk_controlled_momentum`)

- **Hypothesis**: inverse-volatility-weighting momentum's top selections,
  capped at a maximum per-position weight, retains most of the momentum
  signal while reducing concentration-driven drawdown risk versus plain
  equal-weight momentum.
- **Parameters**: shares `lookback_months` range with Long-Term Momentum;
  `vol_lookback_days` in {60,90,126}; `max_position_weight` in
  {0.15,0.20,0.30}. Default: 12-month lookback, quarterly rebalance,
  90-day vol lookback, 0.20 cap.
- **Pipeline-validation result (SYNTHETIC fixture)**: correctly caps
  every individual fill's notional against its weight limit; correctly
  allocates more weight to the lower-volatility of two qualifying
  trending names (inverse-volatility ordering verified directly).
  **No real-data CAGR/Sharpe/drawdown exists.**

## VALIDATION

- **Train / Validation / Test periods**: not applied to real data this
  phase (none exists). The splitting mechanism
  (`strategy_research.splits.build_chronological_split`) is implemented
  and tested against synthetic date ranges only -- chronological,
  non-overlapping, deterministic.
- **Walk-Forward status**: **DEFERRED — insufficient real historical
  data** (none obtained this session). The rolling-window generation
  *mechanism* (`generate_walk_forward_windows`) is implemented and
  tested, including its honest empty-window behavior when history is
  insufficient, but no real walk-forward *evaluation* was run against
  any candidate.
- **Overfitting / multiple-testing concerns**: four strategies now exist
  in this project (Buy & Hold + 3 new candidates), each with a
  documented-but-unsearched parameter range. `ResearchLog` exists to
  make this exposure auditable going forward
  (`parameter_combination_count()`), but no real-data selection was
  performed this phase to apply that log against.
- **Multiple testing count this session**: 3 new strategy candidates x 1
  default parameter combination each = 3 (no grid search was executed by
  any code in this package).

## CLASSIFICATION

| Strategy | Classification | Reason |
|---|---|---|
| Buy & Hold | REFERENCE (not classified via this scheme) | Phase 22's own reference baseline role, unchanged |
| Long-Term Momentum | **INCONCLUSIVE** | No real evaluation data this session (`has_real_evaluation_data=False`) |
| Trend + Volatility | **INCONCLUSIVE** | No real evaluation data this session |
| Risk-Controlled Momentum | **INCONCLUSIVE** | No real evaluation data this session |

No candidate is classified `PROMISING_CANDIDATE` or `REJECTED` this
phase. `strategy_research.classification.CandidateClassification` has no
`PROVEN_ALPHA`/`VERIFIED_ALPHA` member at all -- this is a structural
property of the enum, not a policy this document could override even if
it wanted to.

## WHAT WOULD CHANGE THIS

Running `scripts/ingest_real_market_data.py` in an environment with real
network access, for the 16-symbol universe over a multi-year window,
would let `strategy_research.runner.run_gross_and_net` produce a real
`CandidateEvaluation` per strategy, `ResearchLog` accumulate real
entries, and `classify_candidate` be called with
`has_real_evaluation_data=True` for the first time -- at which point a
genuine `PROMISING_CANDIDATE`/`REJECTED` classification becomes possible,
still never a "verified alpha" claim on its own, and still requiring the
full instruction section 28 criteria (survives costs, out-of-sample
result exists, consistent across periods, not single-symbol dependent,
not overly parameter-sensitive, reasonable turnover, acceptable
drawdown) to all hold before `PROMISING_CANDIDATE` is even reachable.

## Addendum -- first REAL-data run (Phase 24 follow-up, user-executed)

The user ran `scripts/ingest_real_market_data.py` against real Tiingo
data (`--universe PILOT_UNIVERSE`, 2023-01-02 to 2024-12-31, 8,032 bars,
107 corporate actions, real SPY dividend history) in their own
network-enabled environment (this session cannot reach real providers
-- see `MARKET-DATA-PROVIDER.md`), then ran
`scripts/run_first_real_strategy_evaluation.py` against it and shared
the console output back into this session. **This is REAL market data,
not synthetic** -- the first real performance numbers this project has
ever produced.

That first run also surfaced and led to fixing two real bugs
(`git log`, commits `954d32e`/`951473d` on
`claude/phase-24-real-data-expandable-universe`):
1. `scripts/ingest_real_market_data.py` never fetched corporate actions
   (splits/dividends), only price bars -- fixed by wiring
   `TiingoDataProvider.fetch_corporate_actions`/
   `normalize_corporate_actions` (Phase 20, previously unused by this
   script) into the ingestion flow.
2. `BuyAndHoldStrategy` (`src/backtest/strategy.py`, Phase 2) permanently
   gave up if its very first checkpoint had no data for any symbol --
   real 2023-01-02 is a market holiday (observed New Year's) that
   `data_infra.calendar.US_EQUITY`'s admittedly non-production-accurate
   holiday set doesn't know about, so the strategy's first real attempt
   found nothing and never tried again, producing a spurious 0%/0-trade
   result. Fixed with a regression test
   (`tests/backtest/test_buy_and_hold_late_data_availability.py`).

### Results (real data, 2023-01-02 to 2024-12-31, 15 tradeable symbols + real SPY TOTAL_RETURN benchmark)

| Strategy | Net cumulative return | Net Sharpe | Max drawdown | Trades | Excess return vs SPY |
|---|---|---|---|---|---|
| Buy & Hold | +151.95% | 1.06 | -49.38% | 15 | +93.75% |
| Long-Term Momentum | +143.37% | 0.93 | -49.86% | 18 | +85.17% |
| Trend + Volatility | +57.06% | 0.66 | -24.87% | 50 | -1.14% |
| Risk-Controlled Momentum | +127.56% | 0.87 | -46.70% | 19 | +69.36% |

**Honest interpretation, not a verdict**: 2023-2024 was an exceptional
concentrated bull market (this pilot universe includes NVDA, whose real
2024 stock performance was extraordinary). Simply holding everything
(Buy & Hold) outperformed every "smarter" candidate over this specific
window -- a real, useful finding in its own right (per instruction
section 30: "나쁜 전략을 정직하게 제거하는 것이 우선," and here it is the
more complex candidates, not Buy & Hold, that failed to add value this
window). Trend + Volatility's realized-volatility filter did cut max
drawdown roughly in half (-24.87% vs -49%+ for the others) at the cost
of giving up most of the upside -- a real risk/return tradeoff, not
noise.

**This single window does not change any classification.** All four
remain `INCONCLUSIVE` in the actual `ResearchLog` this run produced
(`strategy_research.run_first_real_strategy_evaluation`'s own explicit
design -- see that script's module docstring) -- one window, no
train/validation/test split, no walk-forward re-test, no
multi-period consistency check. A strategy beating (or losing to) Buy &
Hold in one specific 2-year bull market is not evidence it would do so
in a different regime. The natural next step, not yet done, is a
chronological train/validation/test split or walk-forward re-test over
a longer real history once more data is ingested.
