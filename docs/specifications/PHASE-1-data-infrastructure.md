# PHASE 1 SPECIFICATION — Data Infrastructure

**Status:** ACTIVE (design confirmed, reference implementation in progress)
**Phase:** Phase 1 — Data Infrastructure
**Depends on:** `PROJECT_MASTER_PLAN.md`, `docs/decisions/ADR-0001-master-architecture.md`
**Produces ADRs:** ADR-0002 (storage), ADR-0003 (data model), ADR-0004
(point-in-time), ADR-0005 (provider strategy)

---

## 0. Purpose of This Document

This is the official specification for Phase 1. It exists so that any
future session — human or Claude Code — can understand exactly what the
Data Infrastructure layer is, why it is shaped this way, and what it does
and does not do, without needing conversational memory.

Phase 1 does **not** implement investment decisions or real trading. Its
purpose is to build the foundation that every later phase (Feature,
Backtest, Prediction, Decision, Risk, Trading, Trade Journal, Learning)
depends on. The two properties this phase exists to guarantee are:

1. **Point-in-time correctness** — the system can answer, for any past
   moment, exactly what data was actually available at that moment.
2. **Reproducibility / provenance** — the system can answer, for any past
   result, exactly which data version produced it.

These two properties are prerequisites for every later phase's validity.
A backtest or a trained model built on top of a data layer that cannot
guarantee these two properties is **not evaluable**, no matter how good
its metrics look (`PROJECT_MASTER_PLAN.md` §53 / this document's core
invariant, §16 below).

---

## 1. Scope

### 1.1 In scope for Phase 1

- Core data domain model: Security Master, Market Price (OHLCV) data,
  Corporate Actions, Benchmark data, and a Universe/membership concept
  that supports historical (survivorship-bias-aware) queries.
- Point-in-time metadata (`event_time`, `publication_time`,
  `available_time`, `ingestion_time`) attached to all time-sensitive
  data, and an **as-of query** contract (`as_of_time=T` returns only
  what was available at `T`).
- A **look-ahead guard**: a structural mechanism, not a convention, that
  makes it impossible for an as-of query to return data whose
  `available_time` is after the requested `as_of_time`.
- Data provenance fields (`source`, `source_dataset`,
  `source_record_id`, `retrieved_at`, `data_version`, `schema_version`).
- A Data Quality Framework: automated checks (OHLC invariants,
  duplicates, missing values, timestamp/timezone sanity, negative
  price/volume, stale data) with a severity taxonomy
  (`INFO/WARNING/ERROR/CRITICAL`) and a `DataQualityRun` record.
- A storage architecture decision (RAW / CLEAN / DERIVED layering) and
  the concrete storage technology choice, recorded as an ADR.
- A **Data Access Interface** (`DataRepository`) that isolates
  Backtest/Feature/ML code from the concrete storage implementation.
- A **Data Provider Interface** (`DataProvider`) that isolates ingestion
  logic from any specific external data vendor, plus ingestion
  reliability concerns: retry/backoff, idempotency, partial failure
  handling, and checkpointing — designed against a deterministic mock
  provider, not a real external API.
- A **Trading Calendar** abstraction (not a hardcoded "weekdays 9-15"
  rule), covering at minimum a US-market and a KR-market placeholder
  calendar.
- A minimal, in-memory **reference implementation** of the above
  interfaces, sufficient to make the design testable now (mock data,
  unit tests for all invariants listed in `PROJECT_MASTER_PLAN.md` §13.10
  and this document's §14).
- A Data Catalog concept and per-dataset documentation template.
- License/security review process for any future real data provider
  (policy only — no real provider is being contracted in Phase 1).

### 1.2 Out of scope for Phase 1 (explicitly not built here)

- AI trading decisions, LLM trading prompts, automatic strategy
  generation.
- Model training, reinforcement learning, automatic model deployment.
- Toss Securities integration, live orders, live trading, autonomous
  trading, production portfolio management.
- Any real external data provider integration (no live API keys, no
  contracted data vendor). The `DataProvider` interface and a
  deterministic `MockDataProvider` are built instead; a real adapter is
  future work once a provider is actually selected under the criteria in
  ADR-0005.
- A production-grade database deployment (replication, backup policy,
  access control beyond basic file/secret hygiene). Phase 1 selects and
  wires up a **development-appropriate** storage engine (see ADR-0002);
  operational hardening is deferred.
- Full historical S&P 500 constituent data acquisition. The
  architecture must **support** historical universe membership
  (`get_universe(..., as_of_time=T)`), but Phase 1 does not require
  actually sourcing and loading real historical constituent history —
  a mock/sample dataset is enough to prove the interface.
- Fundamental data, macro data, news data, alternative data (§5.2 of
  this document — deferred to a later phase, added only when a specific
  design decision needs them, per `PROJECT_MASTER_PLAN.md` §17.3).

---

## 2. Architecture

```
External Data Sources
        │
        ▼
┌───────────────────┐
│ Data Ingestion     │  DataProvider adapters (fetch/validate/normalize/metadata)
└─────────┬──────────┘  retry, backoff, checkpoint, idempotency, partial-failure handling
          │
          ▼
┌───────────────────┐
│ Raw Data           │  Immutable, append-only. Never overwritten in place.
└─────────┬──────────┘
          │
          ▼
┌───────────────────┐
│ Normalization      │  Canonical schema, canonical timezone (UTC), symbol resolution
└─────────┬──────────┘
          │
          ▼
┌───────────────────┐
│ Data Quality       │  DataQualityFramework: checks + severities + DataQualityRun
└─────────┬──────────┘
          │
          ▼
┌───────────────────┐
│ Clean Data         │  Validated, normalized, versioned
└─────────┬──────────┘
          │
          ▼
┌───────────────────┐
│ Derived Data        │  (Phase 5+: features, regime labels — NOT built in Phase 1;
└─────────┬──────────┘   layer is reserved so Feature Engine never writes into Clean/Raw)
          │
          ▼
┌───────────────────┐
│ Feature Layer       │  Out of scope — Phase 5+
└─────────┬──────────┘
          │
          ▼
┌───────────────────┐
│ Backtest / ML /     │  Out of scope — Phase 2+ / Phase 9+
│ Trading             │  Consumes data ONLY through DataRepository (as-of aware)
└────────────────────┘
```

### 2.1 Layer responsibilities

| Layer | Responsibility | Must NOT do |
|---|---|---|
| Data Ingestion | Call a `DataProvider`, obtain raw payloads, attach provenance metadata, hand off to Raw storage | Interpret/clean data, make trading decisions |
| Raw Data | Immutable store of exactly what was received, when | Be overwritten in place; be queried directly by Backtest/Feature code |
| Normalization | Convert provider-specific formats to the canonical domain schema (§4-8), canonicalize timestamps to UTC | Drop or silently "fix" data without recording a quality issue |
| Data Quality | Run `DataQualityFramework` checks, assign severities, produce a `DataQualityRun` | Decide trading actions; block ingestion of RAW data (RAW is always kept) |
| Clean Data | Store normalized + quality-checked data with a `data_version` | Contain features/derived values |
| Derived Data | Reserved for Phase 5+ Feature Engine output | Be written to by anything other than the (future) Feature Engine |
| `DataRepository` (Data Access Interface) | The **only** way Backtest/Feature/ML/Trade Journal/Decision Replay code reads data; enforces as-of semantics | Contain business/trading logic; be bypassed by direct storage access from consumer code |

### 2.2 Storage / Domain separation

Per `PROJECT_MASTER_PLAN.md` §19, no trading/backtest/feature code calls a
storage API directly:

```
Domain (SecurityMaster, PriceBar, CorporateAction, ...)
        ↓
DataRepository (Protocol / interface — get_bars, get_security, ...)
        ↓
Storage Implementation (Phase 1: InMemory reference impl; later: DuckDB/Parquet — ADR-0002)
```

Consumers (future Backtest engine, Feature Engine, Trade Journal replay)
depend only on the `DataRepository` interface. Swapping the in-memory
reference implementation for the real DuckDB/Parquet-backed
implementation (built later in Phase 1 follow-up work or Phase 2) must
not require any change to consumer code — this is validated by the fact
that Phase 1's own tests run entirely against the in-memory
implementation.

---

## 3. Data Lifecycle

```
DISCOVERED → INGESTED → VALIDATED → NORMALIZED → STORED → AVAILABLE
   → DERIVED → CONSUMED
```

| State | Meaning |
|---|---|
| `DISCOVERED` | The ingestion layer knows a record exists at the source (e.g., listed in a provider's response) but has not yet fetched its full content. |
| `INGESTED` | The raw payload has been fetched and persisted to the Raw layer, with `ingestion_time` and provenance recorded. |
| `VALIDATED` | The Data Quality Framework has run against the record and produced a `DataQualityRun` result (which may itself contain WARNING/ERROR entries — validation happening is distinct from validation passing cleanly). |
| `NORMALIZED` | The record has been converted into the canonical domain schema (UTC timestamps, canonical symbol identity, canonical units). |
| `STORED` | The normalized, validated record exists in the Clean layer with a `data_version`. |
| `AVAILABLE` | The record's `available_time` has been reached/recorded, meaning point-in-time queries at or after that time may return it. `STORED` and `AVAILABLE` are distinct: a record can be `STORED` in our system before the moment a real investor could have known about it (e.g., we backfill historical data today), so `AVAILABLE` is a property of the *data itself* (`available_time`), evaluated relative to a query's `as_of_time` — not a pipeline stage that happens at a fixed wall-clock moment. |
| `DERIVED` | (Phase 5+) A derived artifact (feature, label) has been computed from this record. |
| `CONSUMED` | The record has been read through `DataRepository` by a downstream system (Backtest, Feature Engine, etc.). Tracked for auditability, not enforced as a gate. |

### 3.1 Error states

| State | Meaning | Effect |
|---|---|---|
| `INGESTION_FAILED` | A `DataProvider.fetch()` call failed (network, auth, rate limit, malformed response) for one or more records. | Record(s) marked failed; ingestion run reports `PARTIAL_SUCCESS` or `FAILED` (§12); other symbols/records in the same run are unaffected. |
| `QUALITY_REJECTED` | A record fails a `CRITICAL`-severity quality check (§13). | Record is **not** promoted from Raw to Clean. Raw copy is still retained (§17 Raw Immutability). |
| `QUALITY_FLAGGED` | A record has `WARNING`/`ERROR` severity findings but is not `CRITICAL`. | Record is promoted to Clean but carries its `DataQualityRun` reference so consumers can inspect/filter on quality status. |
| `SUPERSEDED` | A later-arriving correction/restatement replaces this record's derived meaning (e.g., a corrected close price). | The old version is **not deleted** (§17); a new `data_version` is created and the repository query layer resolves "current" vs "as originally reported" based on caller intent. |

---

## 4. Data Classification

Phase 1 implements the domain model for:

1. **Market Price Data** (OHLCV bars)
2. **Volume Data** (part of the OHLCV bar, not a separate dataset)
3. **Corporate Action Data**
4. **Security Master**
5. **Benchmark Data**

Reserved for future phases, **not implemented now** (interfaces are not
even stubbed, to avoid speculative design — `PROJECT_MASTER_PLAN.md`
§17.3, "정의되지 않은 미래 요구사항을 위해 설계하지 않는다"):

6. Fundamental Data
7. Macro Data
8. News Data
9. Alternative Data

---

## 5. Market Price Data (OHLCV)

### 5.1 Schema (conceptual — see `src/data_infra/models.py::PriceBar` for the
authoritative type-hinted definition)

Required:

```
security_id       # not a raw ticker string — see Security Master (§7)
timestamp         # tz-aware; bar's period-start convention, see §10
open, high, low, close
volume
source
data_version
schema_version
ingestion_time
available_time
```

Optional / where applicable:

```
adjusted_close     # see §5.2 — adjustment semantics must be explicit
vwap
trade_count
currency
exchange
```

### 5.2 "Adjusted price" — explicit semantics

`adjusted_close` (when present) means: the close price adjusted for
**dividends and splits that occurred after this bar's date, calculated
as of the adjustment's `retrieved_at`**, using the standard "back-adjust
from present" convention. This field is **provider-dependent and
mutable** — the same historical bar's `adjusted_close` can legitimately
change over time as new corporate actions occur after it. This is why:

- `adjusted_close` is stored **alongside**, never **instead of**, the raw
  unadjusted `close`.
- Every stored `adjusted_close` carries its own `retrieved_at` /
  `data_version`, because "the adjusted close for 2020-01-02 as computed
  in 2020" and "the adjusted close for 2020-01-02 as computed in 2026"
  are different, reproducibility-relevant values.
- **Using `adjusted_close` does not mean corporate-action handling is
  solved.** A provider's adjustment factor is itself a derived
  computation that can be wrong, delayed, or based on incomplete
  corporate-action data. Phase 1 tracks Corporate Actions (§6) as
  first-class, separately versioned data specifically so that
  adjustment logic is auditable and reproducible rather than trusted
  blindly from a vendor field.

### 5.3 OHLC invariants (enforced by the Data Quality Framework, §13)

```
high >= max(open, close)
low  <= min(open, close)
high >= low
volume >= 0
open, high, low, close > 0   (a price of exactly 0 or negative is invalid for equities)
```

---

## 6. Security Master

Security identity is **not** a single ticker string. Minimum fields:

```
security_id       # stable internal identifier, survives ticker changes
ticker
exchange
currency
company_id
instrument_type    # enum, e.g. EQUITY (Phase 1 scope; others reserved)
valid_from
valid_to           # null/None while currently valid
status             # ACTIVE | DELISTED | RENAMED | MERGED
```

This lets a ticker change (`FB` → `META`) or a delisting be represented
as a new `SecurityMaster` validity interval rather than silently
overwriting history. `PriceBar` and other time series reference
`security_id`, not a bare ticker, specifically so historical bars remain
correctly attributable even after a ticker changes.

---

## 7. Corporate Actions

Minimum event types modeled (`CorporateActionType` enum): `SPLIT`,
`REVERSE_SPLIT`, `DIVIDEND`, `SPECIAL_DIVIDEND`, `MERGER`, `ACQUISITION`,
`SPIN_OFF`, `TICKER_CHANGE`, `DELISTING`.

Each event record carries, where applicable:

```
event_time          # when the underlying corporate event actually happens
announcement_time    # when it was first publicly announced
effective_time       # when it takes effect for price/quantity adjustment
available_time       # when OUR system could have known about it
```

`available_time` is the field the look-ahead guard (§15) uses — the same
principle as for price data. A split announced on day X but effective on
day Y must not be usable by a decision simulated at any time before
`available_time`.

---

## 8. Survivorship Bias / Universe

The architecture supports historical universe membership without
requiring Phase 1 to populate real historical S&P 500 constituent data:

```python
get_universe(market="US", universe="SP500", as_of_time=T) -> list[security_id]
```

`UniverseMembership` records (`security_id, universe, valid_from,
valid_to`) let the same interface return different constituent sets for
different `as_of_time` values. Phase 1 ships this as a query capability
over a small mock/sample membership dataset (used in tests, §14) to
prove that "take today's S&P 500 list and assume it always existed" is
structurally impossible with this interface — callers cannot get an
answer without specifying `as_of_time`, and the reference
implementation only returns memberships whose `[valid_from, valid_to)`
interval contains that time.

---

## 9. Provenance

Every Clean-layer record carries:

```
source              # e.g. "mock_provider_v1" in Phase 1; a real vendor id later
source_dataset
source_record_id
retrieved_at
data_version
schema_version
```

`DatasetVersion` additionally tracks a content hash (`hashlib.sha256`
over the canonicalized record) so two ingestion runs that fetch
identical content produce a verifiably identical `data_version`, and any
actual content change is detectable even if the provider does not
expose its own versioning.

---

## 10. Timestamp Design

- All internal timestamps are **timezone-aware** (`datetime` with a
  non-`None` `tzinfo`). A naive `datetime` anywhere in the domain model
  is treated as a schema validation failure (§13), not silently assumed
  to be UTC.
- **UTC is the canonical storage representation** for every timestamp
  field.
- Market-local time (e.g., US Eastern for NYSE/NASDAQ bars, KST for a
  KRX-listed instrument accessed via Toss in a later phase) is derived
  from the `TradingCalendar`'s declared timezone for that market, never
  hardcoded per-record.
- A `PriceBar.timestamp` denotes the **start** of the bar's period
  (e.g., a daily bar dated `2024-03-15` in US Eastern represents the
  2024-03-15 US regular trading session; consumers must not assume it
  means "as of local midnight UTC").
- US-market data (relevant to the S&P 500 benchmark) and any
  Korea-market data (relevant to a future Toss Securities integration,
  Phase 13) are never implicitly mixed in one query without an explicit
  market/timezone parameter — this is enforced by requiring
  `TradingCalendar` selection to be explicit in every calendar-aware
  query.

---

## 11. Trading Calendar

`TradingCalendar` is an abstraction, not a "weekdays 9-15" rule:

```
market
timezone
open_time
close_time
holidays            # set[date]
early_close         # dict[date, time]
late_open           # dict[date, time]
```

Phase 1 ships two **minimal, explicitly-limited** concrete calendars
(`US_EQUITY` and `KR_EQUITY`) with a small hardcoded holiday sample for
the mock data's date range, clearly documented as a placeholder — **not**
a production-accurate holiday calendar. Sourcing an authoritative,
multi-year holiday calendar is deferred (candidate for Phase 2 or a
dedicated follow-up) and is out of scope for Phase 1's Definition of
Done; what Phase 1 guarantees is that the *interface* is calendar-aware
so no later code hardcodes trading-day assumptions inline.

---

## 12. Data Access Interface

```python
class DataRepository(Protocol):
    def get_bars(self, security_id, start, end, as_of_time) -> list[PriceBar]: ...
    def get_security(self, security_id, as_of_time) -> SecurityMaster | None: ...
    def get_corporate_actions(self, security_id, start, end, as_of_time) -> list[CorporateAction]: ...
    def get_trading_calendar(self, market) -> TradingCalendar: ...
    def get_benchmark(self, benchmark_id, start, end, as_of_time) -> list[BenchmarkPoint]: ...
    def get_universe(self, market, universe, as_of_time) -> list[str]: ...
```

Every data-returning method takes `as_of_time` (except
`get_trading_calendar`, which is not point-in-time-sensitive data).
This is a deliberate API design choice: a caller **cannot forget** to
specify as-of semantics, because there is no overload that omits it.
Phase 1 ships `InMemoryDataRepository`, a reference implementation used
by the test suite; a persistent-storage-backed implementation (per
ADR-0002) is follow-up work that must satisfy the exact same Protocol
and pass the exact same test suite unmodified.

---

## 13. Data Quality Framework

### 13.1 Checks implemented in Phase 1

- Missing required fields
- Duplicate records (same `security_id` + `timestamp` + `source`)
- Invalid/naive timestamps
- OHLC consistency (§5.3 invariants)
- Negative or zero price
- Negative volume
- Impossible price movement (a single-bar move beyond a configurable
  extreme threshold, flagged not rejected — see severities below)
- Stale data (no new bar for a security beyond an expected update
  interval, given its `TradingCalendar`)
- Symbol/security mismatch (a record referencing an unknown
  `security_id`)
- Timezone mismatch (a naive or unexpected-offset timestamp)

Source mismatch and cross-provider reconciliation checks are noted as a
**known limitation** deferred to when a second real provider actually
exists (§1.2) — a single-provider Phase 1 has nothing to reconcile
against yet.

### 13.2 Severity taxonomy

| Severity | Example | Effect on promotion Raw→Clean |
|---|---|---|
| `INFO` | A field outside the required set is absent | No effect |
| `WARNING` | A single missing observation in an otherwise-continuous series | Promoted, flagged |
| `ERROR` | OHLC logical inconsistency on one record (e.g. `high < low`) | That record not promoted; sibling records in the same run unaffected |
| `CRITICAL` | Systematic failure — e.g., an entire day's data for a whole market ingested with a corrupted schema, or a majority of records in a run fail OHLC invariants | Entire ingestion run's promotion halted; requires investigation before Clean-layer promotion resumes |

### 13.3 `DataQualityRun`

```
validation_id     # "DQ-000001" style, monotonic
dataset
data_version
timestamp
checks            # list of checks executed
warnings
errors
critical_errors
status            # PASSED | PASSED_WITH_WARNINGS | FAILED | CRITICAL_FAILURE
```

---

## 14. Test Strategy

Phase 1's Definition of Done requires all of the following test
categories to exist and pass against the reference (in-memory)
implementation, per `PROJECT_MASTER_PLAN.md` §13.10 and the Phase 1
initialization instruction:

1. Schema validation
2. OHLC invariant
3. Duplicate detection
4. Timestamp (tz-aware requirement, ordering)
5. Timezone (canonicalization to UTC, market-local derivation)
6. Point-in-Time (`available_time` semantics)
7. Look-ahead guard (`as_of_time` < `available_time` ⇒ excluded)
8. Idempotent ingestion (re-running ingestion does not duplicate records)
9. Retry (transient provider failure recovers within retry policy)
10. Partial failure (`N-1` of `N` symbols succeed ⇒ `PARTIAL_SUCCESS`,
    failed symbol + reason recorded)
11. Checkpoint recovery (an ingestion run resumed from a checkpoint does
    not re-fetch already-ingested records)
12. Data version (identical content ⇒ identical `data_version`;
    changed content ⇒ new `data_version`, old one retained)
13. As-of query (a query at time `T1` and a later query at time `T2 > T1`
    for the same historical window return different results if data was
    restated/added in between, while both remain internally consistent
    with what was available at their respective query times)
14. Survivorship bias protection (`get_universe` at two different
    `as_of_time` values against the mock membership dataset returns
    different constituent sets)

Property-based testing (`hypothesis`, if added as a dev dependency) is
considered for OHLC invariants and timestamp ordering only, per
`PROJECT_MASTER_PLAN.md` §38 ("반드시 필요한 곳에만 사용한다") — Phase 1
does not require it if example-based tests already give confidence; see
ADR-0002/implementation notes for the final call.

### 14.1 Mock data

No test calls a real external API. `MockDataProvider` (§ src/data_infra/provider.py)
serves a fixed, deterministic dataset including: normal bars, a
missing-bar gap, a duplicate bar, a bar dated in the future relative to
the mock "current time", a bar violating OHLC invariants, a
naive-timestamp bar, and a scenario where one of several requested
symbols fails to fetch (for partial-failure testing).

---

## 15. Look-ahead Guard

The guard is structural, implemented at the `InMemoryDataRepository`
query boundary: every as-of-aware method filters out any record whose
`available_time > as_of_time` **before** returning results — callers
cannot opt out of this filter. This directly implements
`PROJECT_MASTER_PLAN.md`'s core invariant (§16/§50 of the master plan):
"as of time T, only data actually available at T is returned."

`DATA_EXISTS` (a record is present in Clean storage) and
`DATA_AVAILABLE` (a record's `available_time <= as_of_time` for a given
query) are deliberately different predicates — the repository layer
only ever exposes the second one to callers; there is no method that
returns "everything regardless of `as_of_time`" (except explicit
catalog/admin inspection tooling, which is not the `DataRepository`
consumer path).

---

## 16. The Core Invariant This Phase Exists to Satisfy

> "2024년 3월 15일 오전 10시에 AI가 의사결정을 내렸다고 할 때, 그
> 시점에 실제로 이용할 수 있었던 데이터만 정확히 가져올 수 있는가?"
> → **YES**, via `DataRepository.get_bars(..., as_of_time=T)` and the
> look-ahead guard (§15).
>
> "2024년 3월 15일의 백테스트 결과가 2026년에 데이터를 다시 받아도
> 어떤 데이터 버전으로 계산되었는지 추적할 수 있는가?"
> → **YES**, via `data_version` + `DatasetVersion` content hashing (§9)
> and Raw-layer immutability (§17).

Both are validated directly by the test suite (§14, tests 6, 7, 12, 13).

---

## 17. Raw Data Immutability

Raw-layer records are never deleted or overwritten. A correction
(`SUPERSEDED`, §3.1) creates a new `data_version` in the Clean layer;
the original Raw payload remains queryable for audit/reproducibility.
The in-memory reference implementation models this by storing Raw
records in an append-only structure keyed by `(source_record_id,
retrieved_at)`, never by an overwritable primary key alone.

---

## 18. Data Catalog & Documentation

Each dataset registered in Phase 1 (currently: mock OHLCV, mock
corporate actions, mock security master, mock benchmark, mock universe
membership) is documented with:

```
dataset_id, description, source, frequency, coverage, schema_version,
data_version, quality_status, last_updated
```

Per-dataset documentation additionally records: meaning, source, units,
frequency, timezone, timestamp semantics, adjustment methodology,
missing-value policy, and known limitations — see
`docs/architecture/data-catalog.md` (created alongside this
specification) for the Phase 1 dataset entries.

---

## 19. Provider Strategy (summary — full reasoning in ADR-0005)

Phase 1 does **not** integrate a real external data provider. Only the
`DataProvider` interface and `MockDataProvider` are built. This is
intentional: `PROJECT_MASTER_PLAN.md` §40 requires provider selection to
weigh official documentation, rate limits, licensing, historical
coverage, point-in-time capability, adjusted-data semantics, cost, and
stability before adoption — none of which has been done yet, and "free"
alone is explicitly an invalid reason to adopt a provider as core
infrastructure. Selecting a real provider is deferred to a dedicated
decision (tracked as a `DECISION REQUIRED` candidate whenever Phase 2
Backtesting needs real historical data — see §21 Master Plan Interaction
below).

---

## 20. Security & Licensing Policy

- No provider API keys exist in this phase (none are needed — only the
  mock provider is used). `.env.example` already documents the naming
  convention (`MARKET_DATA_API_KEY`, unset) for when a real provider is
  chosen.
- When a real provider is evaluated, its license terms (commercial use,
  redistribution, storage/retention limits, API usage limits) must be
  explicitly recorded. Any term that is unclear is recorded as
  `UNKNOWN` and treated as a blocking condition — the provider is not
  adopted for storage/redistribution-sensitive use until clarified
  (`PROJECT_MASTER_PLAN.md` §41).

---

## 21. Interaction with the Master Plan

No conflicts were found between this specification and
`PROJECT_MASTER_PLAN.md` / ADR-0001. This specification is a refinement
(adds concrete schemas, interfaces, and a storage choice) within the
boundaries the master plan already set (Raw/Clean/Derived layering §2.5,
Point-in-Time §2.2/§16, Provenance §2.3, module boundaries §3 of the
master plan). Any future divergence must be raised as `DECISION
REQUIRED` per master plan §19.1, not resolved silently.

---

## 22. Definition of Done for Phase 1 (design stage)

- [x] Master Plan reviewed
- [x] Repository re-inspected
- [x] This specification written
- [x] Data Architecture defined (§2)
- [x] Data Model defined (§5-8)
- [x] Storage decision made + ADR-0002
- [x] Point-in-time design + ADR-0004
- [x] As-of query design (§12, §15)
- [x] Look-ahead guard design (§15)
- [x] Data Quality design (§13)
- [x] Data Versioning design (§9)
- [x] Provenance design (§9)
- [x] Ingestion Interface design (§ src/data_infra/provider.py)
- [x] Data Access Interface design (§12)
- [x] Mock Dataset strategy (§14.1)
- [x] Test strategy (§14)
- [x] Survivorship bias design (§8)
- [x] Benchmark structure (§5, `BenchmarkPoint` model)
- [x] S&P 500 Universe structure (§8)
- [x] Security policy reviewed (§20)
- [x] License policy reviewed (§20)
- [ ] `docs/PROJECT_STATUS.md` updated (tracked as this session's final
      step)
- [ ] Design + reference implementation committed to git (tracked as
      this session's final step)

Full implementation-level checklist (code + tests existing and passing)
is tracked in `docs/PROJECT_STATUS.md` under Phase 1.
