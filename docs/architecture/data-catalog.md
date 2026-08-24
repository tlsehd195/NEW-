# Data Catalog — Phase 1

Referenced from `docs/specifications/PHASE-1-data-infrastructure.md` §18.
Lists every dataset the system knows about as of Phase 1. All entries
below are **mock/reference datasets** used to validate the Data
Infrastructure design and test suite — none is a real external data
source (see ADR-0005).

---

## `mock_ohlcv_us_equity`

| Field | Value |
|---|---|
| dataset_id | `mock_ohlcv_us_equity` |
| description | Deterministic mock daily OHLCV bars for a small set of US equity `security_id`s, used by tests and as the reference dataset for the in-memory `DataRepository` |
| source | `mock_provider_v1` (`src/data_infra/provider.py::MockDataProvider`) |
| frequency | Daily |
| coverage | A short fixed date range (see provider source for exact dates) sufficient to exercise gaps, duplicates, future-dated records, and OHLC violations |
| schema_version | 1 |
| data_version | Content-hash based; recomputed per ingestion run (§9 of Phase 1 spec) |
| quality_status | Intentionally includes both clean and flagged records so the Data Quality Framework has something to detect |
| last_updated | Set at test/dev run time (mock data is generated in-process, not persisted between runs) |
| meaning | OHLCV bar per `security_id` per trading day |
| units | Price in the security's `currency` (mock: USD); volume in shares |
| timezone | US Eastern (market-local), canonically stored as UTC per §10 of Phase 1 spec |
| timestamp semantics | `timestamp` = start of the trading session the bar represents |
| adjustment | `adjusted_close` semantics as defined in Phase 1 spec §5.2; mock data includes a case with a corporate action so adjustment behavior is testable |
| missing value policy | A gap is retained as "no record for that date" (not a null-filled record) — consumers must handle absence explicitly |
| known limitations | Not real market data; date range and instrument set are minimal by design (§1.1 of Phase 1 spec — accuracy/reproducibility prioritized over breadth) |

---

## `mock_corporate_actions_us_equity`

| Field | Value |
|---|---|
| dataset_id | `mock_corporate_actions_us_equity` |
| description | Mock corporate action events (at least one `SPLIT` and one `DIVIDEND`) for the mock OHLCV universe |
| source | `mock_provider_v1` |
| frequency | Event-driven (irregular) |
| coverage | Same date range as `mock_ohlcv_us_equity` |
| schema_version | 1 |
| data_version | Content-hash based |
| quality_status | Clean |
| last_updated | Generated in-process |
| meaning | One record per corporate action event, per `CorporateAction` model |
| units | N/A (split ratio / dividend amount encoded in event-specific fields) |
| timezone | Same convention as OHLCV |
| timestamp semantics | `event_time`, `announcement_time`, `effective_time`, `available_time` distinguished per Phase 1 spec §7 |
| adjustment | This dataset is the **source of truth** corporate actions are adjusted from — see Phase 1 spec §5.2 |
| missing value policy | N/A — sparse by nature |
| known limitations | Only two event types populated in the mock set; full event-type coverage deferred until real provider integration |

---

## `mock_security_master`

| Field | Value |
|---|---|
| dataset_id | `mock_security_master` |
| description | Mock `SecurityMaster` records including one ticker-change scenario |
| source | `mock_provider_v1` |
| frequency | Slowly changing dimension (validity intervals) |
| coverage | Covers all `security_id`s referenced by the other mock datasets |
| schema_version | 1 |
| data_version | Content-hash based |
| quality_status | Clean |
| last_updated | Generated in-process |
| meaning | Identity and status of a tradable instrument over time |
| units | N/A |
| timezone | `valid_from`/`valid_to` stored as UTC dates |
| timestamp semantics | `[valid_from, valid_to)` half-open interval; `valid_to = None` means currently valid |
| adjustment | N/A |
| missing value policy | N/A |
| known limitations | Only `EQUITY` instrument type populated |

---

## `mock_benchmark_sp500`

| Field | Value |
|---|---|
| dataset_id | `mock_benchmark_sp500` |
| description | Mock S&P 500 benchmark index level series |
| source | `mock_provider_v1` |
| frequency | Daily |
| coverage | Same date range as `mock_ohlcv_us_equity` |
| schema_version | 1 |
| data_version | Content-hash based |
| quality_status | Clean |
| last_updated | Generated in-process |
| meaning | Benchmark index level (price return series in Phase 1 mock; total-return handling deferred — see Phase 1 spec §33 of the master plan and note below) |
| units | Index points |
| timezone | US Eastern, canonicalized to UTC |
| timestamp semantics | Same as OHLCV |
| adjustment | **Not dividend-adjusted in the Phase 1 mock.** The distinction between "price return" and "total return" (dividends reinvested) must be made explicit before this dataset is used for real Phase 2 benchmark comparisons — tracked as a Phase 2 follow-up, not resolved here. |
| missing value policy | No gaps in mock data |
| known limitations | Mock data only; real S&P 500 total-return benchmark sourcing is a Phase 2 concern |

---

## `mock_universe_sp500`

| Field | Value |
|---|---|
| dataset_id | `mock_universe_sp500` |
| description | Mock historical S&P 500 membership intervals for the mock security set, including one membership change |
| source | `mock_provider_v1` |
| frequency | Slowly changing dimension |
| coverage | Same date range as `mock_ohlcv_us_equity` |
| schema_version | 1 |
| data_version | Content-hash based |
| quality_status | Clean |
| last_updated | Generated in-process |
| meaning | `(security_id, universe, valid_from, valid_to)` membership interval |
| units | N/A |
| timezone | UTC dates |
| timestamp semantics | `[valid_from, valid_to)` half-open interval |
| adjustment | N/A |
| missing value policy | N/A |
| known limitations | Not real historical S&P 500 constituent data — exists only to prove `get_universe(..., as_of_time=T)` returns different sets for different `T` (survivorship-bias protection test, Phase 1 spec §14 test 14) |
