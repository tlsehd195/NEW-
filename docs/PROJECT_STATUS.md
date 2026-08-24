# PROJECT STATUS

> 새 Claude Code 세션은 이 파일 하나만 읽어도 현재 프로젝트가 어디까지
> 진행되었는지 파악할 수 있어야 한다. 이 파일은 각 세션 종료 시 반드시
> 최신 상태로 갱신한다.

**Last Updated:** 2026-08-24
**Updated By:** Claude Code (Session 2 — Phase 1 Data Infrastructure)

---

## Current Phase

**Phase 1 — Data Infrastructure** (설계 및 참조 구현 완료, 실 데이터
provider 연동 및 영구 저장소 구현은 후속 작업)

## Current Subtask

Phase 1 Definition of Done 충족: 명세 + 4개 ADR + 도메인 모델/Data
Quality/Trading Calendar/Data Access Interface/Ingestion 참조 구현 +
14개 카테고리 테스트 전부 통과.

---

## Completed

### Session 1 (Phase 0)
- [x] Repository 조사, `PROJECT_MASTER_PLAN.md`, `docs/PROJECT_STATUS.md`,
      `docs/decisions/ADR-0001-master-architecture.md` 작성

### Session 2 (Phase 1)
- [x] Master Plan / Phase 0 문서 / ADR-0001 재검토, repository 재조사
      (충돌 없음 확인)
- [x] `docs/specifications/PHASE-1-data-infrastructure.md` 작성 (Scope,
      Architecture, Data Lifecycle, 데이터 분류, Market Price/Security
      Master/Corporate Action/Universe 스키마, Timestamp/Trading
      Calendar 설계, Data Quality Framework, Data Access Interface,
      Look-ahead Guard, Test Strategy, Provider/보안/라이선스 정책,
      완료 체크리스트)
- [x] `docs/architecture/data-catalog.md` 작성 (Phase 1 mock 데이터셋
      6종 문서화)
- [x] `docs/decisions/ADR-0002-data-storage.md` — DuckDB(+Parquet) 채택,
      SQLite/PostgreSQL/Parquet-only/object storage 대안 비교
- [x] `docs/decisions/ADR-0003-data-model.md` — SecurityMaster/PriceBar/
      CorporateAction/BenchmarkPoint/UniverseMembership/Provenance 모델
      확정
- [x] `docs/decisions/ADR-0004-point-in-time-data.md` — 4-timestamp
      원칙, `available_time` 보수적 기본값, look-ahead guard가 구조적
      으로 강제됨을 확정
- [x] `docs/decisions/ADR-0005-data-provider-strategy.md` — Phase 1은
      실제 provider를 연동하지 않고 `MockDataProvider`만 사용하기로
      결정, 향후 provider 선정 기준 명시
- [x] `pyproject.toml` (Python 3.11+, pytest, src-layout) 작성
- [x] `src/data_infra/` 패키지 구현:
      `enums.py`, `models.py`(Provenance/SecurityMaster/PriceBar/
      CorporateAction/BenchmarkPoint/UniverseMembership),
      `versioning.py`(content-hash 기반 data_version),
      `quality.py`(DataQualityFramework, 8개 체크 + 4단계 severity),
      `calendar.py`(TradingCalendar 추상화 + US/KR 최소 샘플 캘린더),
      `repository.py`(`DataRepository` Protocol +
      `InMemoryDataRepository` 참조 구현, look-ahead guard 내장),
      `provider.py`(`DataProvider` Protocol, `MockDataProvider`,
      `IngestionRunner` — retry/backoff/idempotency/partial-failure/
      checkpoint)
- [x] `tests/data/` — 14개 필수 테스트 카테고리 + Trading Calendar 보조
      테스트, 총 57개 테스트 전부 통과 (`python3 -m pytest -q`)

## In Progress

없음 (Phase 1 설계 단계는 완료). 아래 "Not Yet Implemented"는 Phase 1
스코프에서 의도적으로 제외된 항목이며, 별도 후속 작업으로 남는다.

## Blocked

없음.

## Design Decisions (이번 세션의 핵심 결정)

1. 저장 기술: **DuckDB + Parquet** (ADR-0002). 단, Phase 1 참조 구현은
   **in-memory**이며 DuckDB/Parquet 백엔드 구현 자체는 아직 하지 않음
   — `DataRepository` 인터페이스만 고정하고 실제 연결은 후속 작업으로
   명시적으로 미룸.
2. Security 식별은 ticker가 아닌 `security_id` + `SecurityMaster` 유효
   구간으로 분리 (ADR-0003).
3. `available_time`이 없는 경우 `event_time`이 아닌 `ingestion_time`으로
   보수적으로 기본 설정 (fail-closed 원칙을 데이터 가용성에도 적용,
   ADR-0004).
4. `DataRepository`의 모든 point-in-time 메서드는 `as_of_time`을 필수
   인자로 강제 — "전체 반환" 기본값이 존재하지 않도록 하여 look-ahead
   누락을 구조적으로 차단.
5. Phase 1에서는 실제 외부 데이터 provider를 연동하지 않음
   (ADR-0005). Provider 선정은 Phase 2 진입 시 별도 결정으로 미룸.

## Known Risks / Limitations (의도적으로 남겨둔 항목)

- `InMemoryDataRepository`는 참조 구현이며 영속성이 없음. DuckDB/Parquet
  백엔드 구현은 아직 없음 (ADR-0002 Consequences 참조).
- `TradingCalendar`의 US/KR 구현은 최소 샘플 휴일만 포함한 placeholder이며
  프로덕션 수준의 정확한 다년도 휴일 캘린더가 아님 (Phase 1 spec §11).
- `mock_benchmark_sp500`은 dividend 미조정(price return) 계열이며,
  실제 Phase 2 벤치마크 비교 전에 total return 처리 여부를 명시적으로
  결정해야 함 (data-catalog.md 참조).
- 실제 S&P 500 historical constituent 데이터는 수집되지 않음 —
  `get_universe(..., as_of_time=T)` 인터페이스와 mock 데이터로 survivorship
  bias 방지 설계만 검증됨.
- 실제 외부 provider 미선정 상태이므로 Phase 2(Backtesting)가 실제
  데이터로 결과를 낼 수 없음 — provider 선정이 선행 조건.

## Recent Experiments

없음. Phase 2(Backtesting)/Phase 4(Baseline Models) 이전까지는 실험이
발생하지 않는다.

## Current Model

없음 (Phase 4 Baseline Models 이전까지 모델 없음).

## Current Benchmark

미설정. Phase 2(Backtesting)에서 S&P 500 Buy & Hold를 최소 benchmark로
구현 예정. Phase 1은 `BenchmarkPoint` 모델과 `get_benchmark()` 인터페이스,
그리고 mock 벤치마크 데이터셋까지만 준비했다.

## Last Validation

`python3 -m pytest -q` — 57 passed (schema validation, OHLC invariant,
duplicate detection, timestamp, timezone, point-in-time, look-ahead,
idempotent ingestion, retry, partial failure, checkpoint recovery, data
version, as-of query, survivorship bias protection의 14개 필수 카테고리
전부 포함).

---

## Not Yet Implemented

- AI trading decision / LLM trading prompt / automatic strategy
  generation (§43 of the Phase 1 instruction — out of scope by design)
- Model training / reinforcement learning / automatic model deployment
- Toss Securities 연동, 실계좌 주문, Live Trading, 자율 매매
- 실제 외부 데이터 provider 연동 (오직 `MockDataProvider`만 존재)
- DuckDB/Parquet 실 저장소 백엔드 (ADR-0002는 결정만 기록, 구현은 후속)
- Feature Engine, Market Regime Detection, Prediction/Decision/Risk
  Engine, Order System, Trade Journal, Learning Engine 등 Phase 2 이후
  전체 모듈

---

## Next Recommended Task

1. (선택) Phase 1 follow-up: DuckDB/Parquet 백엔드 구현체를 만들어
   `InMemoryDataRepository`와 동일한 테스트를 통과시키는 작업 — Phase 2
   착수 전 또는 착수와 병행 가능.
2. **Phase 2 — Backtesting** 착수: 이 시점에 실제 데이터 provider 선정이
   `DECISION REQUIRED`로 필요해짐 (ADR-0005 §2). `docs/specifications/
   PHASE-2-backtesting.md` 작성부터 시작.
3. Phase 2 설계 시 `mock_benchmark_sp500`의 total-return 처리 여부를
   명시적으로 결정해야 함 (data-catalog.md의 known limitation 참조).

---

## 세션 이력 (Session Log)

### Session 1 — 2026-08-24 (Phase 0)
- 저장소 최초 조사 완료 (기존 코드 없음)
- Phase 0 문서 기반 수립: `PROJECT_MASTER_PLAN.md`,
  `docs/PROJECT_STATUS.md`, `docs/decisions/ADR-0001-master-architecture.md`
  생성
- 실제 투자 기능, 주문 코드, AI API 호출은 수행하지 않음

### Session 2 — 2026-08-24 (Phase 1)
- Master Plan / Phase 0 산출물 재검토, repository 재조사 (충돌 없음)
- Phase 1 명세, Data Catalog, ADR-0002~0005 작성
- `src/data_infra/` 참조 구현 (모델/품질/캘린더/저장소/provider/ingestion)
- 14개 필수 테스트 카테고리 포함 57개 테스트 작성 및 전부 통과
- 실제 AI API, Toss Securities, Live Trading은 여전히 구현하지 않음
  (지시사항 준수)
