# Strategy Validation Report (Phase 25)

See `docs/decisions/ADR-0031-long-horizon-walk-forward-validation.md`
for the design rationale behind everything summarized here. This
document is the instruction section 35 deliverable: an honest account
of what this phase's chronological Train/Validation/Test + Walk-Forward
infrastructure actually validated, against what data, and what it did
not. Explicitly never using the phrase "verified alpha," "proven
alpha," "validated strategy," or "production ready" anywhere below --
see `docs/research/STRATEGY-RESEARCH-REPORT.md` for the equivalent
Phase 23/24 discipline this document continues.

## 1. Data source

Real market data: Tiingo primary / Stooq fallback
(`src/data_infra/providers/tiingo.py`, `src/data_infra/providers/stooq.py`,
Phase 20/22, unmodified this phase), via
`data_infra.providers.fallback.FallbackDataProvider`. Ingested through
`scripts/ingest_real_market_data.py` (Phase 23/24). No new data
provider, ingestion path, or corporate-action source was added this
phase.

## 2. Data period

Real data actually ingested (Phase 24 follow-up, user-executed, from
this project's own network-enabled Codespaces session, not from this
sandboxed session): **2023-01-02 to 2024-12-31** (~2 years), 15 tradeable
symbols + SPY, 8,032 price bars, 107 corporate actions. This remains the
only real historical window this project has ever obtained -- unchanged
since the interactive session recorded in
`STRATEGY-RESEARCH-REPORT.md`'s "Addendum" section. This sandboxed
session has **no** real data file locally (`data/` is empty and
gitignored -- confirmed this session) and cannot ingest more (egress
still blocked, re-confirmed below).

## 3. Universe

`PILOT_UNIVERSE_V1` (`src/data_infra/universe.py`, Phase 24, unmodified):
AAPL, MSFT, NVDA, AMZN, GOOGL, META, AVGO, TSLA, JPM, V, MA, COST, WMT,
JNJ, XOM (15 symbols). No universe expansion this phase -- Phase 24's
own reasoning (provider request/rate limits remain UNKNOWN for both
Tiingo and Stooq) is unchanged and still applies.

## 4. Benchmark

SPY, TOTAL_RETURN construction (`backtest.total_return.build_total_return_benchmark_points`,
Phase 20, unmodified), built from real SPY bars + corporate actions
whenever both are present in the ingested catalog; `BENCHMARK_UNAVAILABLE`
otherwise (ADR-0026, unchanged). `scripts/run_long_horizon_validation.py`
builds this once, from the full ingested window, before any fold or
held-out-test evaluation runs.

## 5. Corporate action handling

Unchanged from Phase 20/24: splits and dividends are ingested and
applied through the existing point-in-time-safe adjustment machinery
(`data_infra` corporate-action normalization, `backtest.asof.AsOfDataView`).
`tests/strategy_research/test_walk_forward_evaluation.py`'s
`TestCorporateActionAvailability` category (this phase, synthetic
fixture) confirms a walk-forward fold whose TEST window contains a real
split/dividend event still runs to completion through this same,
unmodified path -- proving `run_walk_forward_evaluation` adds no bypass
around corporate-action handling, not that any particular real
adjustment was exercised this phase (the real 2023-2024 ingestion's own
107 corporate actions were already covered by Phase 24's own test
coverage).

## 6. Survivorship limitations

Unchanged from ADR-0030: `PILOT_UNIVERSE_V1` is today's actual
large-cap composition, not a point-in-time-correct historical
constituent list. A symbol that would have been delisted, merged, or
removed from any real index during 2023-2024 is not modeled as such --
every symbol in the universe is assumed continuously tradeable across
the whole ingested window. This is an existing, documented limitation
this phase does not resolve.

## 7. Train / Validation / Test methodology

`strategy_research.splits.build_chronological_split` (Phase 23,
unmodified) divides the ingested window chronologically -- never
randomly -- into TRAIN (default 60%) / VALIDATION (default 20%) / TEST
(remaining ~20%), each window strictly ordered and non-overlapping
(`TrainValidationTestSplit.__post_init__` raises otherwise;
`tests/strategy_research/test_evidence.py::TestChronologicalSplitReservesTestExactlyOnce`
re-verifies this at this phase's own usage boundary). `scripts/run_long_horizon_validation.py`
runs walk-forward folds across TRAIN+VALIDATION only, and evaluates the
TEST window exactly once, as a single `held_out_test` result, never
re-opened afterward (instruction section 24's "TEST 구간은 마지막에 딱
한 번만 사용한다").

## 8. Walk-Forward methodology

`src/strategy_research/walk_forward_evaluation.py` (this phase):
`run_walk_forward_evaluation` runs `strategy_research.runner.run_gross_and_net`
(Phase 23, unmodified) once per rolling window from
`strategy_research.splits.generate_walk_forward_windows` (Phase 23,
unmodified), with `start_date`/`end_date` set to each fold's own TEST
window only -- never its TRAIN window. This works without any change to
`backtest.engine` because `AsOfDataView.get_bars` already binds to the
backtest clock's current time, independent of the configured backtest
start date, so a strategy's own lookback query still reaches genuine
prior history the moment the fold's first checkpoint fires (see
ADR-0031 Decision 1 for the full argument). Each fold starts from a
fresh `initial_capital` -- walk-forward here checks consistency across
independent periods, not one continuous compounding run. CLI defaults:
6-month TRAIN window, 2-month TEST window, 2-month step (fixed before
any real run, not tuned against a result -- RULE 0.8).

## 9. Strategy definitions

Unchanged from Phase 22/23: `BuyAndHoldStrategy` (reference baseline,
Phase 2), `LongTermMomentumStrategy`, `TrendVolatilityStrategy`,
`RiskControlledMomentumStrategy` (all Phase 23). No strategy code was
modified this phase.

## 10. Parameter policy

Every strategy uses its existing default `*Parameters` dataclass --
`LongTermMomentumParameters()`, `TrendVolatilityParameters()`,
`RiskControlledMomentumParameters()`. No grid search, no parameter
sweep. `tests/strategy_research/test_walk_forward_evaluation.py::TestStrategyParameterImmutability`
confirms these dataclasses are frozen and that a fresh `Strategy`
instance is constructed per gross/net run per fold (no state leaks
fold-to-fold). RULE 0.8 (fixed before evaluation, never re-tuned
afterward) applies to both the strategy parameters and this phase's own
CLI defaults (`--train-window-months`/`--test-window-months`/
`--step-months`), none of which have been adjusted based on any result
this phase has seen.

## 11. Transaction cost / slippage

Unchanged from Phase 2/23: `DEFAULT_TRANSACTION_COST_MODEL`/
`DEFAULT_SLIPPAGE_MODEL` for the "net" leg,
`ZERO_TRANSACTION_COST_MODEL`/`ZERO_SLIPPAGE_MODEL` for the "gross" leg,
both run for every fold via `run_gross_and_net`.
`tests/strategy_research/test_walk_forward_evaluation.py::TestTransactionCostAndGrossNetConsistency`
confirms the net leg carries a non-zero transaction cost whenever
trades occur, and that net return never exceeds gross return for the
same set of fills.

## 12. Fold-by-fold results (real data)

**NOT RUN THIS SESSION.** This sandboxed environment has no real
ingested data (`data/` is empty and gitignored) and cannot reach real
market data providers -- re-confirmed this session via the same egress
check prior phases used (`curl "$HTTPS_PROXY/__agentproxy/status"`):
`api.tiingo.com`, `stooq.com`, and `openapi.tossinvest.com` all remain
**BLOCKED**. `scripts/run_long_horizon_validation.py` was built and
verified this phase (see section 18 below for how), but has never been
executed against the real 2023-2024 catalog by this session.

**Ready to run externally**, using the real data already ingested in
this project's Codespaces session (per `STRATEGY-RESEARCH-REPORT.md`'s
Addendum):

```
python3 scripts/run_long_horizon_validation.py \
    --universe PILOT_UNIVERSE \
    --start 2023-01-02 --end 2024-12-31 \
    --db-path ./data/real_market_data
```

This produces a `long_horizon_validation.json` report plus console
output with per-fold results, an aggregate per strategy, and each
strategy's `EvidenceLevel`. Given the real window is only ~2 years, the
honest expectation (see section 17) is that most or all evidence
assessments land at `INSUFFICIENT_EVIDENCE` or `PRELIMINARY` --
`MIN_FOLDS_FOR_ROBUSTNESS` (6 real folds) may not be reached once TEST
is reserved and TRAIN+VALIDATION is the only region walk-forward runs
across.

## 13. Aggregate results (real data)

**NOT AVAILABLE THIS SESSION** -- depends on section 12. Nothing is
fabricated here in its place.

## 14. Regime analysis (real data)

**NOT AVAILABLE THIS SESSION** -- depends on section 12.
`run_walk_forward_evaluation` classifies each fold's regime via
`regime.detector.RegimeDetector`/`make_single_point_view` (Phase 5,
unmodified) as of the fold's own `test_end`
(`tests/strategy_research/test_walk_forward_evaluation.py::TestAsOfTimeIntegrity`
confirms this exactly, not the run's overall end or any other time).
Given the real window is 2023-2024 -- publicly known to have been a
strong, largely uninterrupted US equity bull market driven substantially
by AI/semiconductor names (this pilot universe includes NVDA/AVGO) --
any real fold-by-fold regime breakdown obtained from section 12's
external run should be expected to skew heavily toward BULL, with
correspondingly limited ability to say anything about BEAR or NEUTRAL
regime behavior. This is a real, structural limitation of the
currently-available history, not a defect in the regime classification
itself.

## 15. Overfitting / multiple-testing analysis

Four strategies exist in this project (Buy & Hold + 3 candidates from
Phase 23), each evaluated with exactly one default parameter
combination this phase (no grid search) -- unchanged from Phase 23/24's
own count. `ResearchLog` records one `CandidateEvaluation` per strategy
per `scripts/run_long_horizon_validation.py` run
(`tests/strategy_research/test_evidence.py::TestPboDsrApplicability::test_every_logged_candidate_is_retained_never_pruned`
confirms nothing is silently dropped). No candidate's parameters were
adjusted after seeing any result, this phase or prior ones.

## 16. PBO / Deflated Sharpe applicability

`strategy_research.evidence.assess_pbo_dsr_applicability` (this phase)
checks Phase 18's documented adoption trigger (multiple candidates,
each with enough real out-of-sample folds to rank meaningfully) against
whatever `real_fold_counts_by_candidate` an actual run produces -- it
does **not** compute PBO or Deflated Sharpe itself; that computation
remains deferred pending an explicit human decision to adopt it
(`docs/research/walk-forward-pbo-deflated-sharpe.md`, Phase 18,
unchanged). Because this phase's own CLI never sets `pbo_dsr_applied=True`,
no strategy evaluated by `scripts/run_long_horizon_validation.py` can
reach `EvidenceLevel.CANDIDATE` through this phase's own tooling alone
-- `ROBUSTNESS_PENDING` is the honest ceiling until a future phase
actually implements the PBO/DSR computation.

**Applicability result**: not evaluated against real data this session
(depends on section 12's real fold counts). A synthetic, realistic-scale
dry run this phase (4 candidates, PILOT_UNIVERSE's real 15 tickers with
synthetic deterministic prices -- explicitly a pipeline check, not a
real-data result) did produce `applicable=True` once each candidate
reached >= 6 folds, confirming the applicability check itself works
correctly end-to-end.

## 17. Evidence classification

No strategy has been assigned any `EvidenceLevel` from real data this
session -- section 12 was not run. `EvidenceLevel.VALIDATED` remains
structurally unreachable by `classify_evidence_level` regardless
(`tests/strategy_research/test_evidence.py::TestEvidenceLevelNeverReachesValidated`
sweeps a wide range of inputs, including the most favorable one the
function can receive, and confirms `VALIDATED` is never produced) --
reaching it requires an explicit human review this project's automated
tooling does not perform, by design (ADR-0031 Decision 3).

## 18. Known limitations

- This sandboxed session has never had real market data access, for
  any phase (Phase 20 through 25) -- unchanged.
- Only ~2 years of real history exist anywhere in this project (in the
  user's own Codespaces session), which is short for both a
  chronological TRAIN/VALIDATION/TEST split *and* multi-fold
  walk-forward simultaneously -- expect few real folds even once
  section 12 is run externally.
- The available real window (2023-2024) is a single, unusually strong,
  largely one-directional bull market -- any real evidence gathered
  from it cannot speak to BEAR or high-stress regime behavior at all.
- Survivorship bias in `PILOT_UNIVERSE_V1` is unresolved (section 6).
- PBO/Deflated Sharpe remains unimplemented (section 16) -- this
  phase's `EvidenceLevel.CANDIDATE` ceiling is consequently unreachable
  through this phase's own tooling until a future phase implements it.
- `data_infra.calendar.US_EQUITY`'s holiday calendar remains
  non-production-accurate (documented limitation, unchanged since
  Phase 24's Bug 2 fix addressed the strategy's fragility to this, not
  the calendar's own incompleteness).

## 19. What is needed for stronger validation

- Run `scripts/run_long_horizon_validation.py` (section 12's command)
  against the real 2023-2024 catalog, in an environment with that data
  already ingested, and report the actual per-fold/aggregate/regime/
  evidence results here as an addendum (the same pattern
  `STRATEGY-RESEARCH-REPORT.md`'s own Addendum section used for Phase
  24's real single-window run).
- Ingest additional real history further back than 2023-01-02 --
  `scripts/ingest_real_market_data.py` already supports an arbitrary
  `--start` date; no new ingestion script or flag is needed, only
  network access from an environment where it can actually run.
  Meaningfully more real folds, and exposure to more than one market
  regime, both require this.
- Once real folds exist for 2+ candidates each with >= 6 real
  out-of-sample folds, actually implement the PBO/Deflated Sharpe
  computation (Phase 18's DECISION REQUIRED item) so
  `pbo_dsr_applied=True` can honestly be passed and `EvidenceLevel.CANDIDATE`
  become reachable for the first time.
- A real, point-in-time-correct historical constituent list for the
  universe (section 6), to remove the survivorship-bias limitation.
