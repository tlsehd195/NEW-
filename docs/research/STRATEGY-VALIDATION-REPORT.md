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
    --db-path ./data/real_market_data \
    --data-status REAL
```

(`--data-status REAL` is required as of Phase 27 -- see the Phase 27
Addendum below for why.)

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

## Phase 26 Addendum

Phase 26's stated goal was extending real data range and running actual
long-horizon Walk-Forward -- **neither was possible from this session**;
this addendum records what was verified instead, and answers the
instruction's required questions honestly rather than fabricating
results.

### Precise environment diagnosis (new this phase)

Prior phases recorded "CONNECT 403" without further diagnosis. Phase 26
ran DNS resolution, a raw TCP connect (bypassing the configured proxy),
and a direct HTTPS request (also bypassing the proxy) as three
independent layers. DNS resolves correctly and the TCP handshake to
`api.tiingo.com:443` succeeds; only the HTTP request itself is denied,
with response header `x-deny-reason: host_not_allowed` and body "Host
not in allowlist: \<host\>. Add this host to your network egress
settings to allow access." -- identical for all three domains
(`api.tiingo.com`, `stooq.com`, `openapi.tossinvest.com`). This is
conclusively an **environment-level network egress allowlist** block
(status: `BLOCKED_BY_ENVIRONMENT`), not a provider-side rejection, not
DNS failure, not an auth failure, not a rate limit. Full detail:
`docs/operations/MARKET-DATA-PROVIDER.md`'s "Phase 26 precise block
diagnosis" section. No `MARKET_DATA_API_KEY` is set in this session's
environment either (checked, not assumed).

### Point-in-time CASE 1-5 audit (instruction section 9)

CASE 1-4 were already covered by existing Phase 1/2/20 tests (audited
and confirmed, not re-implemented). CASE 5 (re-running real ingestion
must not retroactively change an already-established as-of query
result at an earlier time) had no existing direct test -- added
`tests/data/test_phase26_point_in_time_cases.py` (2 new tests, against
the real `IngestionRunner`/`DuckDBDataRepository` path): extending an
already-ingested real range with new, later data leaves every earlier
as-of query byte-identical, and re-running ingestion over the exact
same range twice (a retry/resume scenario) is fully idempotent and
equally non-retroactive.

### Corporate action 8-question audit (instruction section 8)

All 8 questions were checked against existing code and tests (not
assumed): raw `close` is never replaced by Tiingo's `adjClose`
(`src/data_infra/providers/tiingo.py` -- `adjusted_close` stays a
separate, optional field); splits and dividends are stored as distinct
`CorporateAction` records with different `CorporateActionType` values;
`CorporateAction.effective_time` is a field structurally distinct from
`available_time`/`ingestion_time`; a late-discovered corporate action or
dividend cannot change an earlier as-of query or backtest result
(CASE 1/2 above); `CorporateActionApplier` (wired into `BacktestEngine.run()`)
adjusts held position quantities on a SPLIT event
(`tests/backtest/test_corporate_actions.py::test_split_adjusts_held_position`);
dividends are correctly reflected in the TOTAL_RETURN benchmark
(`tests/backtest/test_total_return.py::test_dividend_is_added_back_into_the_days_return`).
**No gap found** -- every question was already correctly implemented
before this phase; this phase's contribution is verifying and recording
that fact explicitly rather than assuming it.

### Reproducibility fields added to the CLI (instruction section 22)

`scripts/run_long_horizon_validation.py`'s JSON report previously had
no `experiment_id`/`data_version` fields section 22 asks for. Added
both, additively: `experiment_id` is a deterministic hash of the run's
own configuration (universe, date range, split fractions, walk-forward
window sizes, initial capital -- never a wall-clock value, so an
identical configuration always produces an identical id);
`data_version` is a hash of what the repository actually contains for
this universe+window at run time (per-symbol/benchmark bar counts),
using the same `data_infra.versioning.compute_data_version` function
`scripts/ingest_real_market_data.py` already uses for its own content
checksum. Verified end-to-end against a small synthetic-scale dry run
(both fields present and correctly populated in the resulting JSON).

### Answers to the instruction's required questions (section 32)

Most data-dependent questions remain unanswerable from this session for
the same reason as Phase 25 -- no real data exists locally
(`data/` empty, gitignored) and the environment is `BLOCKED_BY_ENVIRONMENT`
(see above), not because of any code defect.

- **Q1 (actual date range obtained)**: None, this session. The only real
  data this project has ever obtained (2023-01-02 to 2024-12-31) exists
  solely in a user's separate Codespaces environment, unchanged since
  Phase 24.
- **Q2 (actual symbol count obtained)**: None, this session; 15
  tradeable + SPY in the user's separate environment (unchanged).
- **Q3 (provider)**: Tiingo (primary), Stooq (fallback) -- unchanged.
- **Q4 (data_version/checksum of real data)**: Not computable from this
  session (no local real data). `scripts/ingest_real_market_data.py`
  already records a `content_checksum` for whatever it actually
  ingests; `scripts/run_long_horizon_validation.py` now also records one
  (this phase's addition, see above) -- both are ready to produce a real
  value the moment real ingestion runs somewhere with access.
- **Q5 (corporate actions actually obtained)**: Not this session; 107
  real corporate actions were obtained in the user's Codespaces session
  after Phase 24 (unchanged fact, re-cited not re-verified).
- **Q6 (SPY Total Return benchmark computed from real data)**: Not this
  session (`BENCHMARK_UNAVAILABLE`, no local SPY data); it WAS computed
  from real data in the user's Phase 24 follow-up run.
- **Q7 (per-strategy full-period real performance)**: Unchanged from
  Phase 24's Addendum table in this same document's earlier section --
  not re-run this session.
- **Q8 (per-strategy real Walk-Forward performance)**: Still none --
  this remains the single biggest gap this project has, blocked
  strictly on real data access, not on missing infrastructure (the
  infrastructure has been ready and tested since Phase 25).
- **Q9 (regime-dependent strengths/weaknesses)**: Not answerable without
  Q8's data.
- **Q10 (risk-adjusted improvement over Buy & Hold)**: Not answerable
  without Q8's data; the single-window Phase 24 result showed Buy & Hold
  outperforming every other candidate over 2023-2024's bull market --
  not evidence either way about risk-adjusted behavior across regimes.
- **Q11 (results survive transaction costs)**: Not answerable without
  Q8's data; the gross/net machinery to answer it is tested and ready
  (`tests/strategy_research/test_walk_forward_evaluation.py::TestTransactionCostAndGrossNetConsistency`).
- **Q12 (results depend on a specific period/symbol)**: Cannot be ruled
  out or confirmed -- only one real window (2023-2024, a strong,
  largely single-direction bull market including NVDA/AVGO) has ever
  been observed. This dependency risk is the central reason Walk-Forward
  across a longer, more varied real history is this project's most
  valuable remaining next step.
- **Q13 (current evidence classification)**: No strategy has ever been
  assigned an `EvidenceLevel` from real data (`classify_evidence_level`
  has never been called against a real `WalkForwardAggregate`) --
  effectively `INSUFFICIENT_EVIDENCE` for all four candidates, by the
  same rule that forces that result for any non-real-data input.
- **Q14 (PBO/DSR adoption conditions met)**: Not evaluated against real
  data this session (`assess_pbo_dsr_applicability` has never been
  called with real fold counts); a synthetic-scale dry run in Phase 25
  did confirm the check itself returns `applicable=True` once fold
  counts clear the threshold, proving the check works, not that real
  data has cleared it.
- **Q15 (most promising research target)**: Unchanged from Phase 25 --
  running `scripts/run_long_horizon_validation.py` against the real
  2023-2024 catalog the user already has (external command in section
  12 above) is the single highest-value next action; it requires no new
  code.
- **Q16 (can any strategy be called "validated alpha")**: **No.**
  Applying `classify_evidence_level`'s own rules strictly: with zero
  real folds evaluated, every candidate is `INSUFFICIENT_EVIDENCE`, the
  lowest tier. Even in the most favorable hypothetical case, the highest
  tier the project's own code can ever assign is `CANDIDATE` --
  `VALIDATED` requires human review no automated function in this
  codebase performs.
- **Q17 (what currently blocks Live Trading)**: Unchanged and
  independent of this phase's work entirely -- Toss `CapabilityStatus`
  remains `UNKNOWN` for all four capabilities (operational verification
  never performed), real Toss credentials have never been obtained, and
  the three risk-default values remain PROPOSED / AWAITING USER
  RATIFICATION. None of Phase 25/26's strategy-research work is a
  precondition for or against Live activation; they are unrelated
  gates.
- **Q18 (highest-value next Phase 27 work)**: Run
  `scripts/run_long_horizon_validation.py` against the real data the
  user already has (zero new code needed), OR resolve the environment
  egress allowlist restriction (section above) so this session itself
  can ingest more real history directly -- either would unblock the
  actual long-horizon evidence this and the prior phase's infrastructure
  was built to produce.

## Phase 27 Addendum

Phase 27's stated goal was to actually execute real-data Walk-Forward
against the strategies -- **still not possible from this session**: the
environment egress block is unchanged (re-verified, identical
`x-deny-reason: host_not_allowed` diagnosis, no new evidence of a
policy change), no `MARKET_DATA_API_KEY` is set, and `data/` remains
empty. No fabricated real result is recorded here.

### Bug found and fixed: `is_real_data` was hardcoded in the CLI

Auditing `scripts/run_long_horizon_validation.py` against this phase's
own instruction (sections 27/28-I: real and synthetic status must never
be confused in a report) found that `classify_evidence_level(...,
is_real_data=True, ...)` was hardcoded regardless of what `--db-path`
actually contained. Every synthetic dry run this project has ever run
through this script (Phase 25's and Phase 26's own smoke tests
included) therefore produced an `EvidenceAssessment` structurally
indistinguishable from a real one -- those runs were always correctly
described as synthetic in prose by whoever ran them, but the JSON
report itself carried no field saying so, and the evidence
classification logic used the real-data thresholds regardless.

**Fix** (`scripts/run_long_horizon_validation.py`): added a required
`--data-status {REAL,SYNTHETIC}` argument. It now gates `is_real_data`
directly, is folded into `experiment_id` (a REAL and a SYNTHETIC run of
an otherwise-identical configuration can never collide into the same
id), and is written into the report's new top-level `data_status`
field plus its `note`/`benchmark_status` text. Verified end-to-end: the
exact same synthetic-scale dry-run catalog used in Phase 25/26, re-run
with `--data-status SYNTHETIC`, now correctly produces
`INSUFFICIENT_EVIDENCE` for every strategy (previously it would have
shown `ROBUSTNESS_PENDING`, the real-data-only tier).

Regression tests (`tests/strategy_research/test_run_long_horizon_validation_wiring.py`,
9 new, static AST/source-based -- the script itself is still never
imported or executed by the automated suite): `is_real_data` is never a
hardcoded boolean literal, `--data-status` is required with exactly
`{REAL, SYNTHETIC}` choices, `experiment_id`'s hash input includes
`data_status`, the report dict carries `data_status`/`experiment_id`/
`data_version`, the walk-forward call uses only
`train_start`..`validation_end` and the held-out test call uses only
`test_start`..`test_end` (no TEST-region leakage into the walk-forward
region at the CLI's own call site), both evaluation calls per strategy
reference the same `benchmark_id` variable (no per-strategy benchmark
drift), `benchmark_id` is only ever assigned `None` or the
`spy_bars`-gated conditional (no fabricated fallback), and the script
calls neither `datetime.now()`/`utcnow()` nor uses `random`.

### Full test suite

Baseline (this session, before any change): **1640 passed**. Final:
**1649 passed, 0 failed, 0 skipped** -- 9 new tests, existing 1640
unmodified.

### Answers to the 5 required final questions (instruction section 41)

1. **실제 시장데이터로 Walk-Forward TEST가 실행되었는가?** No. This
   session's environment remains `BLOCKED_BY_ENVIRONMENT` (re-verified,
   unchanged diagnosis). No real Walk-Forward has been executed by any
   session to date.
2. **4개 전략 중 어떤 전략이 여러 TEST fold에서 SPY 및 Buy & Hold 대비
   일관된 우위를 보였는가?** Not answerable -- zero real TEST folds
   exist.
3. **그 우위가 NET 기준에서도 유지되는가?** Not answerable for the same
   reason.
4. **현재 증거만으로 해당 전략을 검증된 알파라고 부를 수 있는가?** No.
   With zero real folds, `classify_evidence_level` places every
   candidate at `INSUFFICIENT_EVIDENCE`, its most conservative tier --
   confirmed empirically this phase by the fixed CLI's own
   `--data-status SYNTHETIC` output. `VALIDATED` remains structurally
   unreachable by this project's own code regardless.
5. **다음으로 필요한 검증은 무엇인가?** Unchanged from Phase 25/26:
   run `scripts/run_long_horizon_validation.py --data-status REAL`
   (now a required flag) against the real 2023-2024 catalog the user
   already has, in an environment with that data -- no further code
   changes are needed for that specific run.

## Phase 28 Addendum

Phase 28's stated goal was to actually execute real-data Walk-Forward
TEST for the first time. **Still not possible from this session**:
re-verified network egress (identical `x-deny-reason: host_not_allowed`)
and `MARKET_DATA_API_KEY` (unset) -- both unchanged from Phase 26/27.
This phase additionally ran an exhaustive filesystem search (project
docs, ingestion manifests, DuckDB/Parquet files anywhere, environment
variables, existing scripts) rather than checking only `data/` -- no
real data location was found anywhere in this session's environment.
Status: `BLOCKED_BY_ENVIRONMENT` (root cause) and `BLOCKED_BY_DATA`
(immediate finding) both apply -- the only path to real data locally is
network ingestion, which remains blocked. No fabricated real result is
recorded here.

### Real-provenance plausibility check added

Instruction section 5 (items B/C) asked that `--data-status REAL` not
be taken purely on faith -- the data's own provenance should be
cross-checked. `scripts/run_long_horizon_validation.py` now verifies
that every bar's `Provenance.source` is `"tiingo"` or `"stooq"` (the
exact strings the real provider implementations stamp -- verified
directly against `src/data_infra/providers/tiingo.py`/`stooq.py`'s own
source) whenever `--data-status REAL` is passed, and refuses to
proceed (exit code 1, before any strategy is evaluated) if an
unrecognized source is found. This closes a real gap: previously
nothing stopped `--data-status REAL` from being passed against data
that was never actually real, beyond the caller's own honesty.

Verified end-to-end this phase, not just statically: the identical
synthetic-fixture catalog construction Phase 25-27 used for their own
dry runs (bars carrying `provenance.source="test_source"`) is now
correctly **refused** under `--data-status REAL` (exit code 1, with a
clear error naming the exact unexpected source and the allowlist), and
still runs correctly to completion under `--data-status SYNTHETIC`
against the same catalog (producing `INSUFFICIENT_EVIDENCE` for every
strategy, `SYNTHETIC_TOTAL_RETURN` benchmark status, and real non-zero
trade counts/returns from the synthetic price series -- confirming the
underlying pipeline itself works correctly end to end once genuine bars
exist in the catalog, which was not separately re-confirmed since
Phase 25's original build).

3 new regression tests (`tests/strategy_research/test_run_long_horizon_validation_wiring.py`,
static AST-based, same discipline as Phase 27's): `_KNOWN_REAL_PROVIDER_SOURCES`
matches the real providers' actual source strings, the unexpected-source
guard actually returns non-zero (not just a warning), and the guard
runs before any strategy's walk-forward evaluation begins.

### Full test suite

Baseline (this session): **1649 passed**. Final: **1652 passed, 0
failed, 0 skipped** -- 3 new tests, existing 1649 unmodified.

### Answers to the 6 required final questions (instruction section 38)

1. **실제 시장 데이터로 Walk-Forward TEST가 실행되었는가?** No. This
   session remains `BLOCKED_BY_ENVIRONMENT`/`BLOCKED_BY_DATA`
   (exhaustively re-verified this phase, unchanged root cause).
2. **REAL TEST fold는 몇 개인가?** **0.**
3. **어떤 전략이 가장 일관된 성과를 보였는가?** Not answerable -- zero
   real TEST folds exist.
4. **그 우위가 NET 기준에서도 유지되는가?** Not answerable for the same
   reason.
5. **SPY Total Return benchmark를 여러 TEST fold에서 지속적으로
   이겼는가?** Not answerable -- zero real TEST folds exist.
6. **현재 증거 수준에서 "검증된 알파"라고 부를 수 있는 전략이
   있는가?** No. With `REAL_TEST_FOLDS == 0`, `classify_evidence_level`
   places every one of the 4 candidates at `INSUFFICIENT_EVIDENCE`, its
   most conservative tier -- this is a direct, unmodified consequence of
   the existing evidence policy, not a judgment call made this phase.
   `VALIDATED` remains structurally unreachable by any code in this
   project regardless of what future real data might show.

## Phase 29 Addendum

**REAL WALK-FORWARD EXECUTION: NOT COMPLETED.** Phase 29's goal was a
2010 -> latest-available, broad, survivorship-aware US equity
Walk-Forward run. Re-verified this session (not assumed unchanged):
network egress remains `BLOCKED_BY_ENVIRONMENT` (identical `x-deny-reason:
host_not_allowed` diagnosis for `api.tiingo.com`, DNS resolves, TCP
connects, only the HTTP request is denied), no `MARKET_DATA_API_KEY` is
set, and an exhaustive filesystem search found no real data anywhere in
this session. No real ingestion, of any size, was possible.

### What this phase actually built

Audited `src/data_infra/models.py`/`repository.py` directly (not
assumed) and found the point-in-time-safe, survivorship-aware
architecture the instruction asks for -- `SecurityMaster.security_id`
as a permanent identifier independent of `ticker`, `valid_from`/
`valid_to` on both `SecurityMaster` and `UniverseMembership`,
`SecurityStatus.DELISTED`, and `get_universe(as_of_time=...)`'s correct
point-in-time filtering -- already existed, unmodified, since Phase 1.
The real gap: `build_security_masters`/`build_universe_memberships`
(Phase 24) never used `SymbolMetadata.listed_from`/`listed_to`, applying
one uniform `valid_from`/`status=ACTIVE`/`valid_to=None` to every
symbol regardless of what was actually known about it. Fixed
additively (byte-for-byte unchanged output for every existing
`SymbolMetadata` entry, since none has `listed_from`/`listed_to` set
yet); full rationale in
`docs/decisions/ADR-0032-security-identity-and-survivorship-aware-universe.md`.

Also added: `detect_ticker_collisions` (distinguishes legitimate ticker
reuse across non-overlapping historical windows from a genuine
same-time collision across two different `security_id`s), and
`TiingoDataProvider.fetch_symbol_metadata`/`normalize_symbol_metadata`
(Tier 2 documentation, never exercised against a live response --
broad-universe discovery groundwork for once network access exists).

Proved, against both `InMemoryDataRepository` and a real on-disk
`DuckDBDataRepository` restart (synthetic fixtures only): a security
listed in 2018 is correctly absent from a 2015 `get_universe` query and
present in a 2020 one; a security delisted in 2017 is correctly present
before and absent after that date; and -- the instruction's central
technical question -- a "current survivors only" query and a real
historical-point-in-time query genuinely differ (one dedicated test
constructs a universe where they return the exact opposite membership
sets, matching the instruction's own stated concern about survivorship
bias). 19 new tests total this phase (12 survivorship-aware universe,
6 Tiingo metadata, 1 DuckDB delisted-security persistence). Full suite:
baseline **1652 passed** -> final **1671 passed, 0 failed, 0 skipped**.

### Data (instruction section 63 fields)

| Field | Value |
|---|---|
| Provider | N/A -- no real ingestion this session |
| Requested start | 2010-01-01 (per instruction) |
| Actual start | N/A |
| Actual end | N/A |
| Security count | N/A |
| Active count | N/A |
| Delisted count | N/A |
| Unknown count | N/A |
| Bar count | N/A |
| Corporate action count | N/A |
| Data version | N/A |
| Checksum | N/A |

### Universe (instruction section 63 fields)

| Field | Value |
|---|---|
| Pilot universe | `PILOT_UNIVERSE_V1`, unchanged, 15 symbols |
| Broad universe | Not populated -- would require real provider metadata (blocked) |
| Historical universe | Mechanism ready and tested (this phase); no real historical dates populated |
| Survivorship-aware | Mechanism ready and tested (this phase, synthetic fixtures); not populated with real data |
| Delisted included | Structurally supported (this phase); no real delisted security ever populated |
| Permanent identifiers available | Yes -- `SecurityMaster.security_id`, has been since Phase 1 |

### Answers to the instruction's 10 required final questions

1. **2010년부터 최신 실제 데이터까지 확보했는가?** NO.
2. **실제 broad US equity universe를 사용했는가?** NO.
3. **historical security identity를 사용했는가?** PARTIAL -- the
   mechanism (`security_id`, `valid_from`/`valid_to`, `SecurityStatus`)
   exists and is tested; no real historical identity data was ever
   populated.
4. **delisted securities가 포함되었는가?** NO (real); YES (synthetic
   fixture, proving the mechanism).
5. **survivorship bias가 이전보다 실질적으로 줄었는가?** N/A -- no real
   universe was ever built to compare against; the underlying query
   mechanism now correctly distinguishes current-survivor from
   historical membership when given real dates, which it was not.
6. **실제 Walk-Forward TEST fold가 몇 개인가?** **0.**
7. **NET 기준으로 여러 fold에서 가장 일관된 전략은?** N/A --
   INSUFFICIENT_EVIDENCE, 0 real folds.
8. **SPY Total Return을 여러 독립 TEST fold에서 이겼는가?** N/A.
9. **특정 소수 종목에 의존한 성과인가?** N/A -- no real performance
   exists to attribute.
10. **이 전략을 "검증된 알파"라고 부를 수 있는가?** NO --
    INSUFFICIENT_EVIDENCE for all 4 candidates, unchanged from every
    prior phase; `VALIDATED` remains structurally unreachable by this
    project's own code.

## Phase 30 Addendum

**FINAL STATUS: VALIDATION BLOCKED -- ENVIRONMENT.** Phase 30's goal
was to move from "survivorship-aware architecture exists" to "a real,
provenance-documented, broad historical US equity dataset has been
acquired and validated." This did not happen -- network egress from
this environment remains blocked to every market-data provider host
tried.

### Network re-verification (broader than any prior phase)

Re-tested this session (not assumed unchanged from Phase 26-29):
`api.tiingo.com`, `stooq.com`, `openapi.tossinvest.com` all still
return `HTTP/2 403`, header `x-deny-reason: host_not_allowed`, body
"Host not in allowlist... Add this host to your network egress
settings to allow access." -- identical to every prior phase's
diagnosis. New this phase: four additional candidate provider hosts
were also tested (`data.nasdaq.com`, `api.polygon.io`,
`www.alphavantage.co`, `financialmodelingprep.com`, `crsp.org`) -- all
five return the same `403`/`host_not_allowed`. Two control hosts
(`github.com`, `pypi.org`) return `200` in the same run, confirming
this is a scoped allowlist blocking market-data providers
specifically, not a total network outage. `env | grep -i
"MARKET_DATA\|TIINGO\|TOSS"` returns nothing -- no API key is
configured in this environment. An exhaustive filesystem search
(`data/`, `/tmp`, environment variables) again found no real market
data anywhere in this session, unchanged since Phase 28.

### What this phase actually built

1. **Ingestion manifest gap (instruction section 16), found and
   fixed**: `scripts/ingest_real_market_data.py`'s manifest previously
   reported only the *requested* `start`/`end` -- never what a
   provider actually returned. A provider lacking data back to the
   requested start (or lagging behind the requested end) would have
   been silently indistinguishable from a run that got exactly what
   was asked for, inviting a false "covers 2010-latest" claim. Fixed:
   the manifest now reports `actual_data_start`/`actual_data_end`
   (computed from the real persisted bars' own timestamps, `None` when
   no bars were persisted -- never equal to the request by
   construction), an explicit `delisted_count` (from the persisted
   `SecurityMaster` records' actual `status`), and an explicit
   `data_status: "REAL"` field. The ambiguous old `start`/`end` keys
   were renamed to `requested_start`/`requested_end` rather than
   leaving both the old and new keys side by side. 8 new AST-based
   regression tests (`tests/data_infra/test_ingest_real_market_data_wiring.py`
   -- this script is never executed by the automated suite, same
   discipline as `run_long_horizon_validation.py`'s wiring tests).
2. **CASE A-G survivorship regression tests (instruction section 8)**:
   `tests/data_infra/test_phase30_survivorship_cases.py`, 8 tests,
   literally traceable by name to each of the instruction's seven
   named cases, using the instruction's own 2010 framing. No new
   mechanism -- the underlying `SecurityMaster`/`UniverseMembership`/
   `get_universe(as_of_time=...)` machinery is unchanged from
   Phase 1/29; this file exists purely for direct auditability.
3. **ADR-0033**: a data-source decision tree (instruction section 4)
   classifying Tiingo/Stooq/Nasdaq Data Link/Polygon/Alpha
   Vantage/Financial Modeling Prep/CRSP across historical prices,
   delisted coverage, ticker changes, corporate actions, historical
   universe membership, point-in-time metadata, and
   licensing/access -- sourced from public documentation via web
   search this session (cited inline), never live-verified against an
   actual API response (network blocked). Also documents the
   instruction's three-universe-concept distinction (price universe vs.
   tradable universe vs. index-constituent universe, section 5) and
   confirms this project's existing `UniverseDefinition` already avoids
   the conflation the instruction warns against (`role` is `"PILOT"`/
   `"RESEARCH"`, never `"INDEX"`; `PILOT_UNIVERSE_V1`'s own description
   already disclaims index representativeness).
4. **Infrastructure audit (instruction section 2C)**: confirmed, by
   direct code reading rather than assumption, that
   `DataQualityFramework` already implements essentially every check
   instruction section 15 asks for (duplicate records, OHLC
   consistency, negative/zero price, negative volume, impossible
   price movement, missing timestamp gaps, split/dividend
   consistency, ingestion-precedes-availability, insufficient
   coverage); that `valid_from < valid_to` is already enforced
   structurally at `SecurityMaster`/`UniverseMembership` construction
   (a `ValueError`, not a soft warning); and that `IngestionRunner`
   already implements checkpointing, retry/backoff, idempotent re-run,
   and per-symbol `SUCCESS`/`PARTIAL_SUCCESS`/`FAILED` reporting
   (instruction section 14) -- all from Phase 1/20-22, unmodified. No
   new quality-check or ingestion-retry code was needed.

### No real ingestion, no real universe, no real walk-forward

Consistent with instruction section 30 ("do NOT spend the entire phase
making synthetic data look realistic"): no synthetic data was dressed
up as real, no broad universe was fabricated, and no walk-forward was
executed against anything but the same pre-existing synthetic fixtures
used for pipeline-correctness testing since Phase 25. The research
conclusion remains `REAL_VALIDATION_NOT_COMPLETED`.

### Answers to the instruction's 15 required final questions (section 33)

1. **Was real data from 2010 or earlier actually obtained?** NO.
2. **What is the actual first date?** N/A -- no real data exists in
   this environment.
3. **What is the actual latest date?** N/A.
4. **How many unique historical securities are represented?** 0 real;
   the synthetic CASE A-G/Phase 29 fixtures use up to 3 per test,
   proving the mechanism only.
5. **How many delisted securities are represented?** 0 real (the new
   `delisted_count` manifest field has never run against a real
   dataset in this environment to produce a number).
6. **Is the universe genuinely historical or merely today's
   survivors?** N/A -- no real universe was built. The underlying
   mechanism (proven this phase via CASE A-G) is capable of genuinely
   historical, point-in-time-correct membership once given real dates;
   it has never been given any.
7. **How many REAL walk-forward TEST folds executed?** **0.**
8. **Which strategy was most consistent across REAL TEST folds?** N/A
   -- INSUFFICIENT_EVIDENCE, 0 real folds.
9. **Did that advantage survive NET transaction costs?** N/A.
10. **Did it outperform SPY Total Return?** N/A.
11. **Was the advantage dependent on a handful of securities?** N/A --
    no real performance exists to attribute.
12. **Did the result survive different market regimes?** N/A.
13. **Did survivorship-aware universe construction materially change
    conclusions?** N/A -- no real conclusions exist yet to change; the
    synthetic proof (Phase 29's `test_current_survivor_only_query_and_historical_query_genuinely_differ`,
    reaffirmed this phase by CASE F/G) shows the mechanism *would*
    change results once given real historical dates (current-survivor
    query and historical query produce disjoint sets in the test
    fixture), which is the necessary precondition for this question to
    ever be answerable with real data.
14. **Can any strategy legitimately be called "validated alpha"?** NO
    -- INSUFFICIENT_EVIDENCE for all 4 candidates; `VALIDATED` remains
    structurally unreachable by this project's own
    `classify_evidence_level`, unchanged.
15. **What evidence is still missing?** Everything downstream of real
    data acquisition: a real 2010-latest ingestion (blocked by this
    environment's network egress allowlist, root cause diagnosed since
    Phase 26, unchanged, now confirmed to block every provider host
    tested, not only Tiingo/Stooq/Toss), real `SymbolMetadata.listed_from`/
    `listed_to` population (the plumbing is ready since Phase 29,
    unpopulated), a real broad-universe symbol count, real corporate
    actions, real delisted-security coverage, and therefore every real
    Walk-Forward TEST fold this report's other questions depend on. The
    exact remedy remains unchanged and unactioned: add
    `api.tiingo.com`/`stooq.com` (or a chosen alternative provider's
    host, per ADR-0033) to this environment's network egress allowlist,
    outside this session's own permissions.

## Phase 31 Addendum

**Primary objective**: determine, rigorously, how this project can
obtain a broad, survivorship-aware 2010-latest US equity dataset, and
build the infrastructure to ingest it -- not to invent or tune a
strategy, not to declare success, not to touch Live Trading. Full
provider audit and decision framework: `docs/decisions/ADR-0034-real-data-acquisition-strategy.md`.

**Network re-verification**: re-confirmed this phase against a broader
host set than any prior phase -- Tiingo/Stooq/Toss plus 5 additional
candidate provider hosts (Nasdaq Data Link, Polygon, Alpha Vantage,
Financial Modeling Prep, CRSP), all identically `403`/
`x-deny-reason: host_not_allowed`; two control hosts (github.com,
pypi.org) succeed in the same run. DNS resolves and raw TCP connects
succeed for all three primary hosts -- confirmed `ENVIRONMENT_BLOCKED`
at the egress-allowlist layer specifically, never
`AUTHENTICATION_FAILED`/`PROVIDER_DOES_NOT_SUPPORT_FEATURE`/
`DATASET_DOES_NOT_EXIST`/`USER_ACCOUNT_LIMITATION` (none of those is
determinable -- no request ever reaches a provider). `MARKET_DATA_API_KEY`
remains unset.

**What this phase built**: (1) extended `ingest_real_market_data.py`'s
manifest with `providers_used`/`missing_symbols`/`active_count`/
`historical_universe_membership_available`/`survivorship_mitigation_applied`
(instruction section 18's remaining unanswered questions); (2) a new
`LocalFileDataProvider` (`src/data_infra/providers/file_import.py`)
implementing the `DataProvider` Protocol against local, pre-downloaded
CSV files instead of a live network call, plus
`scripts/import_external_market_data.py` wiring it through the
identical validated pipeline (`IngestionRunner`/`DataQualityFramework`/
`DuckDBDataRepository`) `ingest_real_market_data.py` uses -- this makes
the external-acquisition workflow (instruction section 21) an actually
runnable path, not only a documented intention, and (being
network-free) is directly exercised end-to-end by the automated test
suite; (3) `audit_survivorship` (`src/data_infra/universe.py`), a
diagnostic answering the instruction's ten survivorship questions
(section 28) with an honest FULLY_SUPPORTED/PARTIALLY_MITIGATED/
CURRENT-UNIVERSE-ONLY/UNKNOWN classification, tested against the same
kind of synthetic fixtures this project has always used to prove a
mechanism (never to claim a real result); (4) ADR-0034's provider
sufficiency matrix, re-labeled under this phase's required
VERIFIED_BY_DOCUMENTATION/VERIFIED_BY_ACTUAL_ACCESS/UNKNOWN/
NOT_AVAILABLE/ENVIRONMENT_BLOCKED vocabulary, and an explicit decision
(both C. EXTERNAL_DATASET_REQUIRED and D. ENVIRONMENT_BLOCKED apply
simultaneously, at different layers -- see ADR-0034 Decision 4).

**No real ingestion, no real universe, no real Walk-Forward** this
phase either -- consistent with instruction section 30/37, no synthetic
result is reported as if real. 30 new tests (15 ingestion-manifest
wiring + 11 file-import provider + 3 import-CLI end-to-end + 6
survivorship-audit -- some classes overlap, see the final report's
exact count).

**FINAL STATUS: VALIDATION BLOCKED -- ENVIRONMENT** (also
EXTERNAL_DATASET_REQUIRED for the full survivorship-bias-aware
objective, per ADR-0034 Decision 4 -- both hold simultaneously).

### Answers to the instruction's 15 required final questions (section 40)

1. **Can this project currently obtain 2010->latest real US equity
   data?** NO -- BLOCKED (network egress allowlist, this session).
2. **Can it obtain a broad historical universe rather than today's
   surviving stocks only?** NO -- BLOCKED, and even where network
   access exists, no already-integrated or free-tier provider supplies
   historical universe membership (ADR-0034 Decision 2).
3. **Can it obtain delisted securities?** NO -- BLOCKED; free-tier
   Tiingo/Stooq/Alpha Vantage do not supply a dedicated delisted-
   securities feed regardless (NOT_AVAILABLE, ADR-0034).
4. **Can it identify securities independently of ticker?** PARTIAL --
   the `security_id` mechanism supports it structurally (Phase 1/29),
   but this project's own population currently sets `security_id ==
   ticker` (never yet wired to a provider-confirmed permanent ID
   distinct from ticker); `audit_survivorship`'s
   `permanent_id_percentage` makes this caveat explicit rather than
   overclaiming 100%.
5. **Can it correctly handle ticker changes and ticker reuse?**
   PARTIAL -- `detect_ticker_collisions` (Phase 29) correctly
   distinguishes legitimate reuse from a genuine data-bug collision
   when given real dates; plain ticker-change (RENAMED) events are not
   distinguishable from DELISTED without a finer data source this
   project does not have (`renamed_or_merged_count` stays honestly 0
   rather than guessed).
6. **Can it reconstruct historical universe membership?** PARTIAL --
   the mechanism (`get_universe(as_of_time=...)`) is proven correct
   against synthetic fixtures (Phase 29 CASE tests, Phase 30 CASE A-G);
   no real historical membership data has ever been supplied to it.
7. **Is the resulting dataset actually survivorship-aware?**
   UNKNOWN for any real dataset (none exists); `audit_survivorship`
   would classify a real ingestion as CURRENT-UNIVERSE-ONLY unless real
   `listed_from`/`listed_to` are supplied, and never higher than
   PARTIALLY_MITIGATED given this project's current `security_id ==
   ticker` limitation (see ADR-0034).
8. **Was real 2010->latest data actually ingested?** NO.
9. **How many real securities were ingested?** 0.
10. **How many real delisted securities were ingested?** 0.
11. **How many real Walk-Forward TEST folds were executed?** **0.**
12. **Which strategy is most consistent across real TEST folds?**
    UNKNOWN -- 0 real folds, INSUFFICIENT_EVIDENCE.
13. **Does that advantage survive transaction costs?** N/A.
14. **Does it beat SPY Total Return consistently?** N/A.
15. **Can any strategy legitimately be called validated alpha?** NO --
    INSUFFICIENT_EVIDENCE for all 4 candidates, unchanged;
    `VALIDATED` remains structurally unreachable by this project's own
    `classify_evidence_level`.

## PBO / Deflated Sharpe Ratio Addendum

After Phase 31, the user obtained real 2010-2026 Tiingo data in their
own network-enabled environment (outside this sandboxed session) and
ran `scripts/run_long_horizon_validation.py --data-status REAL`
against all 4 existing strategies over the full PILOT_UNIVERSE (16
symbols). This produced this project's first-ever real walk-forward
result: 76 real folds per strategy.

**Raw fold-consistency result** (before PBO/DSR): only
`trend_volatility` cleared the fold win-rate bar (53/76 = 69.7% >=
60% required); `buy_and_hold` (55.3%), `long_term_momentum` (51.3%),
and `risk_controlled_momentum` (51.3%) did not. Whether
`trend_volatility`'s apparent edge is genuine or simply "the best of 4
compared candidates" was, until this addendum, unanswerable --
`assess_pbo_dsr_applicability` correctly reported `applicable=True`
(4 candidates, each with 76 >= the 6-fold minimum), the exact trigger
condition `docs/research/walk-forward-pbo-deflated-sharpe.md` section
9.1 named for ending this track's DEFER classification.

**What was built in response** (see
`docs/decisions/ADR-0035-pbo-deflated-sharpe-implementation.md` for
full detail): `strategy_research.pbo_dsr` (CSCV-based PBO, Deflated
Sharpe Ratio, validated against known-labeled synthetic cases before
ever being applied to anything real), wired into
`classify_evidence_level` (CANDIDATE now additionally requires PBO <
50% and DSR >= 95% when those real numbers are supplied) and into
`run_long_horizon_validation.py` (a real bug was found and fixed while
wiring this in: `assess_pbo_dsr_applicability`'s result was computed
but never fed back into evidence classification, so `pbo_dsr_applied`
was silently always `False` -- every real run's evidence was capped at
`ROBUSTNESS_PENDING` regardless of what applicability actually found).
A standalone `scripts/compute_pbo_dsr_from_report.py` applies this to
an already-completed real report without re-running the (roughly
hour-long) walk-forward.

**Actual PBO/DSR result against the real 4-strategy run**: not yet
computed in this session -- the real report JSON exists only in the
user's own environment (Codespaces), not in this sandboxed session's
filesystem. `scripts/compute_pbo_dsr_from_report.py
--report <path-to-long_horizon_validation.json>` needs to be run there
(fast -- no backtest re-run) to get the real answer to "does
`trend_volatility`'s apparent edge survive PBO/DSR scrutiny, or is it
indistinguishable from the best of 4 noisy trials." This report will be
updated with that result once it is available.
