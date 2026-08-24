# PROJECT STATUS

> 새 Claude Code 세션은 이 파일 하나만 읽어도 현재 프로젝트가 어디까지
> 진행되었는지 파악할 수 있어야 한다. 이 파일은 각 세션 종료 시 반드시
> 최신 상태로 갱신한다.

**Last Updated:** 2026-08-24
**Updated By:** Claude Code (Session 5 — Phase 4 Baseline Models + Persistent Storage)

---

## Current Phase

**Phase 4 — Baseline Models + Persistent Storage** (설계 및 참조 구현 완료)

## Current Subtask

Phase 4 Definition of Done 충족: 명세
(`docs/specifications/PHASE-4-baseline-models-and-storage.md`) + ADR-0010
+ `src/storage/`(DuckDB+Parquet 영속 저장소, DataRepository/
TradeJournalRepository/ExperimentRepository/ExperienceRepository 구현) +
`src/baseline/`(baseline runner + comparison report) 참조 구현 + Storage
8개 카테고리 + Baseline 6개 카테고리 + Integration 2개 카테고리 테스트
전부 통과. Phase 3의 DECISION REQUIRED 3건은 재검토 결과 이번 Phase에서
해결이 필요하지 않다고 판단하여 계속 이연(Phase 4 spec §19 참조, 아래
"Blocked" 섹션도 참조). 이번 세션 자체 테스트로 발견/수정한 2건의
Phase-4-내부 정합성 이슈(ExperimentTracker 공유 필요성, ExperienceRecord
dedup key)는 아래 "Design Decisions" 참조.

## Completed

### Session 1 (Phase 0)
- Repository 조사, `PROJECT_MASTER_PLAN.md`, `docs/PROJECT_STATUS.md`,
  ADR-0001 작성

### Session 2 (Phase 1)
- Data Infrastructure 설계 및 참조 구현, 57개 테스트

### Session 3 (Phase 2)
- Backtesting 설계 및 참조 구현, 82개 테스트 (Phase1+2 = 139)

### Session 4 (Phase 3)
- [x] Phase 1/2 실제 데이터 구조 재조사 (`Order`, `Fill`,
      `PortfolioView`, `Strategy`, `ExperimentRecord`, `IntegrityReport`
      시그니처 확인 — Prediction/Decision 관련 별도 interface는 아직
      존재하지 않음을 확인)
- [x] `docs/specifications/PHASE-3-trade-journal.md` 작성 (Scope,
      Architecture, Point-in-Time 원칙 적용, 데이터 모델 7종, Version
      Lineage, Trade Lifecycle, Post Trade Analysis/Counterfactual/
      Attribution의 "실제 계산 가능한 것만 계산" 원칙, Idempotency,
      Immutability+Correction, Provenance 분리, Repository 추상화,
      Phase2 연동 및 2가지 알려진 한계, Auditability 매핑, Test Plan,
      DoD)
- [x] `docs/decisions/ADR-0009-trade-journal-data-model.md` — Phase 2
      타입(Order/Fill/PortfolioView) 직접 재사용 결정, 불변성/Correction
      패턴, 두 가지 재구성 한계(portfolio_state replay, 데이터 없음
      data_version)에 대한 결정 근거
- [x] Phase 2에 **1건의 additive 변경**: `backtest.enums.OrderStatus`에
      `CANCELLED` 추가 (기존 코드/테스트 어디도 해당 enum이 5개 값으로
      exhaustive하다고 가정하지 않음을 확인 후 진행, Phase 2 기존
      139개 테스트 전부 통과 유지)
- [x] `src/trade_journal/` 패키지 구현: `enums.py`, `models.py`(7종
      frozen dataclass), `repository.py`(Protocol +
      `InMemoryTradeJournalRepository`, natural-key idempotency),
      `analysis.py`(execution_error/hold-counterfactual/execution-
      attribution — 실제 계산 가능한 것만), `experience.py`
      (`build_experience_records`), `backtest_adapter.py`
      (`ingest_backtest_result`, Phase 2를 읽기 전용으로만 사용)
- [x] `tests/trade_journal/` — 17개 필수 카테고리 + Phase2 통합 테스트,
      63개 테스트 작성 및 전부 통과
- [x] **전체 테스트 스위트 202개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63) — Phase 2 기존 테스트 무손상 확인

### Session 5 (Phase 4)
- [x] Master Plan/ADR-0001~0009/Phase 1~3 spec 재조사 (충돌 없음 확인)
- [x] `docs/specifications/PHASE-4-baseline-models-and-storage.md` 작성
- [x] `docs/decisions/ADR-0010-persistent-storage-backend.md` 작성
- [x] `src/storage/` 패키지 구현: `config.py`, `engine.py`(단일 DuckDB
      connection 라이프사이클), `schema.py`(멱등 DDL, 전 테이블),
      `parquet_layer.py`(append-only, atomic temp-file+rename 배치 쓰기),
      `serialization.py`(명시적 typed row↔dataclass 변환),
      `data_repository.py`(`DuckDBDataRepository` — Phase1
      `DataRepository` Protocol 구현 + raw payload 저장 + ingestion용
      `append_bars`/`all_bars`), `trade_journal_repository.py`
      (`DuckDBTradeJournalRepository` — Phase3 `TradeJournalRepository`
      Protocol 구현), `experiment_repository.py`(신규 `ExperimentRepository`
      Protocol + DuckDB 구현), `experience_repository.py`(신규
      `ExperienceRepository` Protocol + DuckDB 구현)
- [x] `src/baseline/` 패키지 구현: `runner.py`(`run_baseline`/
      `run_multiple_baselines` — Phase2 BacktestEngine → Phase3
      ingest_backtest_result → 영속 Experiment/Experience 저장까지 연결),
      `report.py`(벤치마크 대비 비교 리포트, ranking/winner 필드 없음)
- [x] Phase 1에 **1건의 additive 변경**: `data_infra.repository`에
      `AppendableDataRepository` Protocol 추가, `IngestionRunner`의 타입
      힌트를 concrete class에서 이 Protocol로 확장(widening) — 기존 202개
      테스트 전부 통과 확인 후 진행
- [x] `tests/storage/`(34), `tests/baseline/`(9), `tests/integration/`(8)
      — 신규 51개 테스트 작성 및 전부 통과
- [x] **전체 테스트 스위트 253개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51) — Phase 1~3 기존 테스트 무손상 확인
- [x] `pyproject.toml`에 `duckdb`/`pyarrow` 런타임 의존성 추가
- [x] `tests/conftest.py` 신설 — 각 Phase 테스트 디렉터리의 helper 모듈을
      다른 Phase 테스트 디렉터리에서도 import 가능하게 하는 순수
      추가적(additive) sys.path 설정 (기존 테스트 파일 변경 없음)

---

## In Progress

없음 (Phase 4 설계+참조구현 완료).

## Blocked

**DECISION REQUIRED 3건 누적 (Phase 2/3에서 이어짐) — 사용자 확인 필요.**
Phase 4 세션에서 세 항목 모두 재검토했으며, 셋 다 이번 Phase의 완료
조건과 무관함을 확인하여(스토리지는 값이 무엇이든 그대로 영속화만 하면
되므로) 여전히 해결하지 않고 이연한다 (Phase 4 spec §19에 재검토 근거
상세 기록):

1. (Phase 2에서 이어짐) 벤치마크 return type (PRICE_RETURN vs
   TOTAL_RETURN)
2. (Phase 3에서 이어짐) `BacktestEngine`의 per-decision `data_version`
   미노출 — Trade Journal이 결정 단위 데이터 버전을 `None`으로 기록
3. (Phase 3에서 이어짐) `BacktestResult`의 per-step corporate action
   이벤트 미노출 — Trade Journal의 `portfolio_state` 재구성이 fill 재생
   기반 근사치이며 두 fill 사이에 발생한 corporate action을 반영하지
   못함

원문은 아래 "DECISION REQUIRED — Phase 2 정밀도 개선" 섹션 참조. Phase
4 코드/테스트 자체는 이 결정들과 무관하게 정상 동작하며 구현이 차단된
것은 아니다.

## DECISION REQUIRED — Phase 2 정밀도 개선 (Phase 3에서 이어짐, 미결)

```
Problem:
Trade Journal(Phase 3)이 Phase 2의 BacktestResult만으로는 다음 두
정보를 정확히 재구성할 수 없다:
  (a) 각 개별 의사결정(Order) 시점에 어떤 data_version이 사용됐는지
      (BacktestEngine은 런 전체 집계 데이터 버전만 노출)
  (b) 두 체결(Fill) 사이에 발생한 corporate action(분할/배당) 적용
      이벤트 (BacktestResult는 최종 성과만 노출, 중간 이벤트 로그 없음)

Current Design:
DecisionSnapshot.data_version은 Phase2 소스 레코드에 대해 None으로
정직하게 기록됨 (Trade 레벨의 Fill.data_version은 정확히 보존됨).
portfolio_state는 fill들을 재생(replay)하여 재구성하며, fill에
관해서는 정확하지만 corporate action에 대해서는 정확하지 않을 수 있음
(문서화된 한계, ADR-0009). Phase 4는 이 값들을 있는 그대로(정직하게
None인 채로) 영속 저장소에 저장할 뿐, 값 자체를 재계산하거나
추정하지 않는다.

Option A:
지금 상태 유지. Phase 2/3는 이미 이 한계를 문서화했고 테스트도
전부 통과한다. 실제로 필요해지는 시점(예: Phase 9 Learning Engine이
per-decision 데이터 버전을 요구하거나, corporate action이 빈번한 실제
데이터로 전환될 때)에 재검토한다.

Option B:
BacktestEngine을 확장하여 (a) 매 주문 생성 시점에 사용된 가격 bar의
data_version을 Order 또는 별도 이벤트로 노출하고, (b) corporate
action 적용을 이벤트 로그(예: CorporateActionEvent 리스트)로
BacktestResult에 포함시킨다. Trade Journal은 이 이벤트들을 정확히
소비하도록 수정된다.

Recommendation:
Option A로 유지. 두 한계 모두 명확히 문서화되어 있고, 현재 mock 데이터
기반 테스트에서는 실질적 영향이 없다(대부분의 백테스트 시나리오가
corporate action을 자주 포함하지 않음). Phase 9(Learning) 착수 시점에
실제로 정밀한 per-decision lineage가 필요한지 재평가할 것을 권장한다.
Option B는 Phase 2 아키텍처 변경이므로 Phase 2/3/4 세션 하나에서
임의로 결정하지 않는다.

Impact:
현재 Trade Journal에서 나온 Experience Record는 data_version 필드가
비어 있으므로(None) 재현성 검증 시 trade-level(Fill.data_version)
정밀도까지만 신뢰할 수 있다. corporate action이 포함된 백테스트의
portfolio_state 스냅샷은 근사치일 수 있다. 둘 다 성능/정확성 지표
자체(realized_pnl, execution_price 등)에는 영향이 없다 — 영향은
오직 "그 순간의 재현된 컨텍스트"의 정밀도에 국한된다. Phase 4에서
이 값들은 영속 저장소에도 동일하게 정직한 상태(None 또는 근사치임을
문서화한 상태)로 저장된다 — 저장소가 정밀도 문제를 해결하지도, 악화
시키지도 않는다.
```

## Design Decisions (Phase 4 세션의 핵심 결정)

1. DuckDB 카탈로그 파일 1개(모든 relational/metadata 테이블) + Parquet
   append-only 파일(대용량 시계열 — Raw/Clean market data만) 조합.
   Benchmark처럼 시계열이지만 볼륨이 작은 데이터는 DuckDB 테이블로 유지
   (ADR-0010 §1).
2. Parquet 쓰기는 temp file + atomic rename(`os.replace`)로만 수행 —
   기존 파일을 열어 append/rewrite하지 않음. 크래시 시 반파일이 아니라
   최대 orphan temp 파일만 남음 (ADR-0010 §2).
3. Raw Market Data는 Clean Market Data와 물리적으로 분리된 별도 Parquet
   데이터셋 — Phase 1은 원래 정규화 이전 payload를 전혀 저장하지
   않았으므로 이번 Phase에서 신규로 추가 (ADR-0010 §3).
4. Idempotency는 각 데이터셋마다 natural key 기반 애플리케이션 레벨
   체크(Parquet는 쿼리 후 필터링, DuckDB 테이블은 `ON CONFLICT DO
   NOTHING` 또는 check-then-insert) — Phase 1/3가 이미 확립한 패턴을
   영속 계층까지 확장 (ADR-0010 §4).
5. Repository 추상화 완전 유지 — `DuckDBDataRepository`/
   `DuckDBTradeJournalRepository`/`DuckDBExperimentRepository`/
   `DuckDBExperienceRepository`는 기존(또는 신규) Protocol만 구현하며,
   `BacktestEngine`/`ingest_backtest_result` 등 Phase 2/3 소비자 코드는
   전혀 수정하지 않음 (ADR-0010 §5).
6. Phase 1에 **1건의 additive 변경**: `AppendableDataRepository`
   Protocol 추가 + `IngestionRunner` 타입 힌트 확장 — 기존 202개 테스트
   전부 통과 확인 후 진행 (ADR-0010 §6).
7. **(자체 테스트로 발견/수정)** `run_baseline`으로 여러 baseline을
   비교할 때는 `ExperimentTracker`를 반드시 공유해야 함 —
   `BacktestEngine`이 기본적으로 인스턴스마다 새 tracker를 생성하므로
   공유하지 않으면 두 실험이 동일한 `experiment_id`("BT-000001")로
   충돌하고, `ExperimentRepository.record()`의 멱등성 때문에 두 번째
   실험이 조용히 저장되지 않는다. `run_multiple_baselines()`가 이를
   자동으로 처리한다 (Phase 4 spec §10.1, ADR-0010 "Known correctness fix").
8. **(자체 테스트로 발견/수정)** `DuckDBExperienceRepository`는
   `ExperienceRecord.experience_id`가 아니라 `trade_id`를 dedup key로
   사용 — `build_experience_records()`의 `experience_id`는 호출 1회
   범위로만 유일함이 문서화되어 있어(전역 유일 아님), 성장하는 영속
   journal에 대해 반복 호출하면 서로 다른 trade가 같은 `experience_id`를
   재사용할 수 있고, 그 값으로 dedup하면 첫 호출 이후의 레코드가 조용히
   유실된다. 저장소가 자체 시퀀스로 전역 유일 `experience_id`를 새로
   발급한다 (Phase 4 spec §12.1, ADR-0010 "Known correctness fix").

## Known Risks / Limitations (의도적으로 남겨둔 항목)

- 실 데이터 provider 없음(ADR-0005), 벤치마크 return type 미결(위
  DECISION REQUIRED 참조) — Phase 4의 스토리지/베이스라인 구현과 무관하게
  계속 이연.
- Phase 3의 `data_version`(per-decision) 및 `portfolio_state`(corporate
  action 반영) 정밀도 한계 — 위 DECISION REQUIRED 참조. Phase 4는 이
  값을 있는 그대로 영속화할 뿐 해결하지 않는다.
- `prediction_error`, `timing_error`, `risk_estimation_error`,
  `regime_error`, `signal_error`, `market`/`sector`/`factor`/
  `selection`/`timing` attribution — 전부 `None` (Phase 5/6/8 부재).
- 명시적 `NO_TRADE` 의사결정 로깅 없음 — Phase 2 Strategy가 주문 의도를
  생성한 경우만 기록됨 (Phase 7 Decision Agent가 생기면 확장).
- Experience Record의 `reward`는 단순 `realized_return` 매핑 — 실제
  reward function 설계는 Phase 9 과제. Learning Engine 자체는 아직
  구현하지 않음(Phase 9) — 영속 Experience Dataset은 축적만 될 뿐 아직
  아무 것도 그것을 학습에 사용하지 않는다.
- DuckDB는 단일 프로세스 임베디드 엔진 — 동시 다중 writer 지원 없음
  (ADR-0002에서 이미 인지된 한계, ADR-0010에서 재확인). Phase 15/16에서
  다중 프로세스 Paper/Live 배포가 필요해지면 재검토 필요.
- Paper/Live 브로커 어댑터 없음 — Trade Journal/Experience의
  `PAPER_TRADING`/`LIVE_TRADING` provenance 분리는 저장소 레벨까지
  검증되었으나, 이를 실제로 생산할 producer는 아직 없음 (Phase 13/15/16).
- Model Registry / "왜 모델이 변경되었는가" 감사 질문 (Phase 11).
- Feature Engine, Market Regime Detection, Prediction Engine, 완전한
  Decision Agent, Position Sizing/Portfolio Risk Engine 없음 (Phase
  5-8) — Baseline 전략은 여전히 Phase 2의 단순 Strategy 인터페이스로
  직접 신호를 계산.
- Limit order, Purged K-Fold/Embargo, 5종 corporate action 처리 없음
  (Phase 2부터 이어짐).
- Simple ML baseline 미구현 — Phase 2 spec이 `Strategy` Protocol만
  예약해두었고, 이번 Phase 지시사항도 필수가 아닌 선택 사항으로 명시함.
  Buy & Hold + Simple Momentum 두 baseline으로 최소 요구사항 충족.

## Recent Experiments

없음 (실제 데이터 기반 실험 없음). Phase 4의 baseline runner는 기존
Phase 1/2/3 목 데이터셋 패턴(테스트 fixture)으로만 검증되었으며, 실
시장 데이터 기반 실험은 아직 실행되지 않았다 (실 데이터 provider가
없으므로 — ADR-0005).

## Current Model / Current Benchmark

Phase 2와 동일한 baseline 전략(Buy & Hold, Simple Momentum)과 벤치마크
엔진(S&P 500 Buy & Hold, PRICE_RETURN/TOTAL_RETURN 미결) — 변화 없음.
Phase 4는 이들을 실행/비교/영속화하는 인프라만 추가했다.

## Last Validation

`python3 -m pytest tests/ -q` — **253 passed**
(Phase 1: 57, Phase 2: 82, Phase 3: 63, Phase 4: 51). Phase 4의 51개
테스트는 Storage 8개 카테고리(persistence/restart/append/duplicate-
idempotency/immutable-records/provenance/version-lineage/corruption-
failure-handling), Baseline 6개 카테고리(deterministic-replay/
benchmark-comparison/transaction-cost/slippage/metric-correctness/
reproducibility), Integration 2개 카테고리(Backtest→Trade Journal→
Persistent Storage, Experiment→Persistent Storage)를 모두 포함한다.

---

## Not Yet Implemented

- AI trading decision / LLM API 호출 / Toss Securities / Live Trading
- 실제 외부 데이터 provider (ADR-0005 — Phase 1부터 이연)
- Limit order, Purged K-Fold/Embargo, 5종 corporate action 처리 (Phase
  2부터)
- Feature Engine, Market Regime Detection, Prediction Engine, 완전한
  Decision Agent, Position Sizing/Portfolio Risk Engine (Phase 5-8)
- 실제 Post Trade Analysis 알고리즘(prediction/timing/risk/regime/
  signal error), 실제 Performance Attribution(market/sector/factor/
  selection/timing), 모델 기반 Counterfactual — 전부 구조만 준비됨
- Paper/Live 브로커 어댑터 (Trade Journal의 `PAPER_TRADING`/
  `LIVE_TRADING` provenance를 실제로 생산할 producer 없음)
- Learning Engine (Phase 9) — 영속 Experience Dataset은 이제 존재하지만
  아직 아무 것도 그것을 소비하지 않는다
- Model Registry / "왜 모델이 변경되었는가" 감사 질문 (Phase 11)
- DuckDB 다중 프로세스 동시 writer 지원 (Phase 15/16 필요 시 재검토)

---

## Next Recommended Task

1. **DECISION REQUIRED 3건 확인**: 벤치마크 return type, per-decision
   data_version, corporate-action-aware portfolio_state 재구성 (여전히
   미결, 사용자 판단 대기).
2. **Phase 5 — Market Regime** 착수: `PROJECT_MASTER_PLAN.md` §18의
   Phase 순서를 따를 것. Phase 4가 baseline과 영속 저장소를 마련했으므로,
   이제 Feature/Regime 계층을 추가할 준비가 되어 있다.
3. Phase 9(Learning Engine) 착수 시점에 위 DECISION REQUIRED 2건(데이터
   버전/corporate action lineage)을 재평가하고, 이번 Phase가 만든
   `DuckDBExperienceRepository`를 실제로 소비하는 학습 파이프라인을
   설계.
4. 실 데이터 provider 선정(ADR-0005 기준)이 이루어지면, `data/` 아래
   실제 `StorageConfig.root_dir`를 지정하여 장기 ingestion을 시작할 수
   있다 — 이번 Phase가 그 대상 저장소를 이미 구현했다.

---

## 세션 이력 (Session Log)

### Session 1 — 2026-08-24 (Phase 0)
### Session 2 — 2026-08-24 (Phase 1)
### Session 3 — 2026-08-24 (Phase 2)

### Session 4 — 2026-08-24 (Phase 3)
- Phase 1/2 구조 재조사 (충돌 없음, Prediction/Decision interface 부재
  확인)
- Phase 3 명세, ADR-0009 작성
- Phase 2에 additive 변경 1건 (`OrderStatus.CANCELLED`) — 기존 테스트
  영향 없음 확인
- `src/trade_journal/` 참조 구현 (모델/저장소/분석/경험변환/Phase2 연동)
- 17개 카테고리 + Phase2 통합 테스트 포함 63개 테스트 작성, 전체
  202개 테스트 전부 통과
- DECISION REQUIRED 2건 신규 보고 (per-decision data_version,
  corporate-action-aware portfolio_state 재구성) — 임의 결정하지 않음
- 실제 AI API, Toss Securities, Live Trading은 여전히 구현하지 않음

### Session 5 — 2026-08-24 (Phase 4)
- Master Plan/ADR-0001~0009/Phase 1~3 spec 재조사 (충돌 없음 확인)
- Phase 4 명세, ADR-0010 작성
- Phase 1에 additive 변경 1건 (`AppendableDataRepository` Protocol) —
  기존 202개 테스트 영향 없음 확인
- `src/storage/` (DuckDB+Parquet 영속 저장소 4종 Repository 구현) +
  `src/baseline/` (baseline runner + comparison report) 참조 구현
- Storage 8개 + Baseline 6개 + Integration 2개 카테고리 포함 51개
  테스트 작성, 전체 253개 테스트 전부 통과
- 자체 테스트로 정합성 이슈 2건 발견 및 즉시 수정 (ExperimentTracker
  공유 필요성, ExperienceRecord dedup key — 위 Design Decisions 참조)
- Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
  않다고 판단, 계속 이연 (임의 결정하지 않음)
- 실제 AI API, Toss Securities, Live Trading은 여전히 구현하지 않음
