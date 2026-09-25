# ADR-0207: Wire in exchange_calendars and purgedcv (ADR-0151's deferred adoptions)

**Status:** Accepted
**Date:** 2026-09-26
**Deciders:** Claude Code session, account owner (explicit "진행해" for every item requiring no external account/key)

**Related documents:** `docs/decisions/ADR-0151-...md` (original "adopt
now, wire in later" adoption of `skfolio`/`purgedcv`/`exchange_calendars`),
`docs/decisions/ADR-0035-pbo-deflated-sharpe-implementation.md`
(`strategy_research.pbo_dsr`), `docs/decisions/ADR-0117` (`US_EQUITY_NYSE`
rule-derived calendar), `docs/decisions/ADR-0206` (the immediately
preceding "real, verified" wiring precedent this ADR follows).

## Context

An uploaded external advisory report (2026-09-26, "10th report") pointed
out that `pyproject.toml` declares three optional dependencies
(`exchange_calendars`, `purgedcv`, `skfolio`) that ADR-0151 adopted but
explicitly deferred wiring in. Its every concrete citation was verified
directly against this repository before acting on it (file:line, real
grep results, real JSON report fields) -- none were taken on faith. The
account owner then said to proceed with whatever items required no
external account/key of their own. Of the three, `skfolio` was excluded
by the report's own reasoning (no VALIDATED strategy exists yet for
portfolio-level optimization to operate on) and is left exactly as
ADR-0151 found it. This ADR covers the other two.

## Decision

### 1. `exchange_calendars` -- real holiday calendars, not hand-picked/rule-derived ones

`src/data_infra/exchange_calendars_adapter.py` (new file) implements
`data_infra.calendar.TradingCalendar` by delegating every real calendar
question to `exchange_calendars.get_calendar("XNYS"/"XKRX")` -- the
"exact swap point" ADR-0151's own comment on the Protocol already
anticipated. This is the only file in `data_infra.*` that imports
`exchange_calendars`; `data_infra.calendar` itself (the Protocol,
`SimpleTradingCalendar`, `US_EQUITY`/`KR_EQUITY`/`US_EQUITY_NYSE`) is
unmodified and still dependency-free.

**Verified directly against the real library** (2026-09-26, not assumed):
- `XKRX` correctly excludes Korean lunar holidays (Seollal 2024/2025/2026,
  Chuseok) -- the exact gap `KR_EQUITY`'s hand-picked 2-date sample
  cannot cover, since lunar holidays are not derivable from a fixed
  Gregorian rule.
- `XNYS` correctly excludes MLK Day, Juneteenth, Good Friday, Labor Day,
  Thanksgiving for 2024-2026.
- **Real, disclosed limitation**: both calendars cover a fixed, rolling
  ~21-year window (`first_session=2006-09-25`, `last_session=2027-09-24`
  as installed 2026-09-26). A date outside that window raises
  `exchange_calendars.errors.DateOutOfBounds` -- a loud, clear failure,
  never a silently wrong answer. `US_EQUITY_NYSE` (rule-derived,
  2000-2035) has no such near-term ceiling and remains available for a
  caller that needs it; this module's own docstring names the trade-off
  explicitly.

**Five real script call sites swapped** from `US_EQUITY_NYSE` to
`build_xnys_calendar()` (same `market="US_EQUITY"` injection key, so no
caller-side logic changed beyond which object is injected):
`scripts/run_paper_trading_cycle.py`,
`scripts/run_multi_strategy_paper_trading_cycle.py`,
`scripts/run_long_horizon_validation.py`,
`scripts/run_first_real_strategy_evaluation.py`,
`scripts/ingest_real_market_data.py` (the last one calls
`is_trading_day()` directly, not via `DuckDBDataRepository`, to decide
whether a zero-bar ingestion result is explainable by a market holiday --
ADR-0175's own P1-1 fix; now checks against the real calendar instead of
the rule-derived one). `US_EQUITY_NYSE` itself is untouched and still
exported -- nothing currently calls it, but it is not deleted.

**CI impact, handled**: `.github/workflows/paper_trading_cycle.yml` (the
real daily-scheduled job) and `.github/workflows/run_full_validation.yml`
now `pip install -e '.[market-calendars]'` instead of bare `pip install
-e .`, since their scripts now unconditionally import
`exchange_calendars_adapter`. `requirements-dev.txt` (the frozen
dev/test environment `session-start.sh` installs every session) gained
`exchange_calendars==4.13.2` and its own transitive dependencies
(`korean_lunar_calendar`, `pyluach`, `toolz`) -- regenerated via this
file's own documented `pip freeze` procedure and diffed to confirm
nothing else changed. Without this, `tests/scripts/test_run_monitoring_sweep.py`
(which loads `run_paper_trading_cycle.py` as a module) would break for
any future session that only installs the base `[dev]` extra.

**Real bug found and fixed while wiring this in, not left latent**: the
full test suite (3860 tests, the merge gate) initially broke 36 tests
after this swap. Root cause: `TradingCalendar.is_trading_day`'s own
Protocol signature says `day: date`, but real callers
(`backtest.clock.build_daily_checkpoints` in particular) actually pass a
timezone-AWARE `datetime` -- `datetime` is a `date` subclass, so this was
never a type error, and `SimpleTradingCalendar`'s own hand-rolled
`is_trading_day` tolerates it silently (`.weekday()` works identically on
both). `exchange_calendars` is far stricter: passing a tz-aware
`datetime` straight to `is_session()` raised `AttributeError:
'datetime.timezone' object has no attribute 'key'` from deep inside its
own timestamp parsing. Fixed with a `_calendar_date()` normalizer at
every entry point of `ExchangeCalendarsTradingCalendar` (strips
time/timezone down to the plain calendar date the caller meant) -- see
that function's own docstring for the full story, including the
separately-disclosed, pre-existing (not fixed here) implication that
`SimpleTradingCalendar`'s own `holidays: frozenset[date]` membership
check likely never matched correctly for any caller passing a `datetime`
either, just without ever raising to reveal it.

Two tests needed real updates, not relaxation, once this was fixed:
`tests/orchestration/test_run_paper_trading_cycle_cli.py`'s resume test
computed its own "expected trading days in range" using `backtest_helpers.
trading_days`' toy `US_EQUITY` default, which does not know about a real
Presidents Day (2024-02-19) the actual injected calendar now correctly
excludes -- updated to pass `calendar=build_xnys_calendar()` so the test
computes its expectation against the same calendar the script under test
actually uses. `tests/data_infra/test_ingest_real_market_data_wiring.py`'s
source-inspection test literally asserted the old `US_EQUITY_NYSE` import
string was present -- updated to assert the new
`exchange_calendars_adapter` import instead, keeping its real intent
(never silently fall back to the toy calendar) rather than dropping the
assertion.

Tests: `tests/data_infra/test_exchange_calendars_adapter.py` (16 tests,
`pytest.importorskip`-gated, every asserted holiday date confirmed
directly against the real library before being written, never guessed).

### 2. `purgedcv` -- independent PBO/DSR cross-check, scripts-only

`scripts/cross_verify_pbo_dsr_with_purgedcv.py` (new) reconstructs the
EXACT `fold_returns_by_candidate` matrix
`scripts/run_long_horizon_validation.py`'s own production code built
(same common-valid-fold-index intersection across every candidate) from
an already-committed `full-validation-*.json` report -- no new backtest
run, `src/` untouched, matching ADR-0151's own "cross-check, never
replace the in-house implementation" scoping.

**Real cross-check result, run against this project's own actual data**
(`full-validation-20260925T160732Z.json`, 51 candidates, 58 common valid
folds, `docs/research/reports/pbo_dsr_purgedcv_cross_check_20260925.json`):

- **Self-check passed**: this script's own reconstruction of the input
  matrix from the report JSON exactly reproduces the report's persisted
  `pbo_probability` (0.185714285714...), confirming the reconstruction
  logic is faithful to production.
- **DSR agrees closely**: max absolute difference 0.0014, mean 0.0005
  across all 51 candidates -- strong independent validation that
  `strategy_research.pbo_dsr.compute_dsr_for_all_candidates` correctly
  implements the Bailey & Lopez de Prado (2012/2014) formulas (confirmed
  identical between the two implementations by reading `purgedcv`'s own
  source). The small residual gap is fully explained by one disclosed
  convention difference: `purgedcv`'s default Sharpe helper uses sample
  standard deviation (`ddof=1`) where this project's own module uses
  population standard deviation (`ddof=0`).
- **PBO disagrees by a real, now-diagnosed 7.1 percentage points**
  (ours 0.1857, purgedcv 0.1143) -- root-caused to the exact source line
  in each implementation, not left as an unexplained gap: with 58 folds
  split into 8 groups (`58 = 8*7 + 2`, not evenly divisible), this
  project's `compute_pbo` puts the entire 2-fold remainder into the LAST
  group (`[7,7,7,7,7,7,7,9]`), while `purgedcv._pbo._contiguous_blocks`
  spreads the remainder across the FIRST `remainder` groups instead
  (`[8,8,7,7,7,7,7,7]`) -- confirmed by reading both implementations'
  source directly. The Bailey et al. (2015) CSCV paper assumes an evenly
  divisible fold count and specifies no remainder rule; neither
  convention is "more correct." A new regression test
  (`test_evenly_divisible_fold_count_gives_identical_pbo`) confirms the
  two implementations converge exactly once there is no remainder to
  place anywhere, isolating this as the sole cause.

**This is not treated as a bug to fix.** `compute_pbo`'s own code comment
is extended to cross-reference this finding (so a future reader does not
have to re-derive it), but the group-construction logic itself is left
unchanged -- there is no principled reason to prefer `purgedcv`'s
remainder convention over this project's own beyond "a different library
made a different arbitrary choice," and changing it now, after the
53-candidate real result was already reported and reviewed, would risk
looking like tuning the methodology after seeing an inconvenient
disagreement rather than a genuine correction.

Tests: `tests/scripts/test_cross_verify_pbo_dsr_with_purgedcv.py` (3
tests, `pytest.importorskip`-gated, synthetic small fixtures -- one
proving exact PBO convergence on an evenly-divisible fold count, one
directly reproducing the remainder-divergence structure at small scale).
`requirements-dev.txt` gained `purgedcv==0.1.6` and its transitive
dependencies (`scikit-learn`, `joblib`, `threadpoolctl`, `cloudpickle`) --
same `pip freeze`-and-diff procedure as above. No CI workflow needed a
new install line for this one (the cross-check script is not invoked by
any scheduled workflow, only run manually/on demand).

### 3. `skfolio` -- left exactly as ADR-0151 adopted it

Not wired in. The 10th report's own reasoning is adopted unchanged:
portfolio-level optimization has no validated strategy pool to operate
on yet (0 of 51 candidates `VALIDATED`, per ADR-0206's own full-validation
run), so connecting it now would have nothing real to optimize and no
way to test the connection meaningfully. Revisit when at least one
candidate reaches `VALIDATED`.

## Consequences

### Positive
- Two of ADR-0151's three deferred adoptions are now genuinely connected
  and tested, closing a real, previously-flagged gap (Korean lunar
  holidays; US ad-hoc closures) that mattered concretely for the account
  owner's own stated next step (a KIS adapter needs an accurate Korean
  trading calendar).
- Wiring in a genuinely stricter external library surfaced a real latent
  type-contract gap (`TradingCalendar.is_trading_day` silently tolerating
  a `datetime` where its own Protocol says `date`) that this project's
  own hand-rolled calendar had been masking rather than catching -- found
  by the full suite (the merge gate) actually failing, not by code
  review, and fixed before merge rather than left as a newly-introduced
  regression.
- The `purgedcv` cross-check is a real, independent validation of this
  project's own PBO/DSR implementation against a third-party library
  written from the same academic papers -- DSR agreement to within
  0.0014 is strong evidence the in-house formula is correctly
  implemented, not just internally self-consistent.
- The PBO disagreement, rather than being left as "these two tools
  don't match, use with caution," was root-caused to one specific,
  named line in each codebase and confirmed by a targeted regression
  test -- a genuinely closed investigation, not an open question.

### Negative / Trade-offs
- `exchange_calendars`' fixed ~21-year supported window (currently
  2006-09-25..2027-09-24) is a real constraint the rule-derived
  `US_EQUITY_NYSE` did not have. `run_long_horizon_validation.py`'s
  real production range (2010-01-01 onward) is comfortably inside it
  today, but this window advances only when the `market-calendars` pin
  is bumped and re-verified -- a future session must revisit this
  before the current window's ~1-year runway (as of 2026-09-26) closes.
- Two CI workflows (`paper_trading_cycle.yml`, `run_full_validation.yml`)
  now install an additional real dependency on every scheduled run --
  low risk (a pure calendar-computation library, no network calls, no
  credentials), but it is a real addition to the live daily production
  pipeline's dependency surface, not a purely additive/isolated change
  the way ADR-0206's Gemini adapter was.
- `purgedcv`'s PBO/DSR results are not a "second confirmation" a reader
  can treat as interchangeable with this project's own numbers -- the
  documented remainder-convention difference means the two will
  genuinely disagree on PBO whenever the real fold count is not evenly
  divisible by `num_groups`, which will recur on future real runs unless
  the fold count happens to land evenly.

## Tests

`tests/data_infra/test_exchange_calendars_adapter.py` (16 tests),
`tests/scripts/test_cross_verify_pbo_dsr_with_purgedcv.py` (3 tests) --
both offline/synthetic-or-already-committed-data, `pytest.importorskip`-
gated on their respective optional extras. `scripts/
cross_verify_pbo_dsr_with_purgedcv.py` was additionally run for real
against the actual committed `full-validation-20260925T160732Z.json`,
producing `docs/research/reports/pbo_dsr_purgedcv_cross_check_20260925.json`.

Full suite run before merge as the merge gate (see PR).
