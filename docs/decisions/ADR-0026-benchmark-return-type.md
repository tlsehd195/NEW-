# ADR-0026: S&P 500 Benchmark — SPY Proxy and TOTAL_RETURN Decision

## Context

`PROJECT_MASTER_PLAN_SOURCE.md`'s own stated objective is long-term
outperformance of the S&P 500 ("장기적으로 S&P 500의 수익률을 초과하는
것을 목표로"). `docs/specifications/PHASE-2-backtesting.md` section 9.3
left `BenchmarkPoint.return_type` (`PRICE_RETURN` vs `TOTAL_RETURN`)
explicitly as a **DECISION REQUIRED**, deferred because no real S&P 500
data source had been selected. `BenchmarkEngine.compute()` was already
built to handle either value correctly and simply reports whichever one
the underlying data carries — no engine change is needed regardless of
what this ADR decides.

Phase 20 selected a real (if still access-unverified) US-equity data
source (ADR-0025: Tiingo). This ADR makes the two decisions Phase 20's
instruction section 13 asks for: what index the benchmark actually
tracks, and which return type it targets.

## Decision 1 — SPY as the S&P 500 proxy

No free real S&P 500 index-level (as opposed to a specific fund/ETF)
dataset was found to be accessible from this environment (ADR-0025's
"Honest evidence-access constraint" applies identically here — every
candidate provider domain, including Tiingo's own, returned
`EGRESS_BLOCKED` this session). **SPY (the SPDR S&P 500 ETF Trust) is
adopted as the benchmark proxy**, tracked under `data_infra`/Tiingo the
same way any other pilot-universe symbol is (it is already included in
`docs/operations/MARKET-DATA-PROVIDER.md`'s 16-symbol pilot universe for
exactly this reason).

**This is explicitly not "S&P 500 = SPY"; it is a proxy with known,
material differences:**

| Limitation | Effect |
|---|---|
| Expense ratio (~0.09%/yr as of recent public fund fact sheets, Tier 2 — not independently verified this session) | SPY's total return is structurally slightly below the index's own return, by roughly the expense ratio annually. |
| Tracking difference | SPY approximates but does not exactly replicate index-level rebalancing timing; small deviations accumulate. |
| ETF vs. index structure | SPY is a tradeable security with its own bid/ask spread, creation/redemption mechanics, and (in this system) the same `TransactionCostModel` cost assumptions applied to the strategy backtest (Phase 2 spec section 9.2) — appropriate for "what a real investor could actually buy," but not identical to a frictionless index reading. |
| Dividend timing | SPY distributes dividends quarterly to shareholders; the underlying index's own total-return calculation reinvests dividends continuously/at the constituent level. The reinvestment computation in this ADR's Decision 2 reinvests at SPY's own ex-dividend dates, which is a reasonable, honestly-labeled approximation, not the index's own methodology. |

Every `BenchmarkResult`/report surfacing this comparison must describe
it as "SPY (S&P 500 proxy)," never as "S&P 500" unqualified — this
labeling requirement is binding on any Phase 20+ code or documentation
that renders a benchmark result.

## Decision 2 — target return type: TOTAL_RETURN

**Rationale:** the system's own stated success criterion is long-term
outperformance of the S&P 500's *return*. For a long-term, low-turnover
investment style (the explicit target style per Phase 20's instruction
section 16), dividends are a materially large fraction of total equity
return over multi-year horizons — a `PRICE_RETURN`-only benchmark
systematically understates what the strategy actually needs to beat,
making any "we beat the benchmark" conclusion drawn against it
unreliable and biased in the strategy's favor. That risk is
unacceptable for a benchmark whose entire purpose is an honest go/no-go
signal.

**Implementation:** `backtest/total_return.py`
(`build_total_return_benchmark_points`) reconstructs a dividend-
reinvested, split-adjusted `BenchmarkPoint` series from raw `PriceBar` +
`CorporateAction` records, using the identical `available_time`
look-ahead discipline as `data_infra.repository`/
`backtest.corporate_actions.CorporateActionApplier` elsewhere in this
codebase (defensive re-filtering to `available_time <= as_of_time`, and
propagating a *running* maximum `available_time` forward through the
series, since a total-return level on day T is a function of every
prior day's dividends/splits — see the module docstring and
`tests/backtest/test_total_return.py`'s point-in-time tests). It reuses
`backtest.corporate_actions`'s own split-ratio parsing and
`_SPLIT_TYPES`/`_DIVIDEND_TYPES` sets rather than duplicating them.

It is index-normalized to a `base_level` (default 100.0) rather than
attempting to reproduce the S&P 500's or SPY's actual historical index
value — this project has no real starting index level to anchor to
honestly, and fabricating one would violate the "never fabricate real
market data" rule. Consumers care about the *return series*, which a
normalized index expresses identically to a "real" index level would.

`BenchmarkEngine` (Phase 2, unmodified) requires no change: it already
reads `points[0].return_type` off whatever data it is given and reports
that value, rather than assuming one.

## What remains BLOCKED / NOT done this phase

Per instruction section 24 ("no fake completion"), stated explicitly:

- **No real SPY price or dividend data has been ingested.** Tiingo
  access is unverified from this environment (ADR-0025). Until it is,
  `build_total_return_benchmark_points` has no real input to run on —
  it is tested exclusively against synthetic fixtures
  (`tests/backtest/test_total_return.py`).
- **No `BenchmarkPoint` rows exist in any repository for `benchmark_id`
  `"SPY"` or `"SPY_TR"`.** `BenchmarkEngine.compute()` will correctly
  return `None` (→ `BENCHMARK_UNAVAILABLE` at the Paper Trading
  Performance Report layer, per ADR-0024/Phase 18) for any query against
  either id until real data is actually ingested and stored — this is
  the honest, structurally-enforced behavior, not a gap needing a
  workaround.
- **The interim fallback remains `PRICE_RETURN`.** If, once real Tiingo
  access is verified, dividend data for SPY turns out to be unavailable
  or unreliable before price data is, `BenchmarkEngine`'s existing
  `PRICE_RETURN` handling is fully functional as an interim, explicitly
  labeled fallback — never silently substituted for `TOTAL_RETURN`
  results.
- **The exact reinvestment-timing/tax-treatment conventions real S&P
  500 total-return index providers use (e.g. S&P DJI's own methodology)
  have not been compared against this ADR's simpler ex-dividend-date
  reinvestment model.** This is a reasonable approximation, not a
  verified match to any official total-return index methodology.

## Consequences

- Any future real ingestion of SPY data should call
  `build_total_return_benchmark_points` and persist its output via the
  existing `DataRepository`/`DuckDBDataRepository.add_benchmark_point`-
  style path (Phase 4, unmodified) — no new storage mechanism.
- Every report or comparison referencing this benchmark must say "SPY
  (S&P 500 proxy), total return, dividends reinvested via
  `backtest.total_return`" rather than an unqualified "S&P 500."
