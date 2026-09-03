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

**Actual PBO/DSR result against the real 4-strategy run** (computed by
the user in their own environment via
`scripts/compute_pbo_dsr_from_report.py`, relayed into this session
and recorded here rather than fabricated):

```
PBO (Probability of Backtest Overfitting): 62.86% across 70 CSCV splits (4 candidates, 8 groups)
CANDIDATE requires PBO < 50% and Deflated Sharpe Ratio >= 95%

buy_and_hold: evidence=ROBUSTNESS_PENDING (55% positive folds, below the 60% fold-consistency bar)
long_term_momentum: evidence=ROBUSTNESS_PENDING (51% positive folds, below the 60% fold-consistency bar)
risk_controlled_momentum: evidence=ROBUSTNESS_PENDING (51% positive folds, below the 60% fold-consistency bar)
trend_volatility: evidence=ROBUSTNESS_PENDING -- 70% of 76 real folds positive (clears the
  fold-consistency bar), but PBO=0.63 (must be < 0.50, FAILED) and Deflated
  Sharpe=0.99 (must be >= 0.95, passed) -- PBO alone blocks CANDIDATE.
```

**Final answer, honestly stated: none of the 4 strategies reach
CANDIDATE against this dataset.** `trend_volatility` was the only one
to clear the raw fold-consistency bar (69.7% positive folds), but the
CSCV-based PBO estimate says there is a 62.86% probability that its
in-sample selection as "the best of 4" would NOT have held up
out-of-sample had the CSCV resampling gone the other way -- i.e., more
likely than not that this is exactly the "picked the best of several
noisy trials" failure mode PBO exists to catch, not a persistent edge.
DSR alone (0.99) would have suggested otherwise; PBO -- the more
direct, resampling-based test of reproducibility, rather than a
distributional estimate -- is treated as authoritative when the two
disagree, per `docs/decisions/ADR-0035-pbo-deflated-sharpe-implementation.md`.

This is not a failure of this project's infrastructure -- it is the
evidence-classification system correctly refusing to let a
fold-consistency-only signal be mistaken for real, reproducible skill.
The correct conclusion at this point is `REAL_VALIDATION_NOT_COMPLETED`
for all 4 strategies against the current 16-symbol, survivorship-biased
PILOT_UNIVERSE -- not that no signal exists anywhere, only that none of
the 4 existing strategies clears this project's own evidentiary bar on
this specific dataset. Per this project's RULE 0.8/no-post-hoc-tuning
discipline, this result must NOT be used to retune any strategy's
parameters, add a new strategy, or select a different universe
specifically to make this result look better -- any future attempt
requires a genuinely different, independently-justified dataset or
hypothesis (e.g. the broader/less survivorship-biased universe
`docs/decisions/ADR-0034-real-data-acquisition-strategy.md` already
identified as the actual next requirement), decided before seeing its
own result, not after.

## 40-Symbol (RESEARCH_UNIVERSE Stage 2) Re-Validation

Per `docs/decisions/ADR-0036-research-universe-stage2-expansion.md`,
the universe was widened from `PILOT_UNIVERSE_V1` (16 symbols, mostly
mega-cap tech/growth) to `RESEARCH_UNIVERSE_STAGE2` (40 symbols,
sector-balanced) specifically to test whether the 16-symbol PBO=62.86%
finding above was a concentration-risk artifact rather than evidence
about the strategies themselves -- decided and documented *before* this
result existed, per RULE 0.8. The user re-ran
`scripts/run_long_horizon_validation.py --universe RESEARCH_UNIVERSE
--data-status REAL` (same 4 strategies, same 2010-01-01..2026-08-27
window, same 76-fold walk-forward config) in their own
network-enabled environment, then
`scripts/compute_pbo_dsr_from_report.py` against the resulting report,
relayed into this session and recorded here rather than fabricated:

```
PBO (Probability of Backtest Overfitting): 0.00% across 70 CSCV splits (4 candidates, 8 groups)
CANDIDATE requires PBO < 50% and Deflated Sharpe Ratio >= 95%

buy_and_hold: evidence=ROBUSTNESS_PENDING (45% positive folds, below the 60% fold-consistency bar)
long_term_momentum: evidence=ROBUSTNESS_PENDING (55% positive folds, below the 60% fold-consistency bar)
risk_controlled_momentum: evidence=ROBUSTNESS_PENDING (55% positive folds, below the 60% fold-consistency bar)
trend_volatility: evidence=ROBUSTNESS_PENDING -- 61% of 76 real folds positive (clears the
  fold-consistency bar), but Deflated Sharpe=0.93 (must be >= 0.95, FAILED); PBO=0.00 (passed).
```

**Still no strategy reaches CANDIDATE**, but the failure mode changed
in an important way: PBO across all 4 candidates dropped from 62.86%
(16-symbol) to 0.00% (40-symbol) -- the specific "picked the best of
several noisy trials" concern PBO exists to catch is essentially gone
at this breadth. `trend_volatility` is now blocked by DSR alone (0.93
vs the 0.95 bar), the closest any candidate has come to CANDIDATE in
this project's history. Per RULE 0.8, 0.93 is still a miss against a
bar fixed before this result -- it is reported as a miss, not rounded
up.

### Held-out TEST vs benchmark: PBO improving is not the same as being investable

The held-out TEST period this split produces is 2023-04-28..2026-08-27
(`chronological_split` in the report, ~3.3 years) -- a strong SPY bull
run (benchmark cumulative return **93.1%** net, CAGR ~21.8%). Against
that same window, net performance:

| Strategy | Net cumulative return | Net CAGR | Excess vs. SPY |
|---|---|---|---|
| SPY (`SPY_TOTAL_RETURN_REAL`) | 93.1% | 21.8% | -- |
| buy_and_hold | 40.4% | 10.7% | -52.7pp |
| long_term_momentum | 30.7% | 8.4% | -62.4pp |
| trend_volatility | 22.8% | 6.4% | -70.3pp |
| risk_controlled_momentum | 4.0% | 1.2% | -89.1pp |

**All 4 strategies substantially underperformed simply holding SPY
over this specific held-out window.** This is the honest, necessary
correction to reading the PBO improvement above as good news on its
own: a low PBO says a strategy's cross-validated Sharpe is probably not
an artifact of trying multiple candidates -- it says nothing about
whether that Sharpe is *large enough* to be worth trading over a passive
benchmark. Passing (or nearly passing) the PBO/DSR bar is a necessary
condition for calling a signal real, never a sufficient one for calling
it investable; this table is the concrete evidence that those are
different questions, not a restatement of the same one.

### Root-cause read on `risk_controlled_momentum`'s outsized underperformance

`risk_controlled_momentum` (4.0% net) did far worse than
`long_term_momentum` (30.7% net) despite using the *identical* momentum
score (`_momentum_score` in both `risk_controlled_momentum.py` and
`long_term_momentum.py` -- same lookback, same ranking) and the same
`top_n=5`. Reading both strategies' `generate_orders`
side by side identifies two structural, code-verifiable mechanisms,
neither of which is present in `long_term_momentum`:

1. **Inverse-volatility weights are normalized across all `top_n`
   ranked names, but only *newly-entering* names (`quantity_of(sid) ==
   0`) are ever bought** (`risk_controlled_momentum.py` lines
   140-159). When a momentum leader stays in the top 5 across several
   consecutive rebalances -- exactly what happens in a persistent,
   narrow, mega-cap-led rally like 2023-2026 -- its normalized weight
   share is "claimed" by an already-held position that is never
   topped up, so each rebalance deploys new capital against only a
   shrinking, already-small newly-entering share of the target
   weights.
2. **Weight above the 20% `max_position_weight` cap is left as
   uninvested cash, never redistributed** to other selected names
   (explicitly by design, per the module's own comment at line
   150-153). `long_term_momentum`, by contrast, has no such cap and
   deploys ~98% of available cash into whatever names it buys at each
   rebalance (`per_symbol_cash = portfolio.cash * 0.98 / len(to_buy)`)
   -- it never leaves capital structurally idle.

Both mechanisms bias toward holding cash specifically during the kind
of long, concentrated, single-theme rally this TEST window happens to
be, which plausibly explains most of the 30.7%-vs-4.0% gap between two
strategies sharing the same underlying signal.

**This is a diagnosis, not a fix.** Per RULE 0.8 and this project's
train/validation/TEST discipline, `risk_controlled_momentum`'s logic
must not be modified and re-evaluated against this same 2023-2026 TEST
window -- doing so would be post-hoc tuning against the held-out set
itself, a worse violation than tuning against train/validation. Any
future redesign of this strategy's position-sizing/cap-redistribution
logic is a new hypothesis requiring a new, not-yet-observed evaluation
window, decided on its own merits rather than as a reaction to this
result.

## Phase 32 Track A Addendum -- decomposition, classified by evidence strength

Per Phase 32's own discipline (governing instructions section 50):
every claim below is labeled OBSERVED (directly present in the report
data actually relayed into this session), INFERRED (a computation over
OBSERVED data), HYPOTHESIS (a plausible but unconfirmed explanation),
or UNKNOWN (this session's repository checkout has no real 40-symbol
report file -- `data/` is `.gitignore`d and empty here, confirmed by
direct search -- so anything needing fold-level, regime-level, or
per-security detail beyond what was already pasted into this
conversation cannot be computed here). `scripts/
analyze_long_horizon_result.py` (new this Phase) computes several of
the UNKNOWN items directly from the report file; running it and
relaying its output is the next step to close those gaps.

### E/F. Strategy performance + SPY comparison (OBSERVED, held-out TEST, net)

| Strategy | Net cum. return | Net CAGR | Sharpe | Sortino | Max DD | Turnover | Total cost | Win rate | Trades | Excess vs SPY |
|---|---|---|---|---|---|---|---|---|---|---|
| SPY benchmark | 93.09% | 21.83% | -- | -- | -19.61%(worst, `trend_volatility` window) to -18.76%(`buy_and_hold`/`long_term_momentum` window) | -- | -- | -- | -- | -- |
| buy_and_hold | 40.41% | 10.72% | 0.491 | 0.787 | -26.45% | 0.50 | $33.89 | 0.0* | 30 | -52.68pp |
| long_term_momentum | 30.67% | 8.36% | 0.457 | 0.704 | -48.47% | 7.26 | $102.79 | 0.50 | 53 | -62.42pp |
| trend_volatility | 22.78% | 6.35% | 0.367 | 0.557 | -19.61% | 9.48 | $312.96 | 0.32 | 246 | -70.31pp |
| risk_controlled_momentum | 3.99% | 1.18% | 0.328 | 0.483 | -39.40% | 7.55 | $97.57 | 0.52 | 51 | -89.10pp |

\* `buy_and_hold`'s `win_rate=0.0` is `PerformanceReport`'s existing,
correct convention for zero *closed* trades (it only ever opens
positions) -- not evidence of losing trades.

**Q1 (governing instructions section 19 / 49): is there an investable
candidate among the 4?** OBSERVED: no. Every strategy's Sharpe (0.33-
0.49) is well below what the CANDIDATE bar's DSR requirement implies
is needed for statistical confidence, and every strategy trails SPY by
53-89 percentage points over the only TEST window evaluated. None
qualifies as an investable candidate on this evidence.

### G. Signal-level analysis (Rank IC) -- OBSERVED for walk-forward TRAIN+VALIDATION; TEST-1 deliberately excluded

`scripts/compute_signal_ic_from_catalog.py`, run by the user against
the real DuckDB catalog (2010-01-01..2023-04-28, the walk-forward
TRAIN+VALIDATION region only -- `TEST_1` was correctly excluded by the
script's own hard-refusal guard, see this section's prior note for why):

```
long_term_momentum (_momentum_score, shared with risk_controlled_momentum):
  80 rebalance dates, 79 observations
  mean_ic = -0.0078
  ic_information_ratio = -0.031
  positive_ic_ratio = 51.90%
```

**OBSERVED, and this is the single most important Track A finding**:
the momentum score's rank-correlation with future returns is
essentially zero -- `mean_ic` is a hair's breadth from 0 (slightly
negative), the information ratio is near 0 (no consistent edge, in
either direction), and `positive_ic_ratio` (51.9%) is barely above the
50% a coin flip would produce. **The underlying signal used by both
`long_term_momentum` and (before its position-sizing/cap logic)
`risk_controlled_momentum` shows no real cross-sectional predictive
power over this universe and period.**

This changes how Section H's finding should be read: it is NOT that a
good signal was ruined by bad portfolio construction. INFERRED: the
signal itself appears to carry little to no genuine information, and
`risk_controlled_momentum`'s catastrophic held-out result is better
understood as a weak-to-nonexistent signal compounded further by a
portfolio-construction bug, rather than construction being the primary
cause on its own. `long_term_momentum`'s relatively less-bad held-out
result (30.67% net, still 62pp behind SPY) is then most plausibly
attributable to whatever broad long-only market exposure ("beta")
happened to be embedded in a 40-symbol, mostly-large-cap universe
during a rally -- not to any stock-picking skill from the momentum
ranking itself, since IC data does not support that ranking having any.

`trend_volatility`'s and `buy_and_hold`'s own signals were not
computed here (`_passes_filter` is a boolean trend/vol gate, not a
continuous rank score IC is defined for; `buy_and_hold` has no signal
by design) -- still UNKNOWN whether `trend_volatility`'s trend filter
specifically (as opposed to its moving-average-window bug, already
fixed) carries real information.

**Update -- both run against the real catalog, both OBSERVED, both
negative or null:**

```
low_volatility (factor_scores.low_volatility_score, 2010-01-01..2023-04-28):
  80 rebalance dates, 79 observations
  mean_ic = -0.0486
  ic_information_ratio = -0.147
  positive_ic_ratio = 45.57%

trend_volatility filter (_passes_filter, bucket_return_analysis, same window):
  160 rebalance dates, 155 with both groups present
  mean_passing_return = 0.0110   (filter-passing group)
  mean_failing_return = 0.0189   (filter-failing group)
  mean_spread = -0.0078          (passing minus failing -- NEGATIVE)
  positive_spread_ratio = 47.74%
```

**OBSERVED**: neither shows positive predictive power. The
low-volatility factor's IC is mildly negative (still small in
magnitude relative to its own noise -- 79 observations is not a large
sample -- so "no detectable edge" is the more defensible reading than
"a real anti-signal", but there is certainly no positive edge here).
`trend_volatility`'s own filter is more striking: securities it
REJECTS averaged a *higher* forward return (1.89%) than securities it
ACCEPTS (1.10%) -- the opposite of what "price above trend + low
volatility predicts continuation" claims, though `positive_spread_ratio`
(47.74%, barely below the 50% a coin flip gives) says this is closer
to "no information" than "a strong reversed signal."

**INFERRED**: this is now 3 independent, pre-committed rule-based
hypotheses tested with the same rigorous methodology (momentum,
low-volatility, trend+volatility-filter) against this specific
40-symbol universe over 2010-2023-04-28, and **none shows positive
forward-predictive power.** `trend_volatility`'s real walk-forward
fold-consistency (61% positive folds, the only one of 4 candidates to
clear that bar) is therefore better explained by broad market
exposure during a mostly-BULL walk-forward period (Section K: 54 of
76 folds were BULL-classified) than by its filter actually selecting
better-performing securities -- consistent with, and now
better-evidenced than, the earlier Q2 synthesis's structural/regime
explanation.

This does not prove no exploitable signal exists anywhere for this
universe -- it is evidence about these 3 specific, simple,
price/volume-only technical rules, nothing broader. But 3-for-3 null
results across independently-motivated hypotheses is a legitimate,
non-cherry-picked basis (no result here was searched for after seeing
a favorable one; all 3 were null or negative) to treat further
simple-technical-rule hunting on this exact dataset as having
diminishing expected value, and to weight the Q3 decision (rule-based
vs. ML) more toward ML, or toward acquiring a genuinely different data
source (fundamentals, alternative data) rather than more price-derived
technical variants of the same 3 already-tested ideas.

**Second update -- the first fundamentals-based factor, also null.**
Per the direction chosen after the 3-for-3 result above (ADR-0042:
acquire a genuinely different data source before trying ML on a
feature space already shown to carry no information), real
fundamentals data was ingested from SEC EDGAR for the same 39-symbol
universe (see ADR-0042 for the full ingestion story, including two
real bugs found and fixed along the way) and the first fundamentals
factor -- Return on Equity, a quality-factor hypothesis
(`strategy_research.factor_scores.roe_score`) -- was tested with the
identical Signal IC methodology, over the identical pre-TEST-1 window:

```
roe (factor_scores.roe_score, 2010-01-01..2023-04-28):
  80 rebalance dates, 80 observations
  mean_ic = -0.0359
  ic_information_ratio = -0.1584
  positive_ic_ratio = 46.25%
```

**OBSERVED**: mildly negative, small in magnitude relative to sample
size (80 observations) -- the same "no detectable edge" reading as
`low_volatility`'s comparable result, not "a real anti-signal."
`positive_ic_ratio` (46.25%) is close enough to the 50% coin-flip
baseline that this is unambiguously a null result, not a reversed one.

**INFERRED**: this is now **4 independent, pre-committed hypotheses
tested with the same rigorous methodology, spanning 2 genuinely
different data domains** (3 price/volume-derived: momentum,
low-volatility, trend+volatility-filter; 1 fundamentals-derived: ROE),
and all 4 are null or negative. This is meaningfully stronger evidence
than the 3-for-3 price-only result alone -- that result left open the
possibility that the whole price/volume data domain was simply
unsuitable for this universe while a different domain (fundamentals)
might still work; a first genuinely different-domain factor also
coming back null is evidence against that specific escape hatch too,
though it remains evidence about these exact 4 ideas on this exact
39-symbol large-cap universe over this exact window, not a general
claim that no signal exists anywhere. One factor from a new domain is
a much smaller sample than 3 factors from the old one -- this
conclusion is provisional on that domain's own hypothesis count in a
way the price/volume conclusion, backed by 3 independent tries, is
not.

**A caveat specific to this factor, not the others**: `roe_score` is
restricted to annual (`fiscal_period == "FY"`) figures (Section G's
own factor-scores.py docstring explains why -- avoiding a real
quarter/year period-mismatch bug), so its value updates once per
fiscal year rather than at every 2-month rebalance step this IC
computation uses. A signal that is often stale relative to its own
rebalance cadence has a structural handicap a faster-updating
price-based signal does not -- this is a genuine difference in what
was tested, not just noise, and should be weighed before concluding
"fundamentals as a domain don't work" as strongly as "these 3
price-based rules don't work" was concluded above.

**Third update -- 3 more fundamentals factors; ONE shows the first
real positive result of the entire project, with an explicit multiple-
testing caution attached.** Per the user's decision to pursue both
remaining options ("let's do both" -- more fundamentals factors and
ML), three more ratios sharing `roe_score`'s FY-restricted, point-in-
time-safe plumbing (`_fy_ratio`) were tested over the identical
window, all pre-committed before any of the three was run:

```
roa (factor_scores.roa_score, 2010-01-01..2023-04-28):
  80 rebalance dates, 80 observations
  mean_ic = -0.0053
  ic_information_ratio = -0.0222
  positive_ic_ratio = 51.25%

net_margin (factor_scores.net_margin_score, same window):
  80 rebalance dates, 79 observations
  mean_ic = 0.0238
  ic_information_ratio = 0.1000
  positive_ic_ratio = 56.96%

leverage (factor_scores.leverage_score, same window):
  80 rebalance dates, 80 observations
  mean_ic = 0.0782
  ic_information_ratio = 0.2559
  positive_ic_ratio = 61.25%
```

**OBSERVED**: `roa` is essentially zero (even smaller in magnitude
than `roe`'s own near-zero result) -- no detectable edge, the same
reading as most of this project's prior tests. `net_margin` is
mildly positive across all three metrics (positive mean_ic, positive
IR, majority of dates positive) but small. `leverage` is the
strongest result this entire project has produced across any of the 7
hypotheses tested so far -- positive on every metric, with
`positive_ic_ratio` (61.25%) and `ic_information_ratio` (0.2559)
both clearly further from their respective null baselines (50%, 0)
than anything seen before.

**INFERRED, with an explicit multiple-testing caution -- this is the
single most important methodological point of this update**: this
project has now tested **7 independent, pre-committed hypotheses**
(momentum, low-volatility, trend+volatility-filter, ROE, ROA,
net_margin, leverage). Finding 1 result out of 7 that looks
meaningfully positive is close to what pure chance alone would produce
even if NONE of the 7 carried any real signal -- this is exactly the
multiple-comparisons problem `strategy_research.pbo_dsr` and this
project's own PBO/Deflated-Sharpe-Ratio discipline exist to guard
against for full strategies, and the same caution applies here even
though this is a raw factor-IC test, not a full backtest. **`leverage`
should be read as the most promising LEAD this project has produced,
not as a validated edge** -- treating it as confirmed after seeing a
favorable result among 7 tries is precisely the kind of post-hoc
overconfidence this project's entire discipline (RULE 0.8, PBO, DSR)
exists to prevent.

What weighs somewhat in `leverage`'s favor, short of confirmation:
(1) it was one of 3 factors pre-committed as a batch before any of the
3 was run, not selected after seeing results across a larger untracked
search; (2) "low leverage" is an independently pre-existing,
economically-motivated hypothesis in the academic literature (e.g. one
of the explicit "safety" pillars in Asness, Frazzini & Pedersen 2013's
quality-minus-junk construction), not invented in reaction to a
favorable number; (3) `net_margin`'s smaller but same-direction
positive result is at least consistent with (not independent
confirmation of) a broader "financial-health/quality" theme, rather
than `leverage` being an isolated fluke among otherwise-random
directions.

What weighs against over-trusting it: (1) the 80 rebalance-date
observations are NOT 80 independent samples -- adjacent dates 2 months
apart share overlapping 60-day forward-return windows, so the
effective sample size for any significance judgment is smaller than
80; (2) no significance test or multiple-testing correction (a
Deflated Sharpe Ratio-style adjustment, or simply requiring
out-of-sample stability across sub-periods) has been applied to this
raw IC number at all; (3) `leverage` has never been evaluated as a
full strategy (rank -> top-N -> orders -> costs -> walk-forward ->
PBO/DSR) the way the original 4 candidates were -- a positive Signal
IC is a necessary, not sufficient, condition for that.

**Next step this implies, not yet done**: before treating `leverage`
as anything beyond a lead, it should go through the same rigor the
original 4 strategies did -- a real walk-forward backtest with PBO/DSR
applied, sub-period stability checks, and ideally a genuinely new
out-of-sample check rather than trusting this one pre-TEST-1 window's
number at face value. This is deliberately flagged as future work, not
executed here, to avoid exactly the "found something, immediately
declare victory" pattern this whole methodology exists to prevent.

**Fourth update -- `leverage` built as a real strategy candidate
(`LeverageStrategy`), wired into the walk-forward + PBO/DSR pipeline;
not yet run against real data.** The user chose the third of the three
forks above explicitly ("3번 으로") -- validate `leverage` through this
project's existing rigor rather than trust the raw IC number above.

`src/strategy_research/leverage_strategy.py` adds `LeverageStrategy` as
the project's 5th strategy candidate, and its first built on a
fundamentals-derived score. Portfolio construction is deliberately the
simplest one already proven correct in this codebase -- equal-weight
among newly-entering top-N names, rebalanced by elapsed calendar
months, identical to `LongTermMomentumStrategy`'s own construction --
to isolate "does the ranking signal itself carry information" from
"does a more elaborate sizing scheme help or hurt" (this project's own
`risk_controlled_momentum` bug, Section H below, is the concrete
cautionary precedent for why added complexity can obscure or fabricate
a signal's apparent quality). `scripts/run_long_horizon_validation.py`
gained an optional `--fundamentals-db-path` argument: omitted, every
pre-existing invocation runs exactly as before (4 candidates);
supplied, `leverage` joins as a 5th candidate through the identical
chronological split, walk-forward evaluation, evidence classification,
and PBO/DSR applicability check as the original 4.

A real bug surfaced during the pre-ship manual smoke test (not by any
automated test): two runs of the script with materially different
configurations (with vs. without `--fundamentals-db-path`) produced the
IDENTICAL `experiment_id`, since its hash input never captured whether
fundamentals/`leverage` were included -- fixed by adding that field to
`experiment_id`'s payload and extending `data_version` with a
fundamentals-content fingerprint, confirmed by direct execution and
now regression-tested (see ADR-0042 Decision 13 for the full account).

**This has NOT yet been run against the real 39-symbol fundamentals
catalog + the real price catalog** -- that real run, using the walk-
forward TRAIN+VALIDATION region only (TEST-1 stays locked, no override,
exactly as every other candidate's run has always respected), is the
immediate next step. Its result -- `leverage`'s evidence classification,
and whether the PBO/DSR applicability trigger condition is met with 5
candidates -- will determine whether `leverage` graduates from LEAD to
CANDIDATE, or whether the walk-forward result itself fails to
corroborate the raw Signal IC (a real, live possibility this update
does not prejudge).

**Fifth update -- real walk-forward result: `leverage` does not clear
the CANDIDATE fold-consistency bar; a real TEST-1-lock gap found and
fixed in the same round.** The user ran
`run_long_horizon_validation.py` with `--fundamentals-db-path` against
the real 39-symbol fundamentals catalog and the real price catalog:

```
buy_and_hold:              42% positive folds (64 folds) -- below 60% bar. TEST net cumret=+11.21% sharpe=0.27
long_term_momentum:        55% positive folds -- below 60% bar. TEST net cumret=+1.78% sharpe=0.20
risk_controlled_momentum:  55% positive folds -- below 60% bar. TEST net cumret=-6.91% sharpe=0.09
trend_volatility:          61% positive folds -- clears the bar, but DSR=0.9376 < 0.95 (FAILED). TEST net cumret=+4.78% sharpe=0.22
leverage:                  56% positive folds -- below 60% bar. TEST net cumret=+0.70% sharpe=0.27, DSR=0.9787
PBO: 21.43% across 70 CSCV splits (5 candidates)
```

**OBSERVED: `leverage` does NOT clear the CANDIDATE fold-consistency
bar** (56% positive folds vs. the required 60%) -- the same failure
mode as `buy_and_hold`, `long_term_momentum`, and
`risk_controlled_momentum`, never reaching the point where its
individually-computed DSR (0.9787, which would itself pass the >=0.95
bar on its own) is even evaluated against that threshold. **This is
exactly the outcome the multiple-testing caution above existed to
warn against**: a promising raw Signal IC (mean_ic=+0.0782) did not
translate into a robust edge once built into an actual walk-forward
strategy and evaluated fold-by-fold. 56% is the closest of the three
failing candidates to the 60% bar, and `leverage`'s held-out TEST
Sharpe (0.27) ties `buy_and_hold`'s for the best of the 5 on that one
metric alone -- but per this project's own discipline, a near-miss on
a bar fixed before this result is reported as a miss, not rounded up,
and no single held-out-TEST metric is sufficient evidence on its own
(see "Held-out TEST vs benchmark" above). `REAL_VALIDATION_NOT_
COMPLETED`/no-CANDIDATE remains the correct classification for all 5
candidates, `leverage` now included.

**A second, real incident, found in this same round**: the `--end
2023-12-29` value this session's own instructions gave the user was a
mistake -- `[2010-01-01, 2023-12-29]` overlaps the locked `TEST-1`
window (2023-04-28..2026-08-27), which the original 4 strategies
already observed once. `run_long_horizon_validation.py` had never
called `overlaps_any_locked_window` at all, unlike the three
Signal-IC CLI scripts, which all refuse an overlapping range outright
-- a gap ADR-0041 explicitly noted and assumed away ("none currently
builds a new split that could conflict"), an assumption this exact run
falsified. **What is and isn't compromised, precisely**: the
walk-forward folds driving the fold-consistency/PBO/DSR evidence above
are computed over TRAIN+VALIDATION = [2010-01-01, 2021-03-12),
entirely *before* TEST-1's start -- that evidence, and `leverage`'s
failure to clear the CANDIDATE bar, is NOT contaminated. Only the
"held-out TEST" cumret/sharpe/trades figures quoted above (window
[2021-03-12, 2023-12-29]) partially overlap TEST-1 for their final ~8
months and should not be read as a clean, never-before-seen
comparison. Fixed: `run_long_horizon_validation.py` now refuses (exit
1, no partial output, no override flag) any `[--start, --end]`
overlapping a locked window, mirroring the three existing Signal-IC
scripts exactly -- verified both directions against a fresh synthetic
catalog, 3 new regression tests, full suite 1989 passed. See
`ADR-0042` Decision 14 for the full account.

**Sixth update -- real walk-forward result: `ml_ols` has the
SECOND-WORST fold-consistency of all 6 candidates, despite by far the
strongest raw VALIDATION IC.** The user ran the same real walk-forward
+ PBO/DSR pipeline against `ml_ols` (the ML Research Track's first
model, see ADR-0043 Decision 3):

```
PBO: 12.86% across 70 CSCV splits (6 candidates)
buy_and_hold:              42% positive folds (60 folds) -- below 60% bar. TEST net cumret=+20.16%
ml_ols:                     53% positive folds -- below 60% bar. TEST net cumret=+55.59%, DSR=0.9999
long_term_momentum:        57% positive folds -- below 60% bar. TEST net cumret=+16.81%
risk_controlled_momentum:  57% positive folds -- below 60% bar. TEST net cumret=+8.70%
leverage:                  57% positive folds -- below 60% bar. TEST net cumret=+33.56%
trend_volatility:          60% positive folds -- clears the bar, but DSR=0.9398 < 0.95 (FAILED). TEST net cumret=+0.13%
```

**OBSERVED: `ml_ols` does NOT clear the CANDIDATE fold-consistency
bar** (53% positive folds vs. the required 60%) -- and its 53% is the
second-worst of all 6, beating only `buy_and_hold`'s 42%, despite
`ml_ols` producing by far the strongest raw VALIDATION Signal IC this
project has ever computed (mean_ic=+0.1055 vs. `leverage_score`'s own
+0.0782). This is the multiple-testing/robustness caution from the
prior update playing out a second time, more starkly: a promising raw
metric not only failed to confirm as a robust walk-forward edge, it
underperformed several strategies whose own raw Signal ICs were null.

**A genuine tension, named rather than glossed over**: `ml_ols` also
produced the BEST held-out TEST performance of all 6 candidates
(+55.59% net vs. `leverage`'s +33.56% and `buy_and_hold`'s +20.16%).
Per this report's own established reading of exactly this pattern (see
"PBO/DSR vs. held-out TEST divergence" below, first raised for
`risk_controlled_momentum`): a strong single-window TEST result paired
with weak walk-forward fold-consistency is evidence that TEST-window
result is plausibly regime-specific luck, not a confirmed structural
edge -- fold-consistency, not one window's return, is what the
CANDIDATE bar exists to measure for exactly this reason. Per RULE 0.8,
this TEST observation cannot be used to retune or re-select `ml_ols`
now that it has been seen.

`REAL_VALIDATION_NOT_COMPLETED` remains correct for all 6 candidates.
Across every hypothesis tested against real data to date -- 3
price/volume Signal ICs, 4 fundamentals-factor Signal ICs, `leverage`
as a full strategy, and now `ml_ols` as a full strategy -- zero have
reached CANDIDATE. See ADR-0043 Decision 4 for the full account.

**Seventh update -- asked whether this project's own discipline was
costing efficiency, the user requested all five identified
improvements be executed; three are built.** See ADR-0043 Decision 5
for the full account:

- A shared feature/target cache (`src/ml/ml_strategy.py`) removed the
  redundant recomputation across walk-forward folds' overlapping TRAIN
  windows -- verified to change no output, only speed -- which
  recovered enough headroom to revert `ml_ols`'s `train_window_months`
  from 36 back to the statistically preferable 60. A full 8-candidate
  synthetic smoke test then ran FASTER (55s) than the prior 6-candidate,
  36-month-window run (1m46s).
- `ml_ridge` -- a second model family, same 6 features, but with the
  ridge regularization strength chosen by chronological cross-
  validation on TRAIN, motivated directly by `ml_ols`'s real sign-
  flipped `leverage` coefficient (a multicollinearity symptom
  regularization is the standard fix for).
- `rank_average_ensemble` -- a nonparametric rank-average combination
  of `leverage_score` and `net_margin_score` (the only two factors
  with a positive raw Signal IC), a genuinely different combination
  technique from `ml_ols`/`ml_ridge`'s fitted regression.

Both new candidates are wired into `run_long_horizon_validation.py`
behind the existing `--fundamentals-db-path` gate (8 candidates total).
18 new tests, full suite: 2038 passed. **A real consequence**: with 3
model/combination approaches now evaluated side by side,
ML-RESEARCH-PROTOCOL.md section 7's model-selection multiple-
comparisons framing genuinely applies now, not just in principle --
`compute_pbo`/`compute_dsr_for_all_candidates` already treat all 8 as
one candidate pool, so no new machinery is needed, but any future
result from `ml_ridge` or `rank_average_ensemble` must be read as one
of three tries.

**Eighth update -- real result received: regularization and rank-
averaging both modestly improved fold-consistency over `ml_ols`'s own, but neither
clears the bar, and a second real `experiment_id` collision was found
in the same round.** `ml_ridge` and `rank_average_ensemble` both hit
58% positive folds (vs `ml_ols`'s 53%) -- real evidence the
instability Decision 5 targeted was reduced, still short of the
required 60%. `rank_average_ensemble` produced the WORST held-out TEST
result of any candidate this project has ever evaluated (-23.04% net)
despite reasonable fold-consistency -- the same "these two metrics
answer different questions" caution, now demonstrated in the opposite
direction from `ml_ols`'s own case. `REAL_VALIDATION_NOT_COMPLETED`
remains correct for all 8. Separately: comparing this run's printed
`experiment_id` against the prior 6-candidate run's found they were
IDENTICAL despite the candidate set changing (6->8) and `ml_ols`'s own
internal parameters changing -- a second real reproducibility gap of
the same kind ADR-0042 Decision 14 already fixed once, now fixed by
hashing the actual candidate name list. See ADR-0043 Decision 6 for
the full account.

Universe breadth and quarterly (10-Q) fundamentals -- the two
remaining improvements -- were deliberately NOT attempted this round:
both require real data decisions (a non-cherry-picked ticker-selection
rule; parser changes re-exposed to the exact collision-bug risk
ADR-0042 Decision 7 already fixed once) and real ingestion in the
user's own network-enabled environment, not something buildable inside
this session alone.

**Ninth update -- universe breadth (Stage 3) built, per the user's own
explicit direction to proceed toward completion; not yet observed
against real data.** `RESEARCH_UNIVERSE_STAGE3` (`data_infra/universe.py`)
adds 24 hand-curated symbols to Stage 2's 40, selected by a documented,
non-cherry-picked rule: closing this project's own confirmed GICS
sector gaps (Real Estate and Materials were completely absent from
Stage 2; Utilities had only 1 symbol). Every CLI script's `--universe
RESEARCH_UNIVERSE` alias now resolves to Stage 3 (64 symbols) by
default. Same hand-curation honesty discipline as every prior stage:
NOT verified real index membership, NOT survivorship-bias mitigation
-- see ADR-0044 for the full symbol list, sector rationale, and request-
budget arithmetic (24 x 2 = 48 requests, fits the confirmed 50/hour
Tiingo free-tier cap in one window). `strategy_research.locked_
windows.TEST_1`'s own comments continue to name Stage 2 specifically,
as an accurate record of what that already-observed TEST result was
actually run against -- deliberately left unchanged. **No real
ingestion for the 24 new symbols, and no backtest against Stage 3, has
happened yet** -- this update only fixes the universe definition; real
price and fundamentals ingestion for the new symbols must run in the
user's own network-enabled environment before any Stage 3 result
exists.

**Tenth update -- real Stage 3 (64-symbol) result received: first-ever
CANDIDATE, immediately undercut by its own held-out TEST result; pool
PBO rose rather than fell.** The user completed real ingestion for the
24 new symbols and ran `run_long_horizon_validation.py --universe
RESEARCH_UNIVERSE --data-status REAL` against the real 64-symbol
catalog (2010-01-01..2023-04-28). `leverage` reached
`evidence=CANDIDATE` -- the first candidate in this project's history
to clear all three walk-forward gates (60% positive folds, PBO=0.39<0.5,
DSR=0.9674>=0.95) -- but its held-out TEST result is -26.43% net, the
WORST TEST result this project has ever recorded for any candidate
(surpassing `rank_average_ensemble`'s prior -23.04% record). This is
the starkest instance yet of the "PBO/DSR vs. held-out TEST
divergence" pattern this report has tracked since `risk_controlled_
momentum`'s own case: the one candidate that cleared every robustness
gate produced the single worst TEST outcome in the pool. Separately,
`ml_ols` produced this project's best-ever TEST result (+109.10% net)
while its own fold-consistency (50%) is worse than its Stage 2 number
(53%) -- the same divergence in the opposite direction. Pool-level
PBO rose from 20.00% (Stage 2, same 8 candidates) to 38.57% (Stage 3)
-- real evidence against, not for, the hypothesis that universe
breadth alone would reduce overfitting risk (though several things
changed between the two runs at once, including fold count 76->60, so
this is not proof of causation). `REAL_VALIDATION_NOT_COMPLETED`
remains the correct overall classification -- reaching the CANDIDATE
evidence-level label is a defined statistical threshold, not a claim
of a validated, deployable edge, and this candidate's own TEST result
argues directly against treating it as one. Full account: ADR-0043
Decision 7.

**Eleventh update -- an externally-researched candidate added via
literature search, not by data-mining this project's own results.**
Asked to speed up finding a validated strategy by combining traits
from famous investors, the assistant flagged the sequential-selection
bias risk and proposed literature search instead -- pick a rule from
independently-replicated academic/practitioner research, fixed before
any result is seen, same discipline as every other candidate here. 12
candidates were researched and verified (Piotroski F-Score, Quality
Minus Junk, O'Shaughnessy Trending Value, Altman Z-Score, Graham NCAV,
Dividend Growth, Sloan Accruals, Asset Growth Anomaly, PEAD,
Value+Momentum, Shareholder Yield, 52-week High Momentum);
`asset_growth_score` (Cooper, Gulen & Schill 2008) was built first
because it is the only one testable with zero new real ingestion --
`Assets` is already one of the 5 default XBRL concepts this project
collects. Wired into `compute_fundamentals_ic_from_catalog.py` (`--score
asset_growth`) for a cheap raw-IC check first, per the user's own
explicit instruction not to add it straight into the 8-candidate
walk-forward pool until a result justifies the added multiple-testing
burden -- mirrors exactly how `leverage_score` itself graduated from
raw IC to a full `Strategy`. Full account, including why the other 11
candidates were not pursued this round: ADR-0043 Decision 8.

**Twelfth update -- a second literature-researched candidate,
`piotroski_f_score`, built the same session.** Asked to build as many
of the 12 researched candidates as feasible, Piotroski's F-Score
(2000, JAR) was chosen next as the strongest-replicated remaining one
(re-confirmed via an independent 2004-2024 out-of-sample re-test).
Unlike `asset_growth_score`, this needed real new ingestion -- 6 new
XBRL concepts (`NetCashProvidedByUsedInOperatingActivities`,
`LongTermDebtNoncurrent`, `AssetsCurrent`, `LiabilitiesCurrent`,
`CommonStockSharesOutstanding`, `CostOfGoodsAndServicesSold`), now in
`ingest_fundamentals_data.py`'s `_DEFAULT_CONCEPTS` -- verified this
costs zero additional real requests, since SEC EDGAR's company-facts
endpoint returns one company's entire filing history per request
regardless of concept count. A 0-9 composite of nine YoY quality-
improvement signals, all-or-nothing on missing data; a real,
foreseeable coverage gap is documented up front rather than found
silently later -- financial-sector filers (banks/insurers/broker-
dealers) typically report an unclassified balance sheet and will most
likely score `None` for lack of `AssetsCurrent`/`LiabilitiesCurrent`.
Wired into `compute_fundamentals_ic_from_catalog.py` (`--score
piotroski`), also deliberately NOT added to the walk-forward pool yet.
Full account: ADR-0043 Decision 9.

**Thirteenth update -- a third literature-researched candidate,
`shareholder_yield_score`, needing new IC-computation plumbing.**
Continuing the same "build as many as feasible" request, Shareholder
Yield (O'Shaughnessy; Boudoukh, Michaely, Richardson & Roberts 2007) --
dividends paid plus NET buybacks over market cap -- was built next.
Unlike every prior fundamentals factor, this needs price data too (for
market cap), which `compute_fundamentals_ic_series` structurally cannot
supply to a score function -- a new, separate function,
`compute_hybrid_ic_series`, was added instead of widening the existing
one's contract, and `compute_fundamentals_ic_from_catalog.py` now
branches to it for `--score shareholder_yield`. A deliberate design
choice, distinct from every other factor's missing-data handling: a
company with no dividends/buybacks/issuance concept filed at all scores
`0.0` (a genuine zero-payout year), not `None` -- these cash-flow line
items are only ever tagged by a filer when the activity happened, so
their total absence is not "unknown data" the way a missing
`NetIncomeLoss` would be. Market cap itself still requires both a known
price and a known share count, or the whole score is `None`. Also uses
the RAW (never `adjusted_close`) price for market cap, with a dedicated
regression test proving the distinction matters. Needs 3 more XBRL
concepts (`PaymentsOfDividends`, `PaymentsForRepurchaseOfCommonStock`,
`ProceedsFromIssuanceOfCommonStock`), same zero-extra-request
ingestion cost as Piotroski's addition. Also deliberately NOT added to
the walk-forward pool yet. Full account: ADR-0043 Decision 10.

**Fourteenth update -- three more literature-researched candidates,
all buildable with zero new real ingestion.** `sloan_accruals_score`
(Sloan 1996 -- `NetIncomeLoss - CFO`, scaled by average assets; one of
the most-replicated anomalies in the literature, unshrunk by the
Fama-French five-factor model in a 447-anomaly replication study) and
`dividend_growth_score` (a YoY change in `PaymentsOfDividends`,
structurally the mirror of `asset_growth_score` but not negated) both
need only concepts already ingested for earlier candidates. The
originally-listed "Value+Momentum combination" was built as ONE
standalone factor, `earnings_yield_score` (Basu 1977's `NetIncomeLoss /
market_cap`, the first genuine price-based valuation ratio this project
has tested), rather than the literal published rank-combination --
the momentum leg already has a real, observed null IC result on this
project's own data (mean_ic = -0.0078, Section G's own table above),
so rebuilding it now would re-test an already-null signal, and the
literal combination step needs new cross-sectional architecture this
project's per-security `score_fn` contract does not have. A follow-up
literature search beyond the original 12 candidates found nothing
worth adding: the one concrete alternative (net stock issuance /
composite equity issuance, Daniel & Titman 2006) would be highly
correlated with `shareholder_yield_score`'s own numerator, not
genuinely new information. All 3 wired into
`compute_fundamentals_ic_from_catalog.py` (`--score sloan_accruals` /
`dividend_growth` / `earnings_yield`), also deliberately NOT added to
the walk-forward pool yet. Full account: ADR-0043 Decision 11.

**Fifteenth update -- the last two non-rejected candidates, unblocked
by new cross-sectional architecture.** Asked to build the 2 candidates
that ADR-0043 Decision 8 deferred as "too complex" (Quality Minus Junk,
O'Shaughnessy Trending Value) rather than rejecting them, the precise
cause turned out to be identical for both: each needs to
cross-sectionally rank/z-score several raw metrics against the whole
universe at once, which no per-security score function can express.
Built `signal_ic.compute_universe_ic_series`/`UniverseScoreFn` once to
unblock both (`score_fn` called once per rebalance date with the full
security list, returning a dict already computed via rank-averaging).
`quality_minus_junk_score`: a deliberate 3-component simplification
(Profitability=ROE, Safety=leverage, Quality=accruals; Growth pillar
omitted) reusing already-built functions. `value_composite_score`:
5 of O'Shaughnessy's original 6 legs (EV/EBITDA excluded -- a genuine
missing-data gap, needs Cash/short-term-debt/D&A concepts never
ingested), no momentum "Trending" overlay (same reasoning as the
Fourteenth update's earnings_yield_score: momentum already has a real
null IC result on this project's data). Built 3 new supporting legs
(`book_to_market_score` -- Fama & French 1992's HML basis, arguably the
most canonical value factor in the literature; `sales_yield_score`;
`cashflow_yield_score`) alongside the already-built earnings_yield/
shareholder_yield legs. All need zero new real ingestion. Wired via a
third CLI dict (`--score quality_minus_junk` / `value_composite`),
also deliberately NOT added to the walk-forward pool yet. This closes
out every non-rejected candidate from the original 12-strategy
literature search -- 8 externally-researched candidates now built and
awaiting real raw-IC results. Full account: ADR-0043 Decision 12.

### H. Portfolio construction decomposition (PARTIAL -- OBSERVED for `risk_controlled_momentum`, UNKNOWN for the other 3)

`long_term_momentum` and `risk_controlled_momentum` share the
*identical* `_momentum_score` (same lookback, same ranking, same
`top_n=5`) -- OBSERVED via direct code comparison, not inference. Their
held-out results diverge enormously (30.67% vs. 3.99% net). INFERRED,
from reading `risk_controlled_momentum.py`'s `generate_orders`
directly (not a backtest re-run): two structural mechanisms explain
most of this gap --
(1) inverse-volatility weights are normalized across all `top_n`
ranked names, but only *newly-entering* positions are ever bought
(`quantity_of(sid) == 0`), so once a momentum leader stays in the top
5 across consecutive rebalances -- expected during a persistent,
narrow rally -- little new capital gets deployed each rebalance; (2)
weight above the 20% `max_position_weight` cap is left as uninvested
cash, never redistributed (by explicit design, per that module's own
comment). Both bias toward holding cash specifically during a
long, concentrated rally, which the 2023-2026 TEST window was. This
remains a HYPOTHESIS for the *magnitude* of the gap (a true
decomposition would need to re-run the strategy with each mechanism
isolated, which RULE 0.8 forbids against this already-observed TEST
window) but an OBSERVED, code-verified mechanism for its *direction*.

For `buy_and_hold` and `trend_volatility`, UNKNOWN whether their gap
to SPY is more attributable to signal weakness or construction --
`buy_and_hold` has no signal at all (by design, a reference baseline)
so its entire 52.68pp gap to SPY is pure portfolio-construction/
universe-composition (this 40-symbol equal-ish-weighted basket vs.
SPY's cap-weighted, mega-cap-AI-heavy composition during this specific
rally) -- INFERRED from that structural fact, not from decomposing
`trend_volatility`'s filter-driven cash exposure, which is UNKNOWN
without the fold-level filter-pass-rate data the existing report does
not expose.

### I. Transaction cost / turnover analysis (OBSERVED)

Gross-to-net degradation, computed directly from the report:

| Strategy | Turnover (held-out) | Total cost | Cost as % of initial capital |
|---|---|---|---|
| buy_and_hold | 0.50x | $33.89 | 0.34% |
| long_term_momentum | 7.26x | $102.79 | 1.03% |
| trend_volatility | 9.48x | $312.96 | **3.13%** |
| risk_controlled_momentum | 7.55x | $97.57 | 0.98% |

`trend_volatility`'s cost drag (gross 30.80% -> net 22.78%, an 8.02pp/
26% relative haircut) is the largest of the 4, driven by 246 trades
over a 3.3-year window (monthly rebalance, no position cap forcing it
to constantly enter/exit names as they cross its trend/vol filters).
OBSERVED: none of the 4 strategies' underperformance vs. SPY is
primarily a transaction-cost story -- even at 0% cost (gross), every
strategy's gross cumulative return (not separately re-tabulated here,
but visible in the original held_out_test JSON) still trails SPY's
93.09% by a wide margin. Cost is a real, measurable drag, not the
dominant explanation.

### J. Drawdown analysis -- PARTIAL

Max drawdown OBSERVED (table above). Duration/recovery-day breakdown
(`compute_drawdown_episodes`, added this session) is UNKNOWN for this
specific report -- the running process that produced it started before
that field existed in the code, so the report predates it (established
earlier this session by direct code-timeline reasoning, not assumed).
A re-run will include it automatically. `risk_controlled_momentum`'s
-39.40% max drawdown against only a 3.99% total gain is the worst
reward-to-pain ratio of the 4 -- OBSERVED, directly from the table.

### K. Regime analysis -- OBSERVED for walk-forward TRAIN+VALIDATION; still UNKNOWN for the held-out TEST result itself

Closed via `scripts/analyze_long_horizon_result.py`, run by the user
against the real report and relayed into this session. Covers the
walk-forward TRAIN+VALIDATION region only (76 folds, 2010..2023-04-28)
-- the report schema still does not attach a regime label to the
single continuous held-out TEST backtest itself, so "how did each
strategy do in a BULL regime *during the TEST window*" remains
UNKNOWN; what follows is regime-conditional performance from the
*prior*, non-overlapping walk-forward period.

| Strategy | BEAR win-rate / mean return (n=16) | BULL win-rate / mean return (n=54) | NEUTRAL win-rate / mean return (n=6) |
|---|---|---|---|
| buy_and_hold | 18.75% / -0.63% | 51.85% / 1.32% | 50.00% / 0.75% |
| long_term_momentum | 37.50% / -1.22% | 55.56% / 2.69% | 100.00% / 3.84% |
| risk_controlled_momentum | 37.50% / -0.86% | 55.56% / 1.92% | 100.00% / 3.44% |
| trend_volatility | 37.50% / -0.95% | **68.52%** / 1.15% | 50.00% / 1.81% |

OBSERVED: all 4 lose money on average in BEAR folds and make money on
average in BULL folds -- unsurprising for long-only strategies, and not
by itself informative about relative skill. `trend_volatility` has the
best BULL win-rate of the 4 (68.52%, the only one clearing the report's
own 60% fold-consistency bar overall) -- its trend/volatility filter is
doing something real at the fold level.

**INFERRED, and this is the most important new finding from this
data**: `risk_controlled_momentum`'s walk-forward BULL fold mean return
(1.92%) is *higher* than `trend_volatility`'s (1.15%) -- yet in the
held-out TEST, a single continuous ~3.3-year bull run,
`risk_controlled_momentum` returned only 3.99% net while
`trend_volatility` returned 22.78%. This divergence is consistent with,
and strengthens, the Section H HYPOTHESIS about *why*: each
walk-forward BULL fold is an independent ~2-month window, almost
certainly starting from fresh positions each time, so the "already-held
positions are never topped up, capped weight excess sits in cash"
pathology identified in `risk_controlled_momentum.py`'s code would
barely show up in short, independent folds -- but compounds severely
over one single continuous 3.3-year holding period where the same
momentum leaders persist quarter after quarter. The short-fold
walk-forward result and the long-continuous held-out result are
measuring different things for this specific strategy, not
contradicting each other.

Also OBSERVED: `trend_volatility`'s better fold-level regime profile
did NOT translate to the best held-out TEST result among the 4 (it
ranked 3rd of 4 in absolute held-out return, behind `buy_and_hold` and
`long_term_momentum`) -- its 3.13%-of-capital cost drag (Section I,
246 trades from monthly rebalancing) ate most of the advantage its
regime-conditional signal quality otherwise showed.

### L. Symbol / sector concentration -- UNKNOWN, and NOT closeable the way Section G was

The `concentration` field (`backtest.contribution`, added this
session) is absent from this report because the report predates the
code that produces it. Unlike Signal IC (Section G), there is no safe
way to close this gap against the existing report: computing
concentration needs the actual `Fill` objects from a backtest run,
which the report JSON does not persist -- the only way to get them is
re-running `run_long_horizon_validation.py`, and today's codebase
includes the ADR-0038 momentum-window fix, so re-running against the
same `--start 2010-01-01 --end 2026-08-27` would re-evaluate the
corrected strategies against the already-observed TEST-1 window --
precisely what this project's TEST-1 lock forbids. This UNKNOWN stays
open until a genuinely new TEST window exists (real future data past
2026-08-27, or a deliberately pre-registered TEST-2 per `ML-RESEARCH-
PROTOCOL.md` section 3 Option B) and a fresh run against that new
window is performed -- at which point concentration will be included
automatically, with no further code changes needed.

### M. PBO/DSR vs. held-out TEST divergence -- reinterpreted

```
                    PBO      DSR      fold_win_rate   held-out net CAGR
buy_and_hold        0.00%    0.997    45% (below bar)  10.72%
long_term_momentum  0.00%    0.994    55% (below bar)   8.36%
trend_volatility     0.00%    0.928    61% (clears bar)  6.35%
risk_controlled_mom  0.00%    0.988    55% (below bar)   1.18%
```

**Why PBO improved dramatically (62.86% -> 0.00%) while held-out TEST
performance stayed poor**, classified:

- OBSERVED: PBO answers "would the best-of-N candidates, selected by
  in-sample walk-forward performance, still look good under CSCV
  resampling" -- a question about whether the SELECTION among these 4
  candidates was itself noise-driven. It does not, and was never
  designed to, answer "does the selected candidate beat a passive
  benchmark."
- INFERRED: none of the 4 candidates' walk-forward fold Sharpe values
  are large in absolute terms (0.23-0.50 median, per the earlier PBO
  script output) -- PBO can correctly conclude "the ranking among 4
  mediocre candidates is not itself an artifact of overfitting" while
  every one of those candidates remains mediocre in absolute,
  benchmark-relative terms. Low PBO is evidence against one specific
  failure mode (selection-among-noisy-candidates), not evidence for
  investment quality.
- HYPOTHESIS: the 2023-2026 window's benchmark-relative difficulty
  (a narrow, mega-cap-AI-concentrated rally) may specifically
  disadvantage diversified, long-only, moderate-turnover rule-based
  strategies relative to a cap-weighted index -- consistent with, but
  not proven by, `buy_and_hold`'s own large gap to SPY (that gap has
  no signal/portfolio-construction complexity to blame, only universe
  composition/weighting, which points toward this being at least
  partially a structural, not strategy-specific, effect).
- UNKNOWN: whether the same 4 strategies would show a smaller gap to
  SPY in a differently-composed test window (e.g. a broader bear
  market, or a rally more evenly distributed across sectors) -- this
  project has only ever evaluated one held-out window and, per RULE
  0.8, cannot manufacture another one to check.

### Q2/Q3 (governing instructions section 19)

**Q2 -- is the failure signal, portfolio construction, risk control, or
regime?** Updated with real Signal IC data (mean_ic=-0.0078,
ic_information_ratio=-0.031, positive_ic_ratio=51.9% over 79
walk-forward observations, 2010..2023-04-28): **primarily signal.** The
momentum score `long_term_momentum` and `risk_controlled_momentum`
share shows essentially no rank-predictive power -- barely
distinguishable from a coin flip. Portfolio construction
(`risk_controlled_momentum`, code-verified) and a structural/regime
effect common to all 4 (a rally this concentrated in a handful of
mega-cap names is hard for any diversified long-only approach to
match, including the zero-complexity `buy_and_hold` baseline) both
compound a weak signal further, but are not the primary cause on their
own -- a signal with real IC would very plausibly have produced a
better held-out result even with `risk_controlled_momentum`'s
construction bug intact, or even under the same regime headwind.
`trend_volatility`'s own filter's IC was not computed (its
`_passes_filter` returns a boolean gate, not a continuous rank score --
see Section G) and remains a genuine open question; it is the one
candidate whose fold-consistency bar it clears, which is at least
consistent with (not proof of) its filter carrying more information
than the shared momentum score does.

**Q3 -- is ML research now more valuable than more rule-based
strategies? UPDATED with all 7 real results in, including the
project's first positive lead.** governance groundwork is done
(`docs/research/ML-RESEARCH-PROTOCOL.md`, `docs/decisions/
ADR-0041-test-1-lock-and-ml-research-track.md`). Evidence to date, all
against this 39-symbol universe over 2010-2023-04-28:

| Hypothesis | Domain | mean_ic / mean_spread | Read |
|---|---|---|---|
| momentum | price/volume | -0.0078 | null |
| low_volatility | price/volume | -0.0486 | null |
| trend_volatility filter | price/volume | -0.0078 | null (wrong direction) |
| roe | fundamentals | -0.0359 | null |
| roa | fundamentals | -0.0053 | null |
| net_margin | fundamentals | +0.0238 | weak positive |
| leverage | fundamentals | **+0.0782** | positive, strongest yet |

6 of 7 pre-committed, independently-motivated hypotheses are null or
negative, consistent with everything found before this update.
`leverage`'s result is the exception and the most important new fact
this update adds -- but per Section G's own detailed caution, **it
must be read as one positive result out of seven tries, not a
validated edge**: with 7 independent tests, seeing one result this
size from pure chance is not a low-probability event, no significance
or multiple-testing correction has been applied to the raw IC number,
and `leverage` has never been run through the same walk-forward/PBO/
DSR rigor the original 4 strategy candidates were. What it does do is
convert the earlier binary "does fundamentals data work at all"
question into a genuine three-way fork: (a) actual ML model
development (governance/tooling already exists), (b) more fundamentals
factors in the same vein as `net_margin`/`leverage` (financial-health/
quality-adjacent, since those are the two non-null results so far), or
(c) properly validating `leverage` itself as a candidate strategy
before doing either (a) or (b) -- since a lead this promising, if it
survives PBO/DSR and walk-forward scrutiny, could change how much
appetite there is for continuing to search versus building on what
already looks real. All three remain legitimate, not one prescribed
answer.

**Resolved -- the user chose (c)** ("3번 으로"): validate `leverage`
first, before either more fundamentals-factor search or ML. See the
"Fourth"/"Fifth" updates in Section G above for what was built
(`LeverageStrategy`, wired into `run_long_horizon_validation.py` behind
`--fundamentals-db-path`) and the real result: `leverage` does NOT
clear the CANDIDATE fold-consistency bar (56% positive folds vs. the
required 60%) -- the multiple-testing caution's warning was borne out,
not merely a hypothetical risk. 4 of 5 rule-based/fundamentals
candidates now fail even the fold-consistency bar, only
`trend_volatility` gets as far as failing DSR alone.

**Then (a) chosen**: given 8 hypotheses tested with none reaching
CANDIDATE, the user delegated the next direction to the assistant, who
recommended and began the ML Track -- see `ADR-0043-ml-first-model.md`
and `ML-RESEARCH-PROTOCOL.md` section 14 for what was built (a first
plain-OLS model combining all 6 factor scores, `src/ml/`,
`scripts/train_ml_model_from_catalog.py`).

**Real VALIDATION result received -- the strongest raw metric yet, but
built on far too little to trust alone.** The user ran it against the
real catalog:

```
VALIDATION observations=11
VALIDATION mean_ic=0.1055
VALIDATION ic_information_ratio=0.41036483171008087
VALIDATION positive_ic_ratio=81.82%
```

Stronger on every metric than `leverage_score`'s own raw IC
(mean_ic=+0.0782). **Read with at least as much caution, for
additional reasons**: only 11 observations (far fewer than
`leverage_score`'s 80), a VALIDATION window dominated by the COVID
crash/recovery (an extreme, unusual regime), and a sign flip on the
fitted `leverage` coefficient (negative here, despite a positive raw
univariate IC) suggesting multicollinearity among the correlated
profitability features. It is the first, single, pre-registered
experiment (not cherry-picked), which is a genuine point in its favor.

Consistent with how `leverage_score`'s own lead was handled: built
`MLStrategy` (`src/ml/ml_strategy.py`), a 6th strategy candidate wired
into `run_long_horizon_validation.py` behind the same
`--fundamentals-db-path` gate as `leverage`, to put this raw number
through the same walk-forward + PBO/DSR pipeline rather than trust it
directly. Building this surfaced and required fixing a real
performance problem (refitting per fold is expensive at real
walk-forward fold counts -- see ADR-0043 Decision 3 for the full
account and the fix).

**Real walk-forward result received -- the caution above was
justified.** `ml_ols` does NOT clear the CANDIDATE fold-consistency
bar (53% positive folds vs. the required 60%) -- the second-worst of
all 6 candidates, despite its raw VALIDATION IC being the strongest
this project has ever produced. It also produced the best held-out
TEST performance of the 6 (+55.59% net), a divergence this report
reads as likely regime-specific luck rather than confirmed robustness,
per the established "PBO/DSR vs. held-out TEST divergence" reading
below. See Section G's "Sixth update" and ADR-0043 Decision 4 for the
full account. Across all 9 hypotheses now tested against real data,
zero reach CANDIDATE.

### Status after this addendum

`REAL_VALIDATION_NOT_COMPLETED` remains the correct classification for
all 4 strategies. This addendum does not change that conclusion; it
sharpens it -- the concentration-risk explanation for the 16-symbol
PBO finding is now largely ruled out (PBO here is 0.00%), and the
project's own held-out discipline surfaced a second, independent
reason none of these 4 candidates should be traded with real capital
yet: none, including `trend_volatility` (the closest to CANDIDATE),
comes close to matching a passive SPY position over the one out-of-
sample window this project has ever evaluated them against. `leverage`,
the project's 5th candidate, has now been evaluated against real data
(Section G's "Fifth update") and does not clear the CANDIDATE
fold-consistency bar either -- `REAL_VALIDATION_NOT_COMPLETED` now
applies to all 5 candidates.
