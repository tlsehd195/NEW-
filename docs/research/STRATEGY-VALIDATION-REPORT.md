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
