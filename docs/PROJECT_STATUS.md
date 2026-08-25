# PROJECT STATUS

> 새 Claude Code 세션은 이 파일 하나만 읽어도 현재 프로젝트가 어디까지
> 진행되었는지 파악할 수 있어야 한다. 이 파일은 각 세션 종료 시 반드시
> 최신 상태로 갱신한다.

**Last Updated:** 2026-08-25
**Updated By:** Claude Code (Session 9 — Phase 8 Position Sizing + Portfolio Risk Engine)

---

## Current Phase

**Phase 8 — Position Sizing + Portfolio Risk Engine** (설계 및 참조 구현 완료)

## Current Subtask

Phase 8 착수 전 **Git/Branch Integrity Check를 먼저 수행**(사용자 지시,
이전 세션 PASS 결과를 재사용하지 않고 현재 HEAD 기준으로 처음부터
재검증) — 결과 PASS(단일 선형 히스토리, main/wvscwe 모두 현재 HEAD의
조상, Phase 0~7 전부 포함 확인, 389/389 테스트 통과, working tree
clean). 검증 통과 후 Phase 8 Definition of Done 충족: 명세
(`docs/specifications/PHASE-8-position-sizing-and-risk.md`) + ADR-0014 +
`src/risk/`(DeterministicPositionSizer — Decision+Prediction+Regime+
Portfolio State를 결합해 target_weight/target_quantity를 계산하는
deterministic 규칙, DeterministicPortfolioRiskEngine — 포트폴리오 수준
hard limit을 독립적으로 재검사하는 최종 권한자, PositionSizingResult/
RiskCheckedPosition, PositionSizingRepository/RiskRepository) +
`src/storage/risk_repository.py`(Phase 4 저장소 확장) 참조 구현 + 신규
94개 테스트 전부 통과. Phase 3의 DECISION REQUIRED 3건은 이번 Phase에서도
재검토 결과 해결이 필요하지 않다고 판단하여 계속 이연(Phase 8 spec §20
참조, 아래 "Blocked" 섹션도 참조). 커밋 후 최종 HEAD 기준으로 Git
Integrity Check를 다시 한 번 수행하여 완료 보고에 반영한다(사용자의
명시적 반복 지시).

## Completed (Session 9 — Phase 8)

- [x] **Git/Branch Integrity Check 선행 수행 — 이전 세션 PASS를 재사용
      하지 않고 현재 HEAD(`6a1c937`, Phase 7)부터 처음부터 재검증**
      (사용자 지시) — Phase 0~7 커밋 10개를 `merge-base --is-ancestor`로
      개별 조상 확인, 병합 커밋 0개, `origin/main` 대비 main에만 있는
      커밋 0개/현재 branch에만 있는 커밋 9개, `wvscwe` 대비 wvscwe에만
      있는 커밋 0개/현재 branch에만 있는 커밋 4개, working tree clean,
      389/389 테스트 통과 확인 → **PASS 판정 후 Phase 8 착수**
- [x] Master Plan/ADR-0001~0013/Phase 1~7 spec/현재 src·tests 재조사
      (충돌 없음 확인, DECISION REQUIRED 신규 발생 없음)
- [x] `docs/specifications/PHASE-8-position-sizing-and-risk.md` 작성
      (Git Integrity Check 결과를 §0에 포함, Position Sizing/Risk Engine
      규칙 표, 구조적 경계, fail-closed 원칙, lineage, persistence,
      21개 섹션)
- [x] `docs/decisions/ADR-0014-position-sizing-and-risk-engine.md` 작성
      (12개 결정 사항 + alternatives considered + consequences)
- [x] `src/risk/` 패키지 구현: `enums.py`(RiskCheckStatus — PASS/REDUCE/
      REJECT/UNKNOWN, Position Sizing과 Risk Engine이 공유하는 단일
      vocabulary), `config.py`(PositionSizingConfig/RiskConfig — 모든
      threshold configuration으로 분리, 잘못된 값은 `__post_init__`에서
      즉시 raise), `models.py`(PositionSizingResult/PortfolioRiskState/
      RiskCheckedPosition — order_id/broker_order/execution_price 등
      order-shaped 필드 구조적으로 없음, target_weight/target_quantity는
      이 계층의 권한 있는 출력), `sizing.py`(PositionSizer Protocol +
      DeterministicPositionSizer — confidence/volatility/liquidity/cash/
      risk_budget을 반영한 14단계 순차 fail-closed 규칙, decision의
      target_weight_hint는 어디서도 읽지 않음), `engine.py`
      (PortfolioRiskEngine Protocol + DeterministicPortfolioRiskEngine —
      cash_minimum→single_position_limit→gross_exposure→concentration→
      drawdown→portfolio_volatility→turnover→liquidity 순서로 재검사하는
      최종 권한자, "설정 안 됨(None)"과 "설정됐지만 데이터 없음(fail-closed
      REJECT)"을 명확히 구분), `repository.py`(PositionSizingRepository/
      RiskRepository Protocol + InMemory 구현, natural-key idempotency,
      as_of 조회)
- [x] `src/storage/risk_repository.py`(DuckDBPositionSizingRepository/
      DuckDBRiskRepository) + `schema.py`/`serialization.py`에
      `position_sizing_results`/`risk_assessments` 테이블(risk_state는
      별도 테이블 없이 payload_json에 내장)/직렬화 추가 — 기존 테이블
      스키마 변경 없음
- [x] Phase 1~7 소스코드 변경 없음(Phase 8은 `schema.py`/
      `serialization.py`에 대한 순수 추가만 있으며 — `git diff | grep
      '^-'` 결과 두 파일 모두 삭제/변경 없음으로 확인 — 그 외
      Phase 1~7 코드 전혀 수정하지 않음)
- [x] `tests/risk/`(85: sizing 36 + engine 31 + boundary 11 + leakage 3 +
      backtest-integration 4) + `tests/storage/test_risk_repository.py`(6)
      + `tests/integration/test_risk_lineage.py`(3) — 신규 94개 테스트
      작성 및 전부 통과 (파일명 충돌 없음 — 처음부터 phase-prefixed
      이름으로 작성)
- [x] **전체 테스트 스위트 483개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57 + Phase6 39 + Phase7 40 +
      Phase8 94) — Phase 1~7 기존 테스트 무손상 확인
- [x] Position Sizing/Risk Engine이 주문/브로커/execution_price를 만들지
      않음을 구조적으로 검증 (`test_risk_boundary.py` —
      `dataclasses.fields()`/`inspect.signature()` reflection으로 확인,
      Phase 7 DecisionOutput/BaselineRuleDecisionAgent의 경계도 재확인)
- [x] 미래 데이터 유출 방지 회귀 테스트 (`test_risk_point_in_time.py`)
      — 미래 bar 추가 후 과거 시점 Sizing/Risk 결과를 Regime→Prediction→
      Decision→Sizing→Risk 전체 체인으로 재계산해도 결과가 동일함을 확인
- [x] Phase 5 Regime → Phase 6 Prediction → Phase 7 Decision → Phase 8
      Sizing/Risk 전체 체인을 실제 `BacktestEngine` 루프 안에서 순수
      관찰자로 구동해도 기존 전략의 체결 결과가 전혀 변하지 않음을 확인
      (`test_risk_backtest_integration.py`)
- [x] **Phase 2 현금 소진(cost-exhaustion) 버그 회귀 테스트 신규 작성**
      (`TestCashSafetyRegression`) — `BuyAndHoldStrategy.
      COST_SAFETY_MARGIN`과 동일한 목적의
      `PositionSizingConfig.cost_safety_margin`을 도입해, 완전히 사이즈된
      포지션도 거래비용을 위한 현금 여유를 항상 남김을 직접 검증
- [x] Sizing/Risk 5-way SQL join으로 lineage 증명
      (`position_sizing_results`↔`risk_assessments`↔`decision_outputs`↔
      `predictions`↔`regime_composites`, 한 DuckDB 카탈로그) —
      `attach_sizing_context`/`attach_risk_context`는 Phase 7과 동일한
      이유로 의도적으로 만들지 않음(Phase 8 spec §15, ADR-0013 §9 참조)

## Completed (Session 8 — Phase 7)

- [x] **Git/Branch Integrity Check 선행 수행 — 이전 세션 PASS를 재사용
      하지 않고 현재 HEAD(`6c0b0f6`, Phase 6)부터 처음부터 재검증**
      (사용자 지시) — `git log --graph --all`, `merge-base`,
      `is-ancestor`로 Phase 0~6 커밋 전부(9개) 개별 조상 확인, 병합
      커밋 0개, `origin/main` 대비 main에만 있는 커밋 0개/현재
      branch에만 있는 커밋 8개, working tree clean, 349/349 테스트
      통과 확인 → **PASS 판정 후 Phase 7 착수**
- [x] Master Plan/ADR-0001~0012/Phase 1~6 spec/현재 src·tests 재조사
      (충돌 없음 확인, DECISION REQUIRED 신규 발생 없음)
- [x] `docs/specifications/PHASE-7-decision-agent.md` 작성 (Git
      Integrity Check 결과를 §0에 포함, Decision Rules 표, 구조적
      경계, lineage, persistence, 15개 섹션)
- [x] `docs/decisions/ADR-0013-decision-agent.md` 작성 (9개 결정 사항
      + alternatives considered + consequences)
- [x] `src/decision/` 패키지 구현: `config.py`(DecisionConfig — 모든
      threshold configuration으로 분리), `models.py`(DecisionOutput —
      `trade_journal.enums.DecisionAction` 재사용, quantity/order_id/
      broker_order/execution_price 등 order-shaped 필드 구조적으로
      없음, frozen dataclass), `agent.py`(DecisionAgent Protocol +
      `BaselineRuleDecisionAgent` — prediction 필수/regime은 존재할
      때만 gate/portfolio_state None이면 fail-closed NO_TRADE의 6단계
      순차 규칙), `repository.py`(DecisionRepository Protocol +
      InMemoryDecisionRepository, natural-key idempotency, as_of 조회)
- [x] `src/storage/decision_repository.py`(DuckDBDecisionRepository) +
      `schema.py`/`serialization.py`에 `decision_outputs` 테이블(Trade
      Journal의 기존 `decisions` 테이블과 명칭 충돌 회피)/직렬화 추가 —
      기존 테이블 스키마 변경 없음
- [x] Phase 1~6 소스코드 변경 없음(Phase 7은 `schema.py`/
      `serialization.py`에 대한 순수 추가만 있으며 — `git diff | grep
      '^-'` 결과 두 파일 모두 삭제/변경 없음으로 확인 — 그 외
      Phase 1~6 코드 전혀 수정하지 않음)
- [x] `tests/decision/`(32) + `tests/storage/test_decision_repository.py`(5)
      + `tests/integration/test_decision_lineage.py`(3) — 신규 40개
      테스트 작성 및 전부 통과 (파일명 충돌 방지를 위해
      `test_boundary.py`를 `test_decision_boundary.py`로 명명)
- [x] **전체 테스트 스위트 389개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57 + Phase6 39 + Phase7 40) —
      Phase 1~6 기존 테스트 무손상 확인
- [x] Decision Agent가 quantity/order/broker/risk-bypass를 만들지
      않음을 구조적으로 검증 (`test_decision_boundary.py` —
      `dataclasses.fields()`/`inspect.signature()` reflection으로
      DecisionOutput/decide()에 금지 필드·파라미터가 없음을 확인)
- [x] 미래 데이터 유출 방지 회귀 테스트 (`test_decision_point_in_time.py`)
      — 미래 bar 추가 후 과거 시점 Decision을 재계산해도 결과가
      바이트 단위로 동일함을 확인
- [x] Phase 5 Regime → Phase 6 Prediction → Phase 7 Decision 전체
      체인을 실제 `BacktestEngine` 루프 안에서 순수 관찰자로 구동해도
      기존 전략의 체결 결과가 전혀 변하지 않음을 확인
      (`test_decision_backtest_integration.py`)
- [x] Decision↔Prediction↔Regime lineage를 Phase 3
      `build_experience_records`를 수정하지 않고 3-way SQL join으로
      증명 (`ExperienceRecord.action`이 이미 실제 체결 결과를 담고
      있어 hypothetical Decision으로 덮어쓰면 사실과 가설이 혼동되기
      때문에 `attach_decision_context`는 의도적으로 만들지 않음,
      ADR-0013 §9)

## Completed (Session 7 — Phase 6)

- [x] **Git/Branch Integrity Check 선행 수행** (사용자 지시) — 현재
      branch(`claude/phase-4-baseline-storage-tuavwk`)의 HEAD(d386420,
      Phase 5)부터 시작해 `git log --graph --all`, `merge-base`,
      `is-ancestor`로 검증: 단일 선형 히스토리(Initial commit → Phase 0
      → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5), `origin/main`과
      `origin/claude/autonomous-ai-investment-system-wvscwe` 둘 다 현재
      HEAD의 진짜 조상이며 두 branch 모두 HEAD에 없는 커밋이 0개, 병합/
      분기/reset/force-push 흔적 없음, 모든 Phase 산출물(`docs/specifications/
      PHASE-{1..5}*`, ADR 11개, `src/{data_infra,backtest,trade_journal,
      storage,baseline,regime}/`) 실존 확인, 310/310 테스트 통과, working
      tree clean → **PASS 판정 후 Phase 6 착수**
- [x] Master Plan/ADR-0001~0011/Phase 1~5 spec/현재 src·tests 재조사
      (충돌 없음 확인)
- [x] `docs/specifications/PHASE-6-prediction.md` 작성 (Git Integrity
      Check 결과를 §0에 포함)
- [x] `docs/decisions/ADR-0012-prediction-layer.md` 작성
- [x] `src/predict/` 패키지 구현: `enums.py`(PredictionMethodType —
      DETERMINISTIC_BASELINE/MODEL_BASED 명시적 구분), `config.py`
      (PredictionConfig), `models.py`(PredictionOutput — order/risk-shaped
      필드 구조적으로 없음, frozen dataclass), `predictor.py`
      (Predictor Protocol + `RandomWalkPredictor`(null hypothesis,
      데이터 조회 없음) + `DriftPredictor`(trailing mean return 외삽 +
      realized vol persistence) + `RegimeAwarePredictor`(Phase5 Regime을
      입력으로 사용하는 예시, alpha 주장 없음)), `repository.py`
      (PredictionRepository Protocol + InMemoryPredictionRepository),
      `experience.py`(attach_prediction_context — Phase3
      `ExperienceRecord.expected_outcome` 필드를 비침습적으로 채움)
- [x] `src/storage/prediction_repository.py`(DuckDBPredictionRepository) +
      `schema.py`/`serialization.py`에 predictions 테이블/직렬화 추가 —
      기존 테이블 스키마 변경 없음
- [x] Phase 5에 **1건의 additive 변경**: `regime.features.
      _annualized_realized_vol`를 `annualized_realized_vol`로 공개
      (rename만, 동작 변경 없음) — Phase5 기존 48개 regime 테스트 전부
      통과 확인 후 진행
- [x] `tests/predict/`(31) + `tests/storage/test_prediction_repository.py`(5)
      + `tests/integration/test_prediction_experience_lineage.py`(3) —
      신규 39개 테스트 작성 및 전부 통과 (파일명 충돌 방지를 위해
      `test_point_in_time.py`/`test_version_lineage.py`를 각각
      `test_predict_point_in_time.py`/`test_predict_version_lineage.py`로
      명명)
- [x] **전체 테스트 스위트 349개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57 + Phase6 39) — Phase 1~5 기존
      테스트 무손상 확인
- [x] Prediction은 BUY/SELL을 직접 만들지 않음을 구조적으로 검증
      (`test_boundary.py` — PredictionOutput에 order/risk-shaped 필드
      없음, Predictor는 Strategy Protocol을 구현하지 않음, `predict()`
      시그니처에 portfolio/risk 파라미터 없음을 reflection으로 확인)

## Completed (Session 6 — Phase 5)

- [x] Master Plan/ADR-0001~0010/Phase 1~4 spec/현재 src/tests 재조사
      (충돌 없음 확인)
- [x] `docs/specifications/PHASE-5-market-regime.md` 작성
- [x] `docs/decisions/ADR-0011-market-regime-detection.md` 작성
- [x] `src/regime/` 패키지 구현: `enums.py`(RegimeAxis/SubjectKind/
      TrendState 등, TradeProvenance는 재사용), `config.py`
      (RegimeConfig — 모든 threshold configuration으로 분리),
      `points.py`(PriceBar/BenchmarkPoint → PricePoint 정규화 어댑터),
      `features.py`(deterministic feature 계산 — MA관계/realized vol
      percentile/거래량 비율/rolling correlation/drawdown 기반 stress),
      `models.py`(RegimeObservation/CompositeRegimeObservation, frozen
      dataclass), `detector.py`(RegimeDetector — Phase2
      `AsOfDataView`/`BacktestClock`를 그대로 재사용하여 point-in-time
      guard를 새로 만들지 않음, curated composite label 테이블),
      `repository.py`(RegimeRepository Protocol +
      InMemoryRegimeRepository), `experience.py`(attach_regime_context —
      Phase3 `ExperienceRecord.market_regime` 필드를 비침습적으로 채움),
      `strategy.py`(RegimeConditionedStrategy — Phase2 Strategy Protocol
      그대로 구현하는 예시적 conditioning 전략, alpha 주장 없음)
- [x] `src/storage/regime_repository.py`(DuckDBRegimeRepository) +
      `schema.py`/`serialization.py`에 regime 테이블/직렬화 추가 — Phase4
      storage architecture(단일 DuckDB 카탈로그) 그대로 확장, 기존 테이블
      스키마는 변경 없음
- [x] `tests/regime/`(53) + `tests/storage/test_regime_repository.py`(6)
      + `tests/integration/test_regime_experience_lineage.py`(3) — 신규
      57개 테스트 작성 및 전부 통과 (파일명 충돌 방지를 위해
      `tests/regime/test_backtest_integration.py`를
      `test_regime_backtest_integration.py`로 명명)
- [x] **전체 테스트 스위트 310개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57) — Phase 1~4 기존 테스트 무손상
      확인
- [x] Phase 1~4 소스코드 변경 없음 (Phase 5는 완전히 additive) —
      `BacktestEngine`/`Strategy` Protocol/`TradeJournalRepository`/
      기존 storage schema 전부 그대로

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

없음 (Phase 8 설계+참조구현 완료).

## Blocked

**DECISION REQUIRED 3건 누적 (Phase 2/3에서 이어짐) — 사용자 확인 필요.**
Phase 4, Phase 5, Phase 6, Phase 7, Phase 8 세션 모두 세 항목을
재검토했으며, 매번 이번 Phase의 완료 조건과 무관함을 확인하여 여전히
해결하지 않고 이연한다(재검토했으며 이번 Phase와 무관하여 이연)
(Phase 4 spec §19, Phase 5 spec §16, Phase 6 spec §16, Phase 7 spec §14,
Phase 8 spec §20에 각각 재검토 근거 상세 기록):

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

## Design Decisions (Phase 8 세션의 핵심 결정)

1. Phase 8 착수 전 Git/Branch Integrity Check를 **이전 세션의 PASS
   결과를 재사용하지 않고** 현재 HEAD 기준으로 처음부터 재수행 —
   사용자가 명시적으로 반복 요구했음. 실제 검증 결과는 PASS였으므로
   그대로 Phase 8 진행.
2. Position Sizing과 Portfolio Risk Engine을 별도 top-level 패키지로
   나누지 않고 `src/risk/` 패키지 안에 `sizing.py`/`engine.py` 두
   모듈로 구현 — Phase 3 `trade_journal`이 이미 여러 책임(models/
   repository/analysis/experience/backtest_adapter)을 한 패키지
   아래 모듈로 나눈 패턴을 그대로 적용(ADR-0014 §1).
3. `RiskCheckStatus`(PASS/REDUCE/REJECT/UNKNOWN)를 Position Sizing과
   Risk Engine 양쪽 모두의 결과 상태로 공유 — 병렬 enum을 만들지 않음
   (ADR-0014 §2).
4. `PositionSizer.size()`/`PortfolioRiskEngine.assess()`는 Phase 7의
   `DecisionAgent.decide()`와 동일하게 순수 data-in/data-out 함수 —
   `AsOfDataView`나 저장소를 전혀 직접 호출하지 않음. `current_price`는
   호출자가 이미 조회해 전달하는 값(예: Strategy가 `data.get_bars(...)
   .close`로 조회하는 것과 동일한 방식) — Phase 8은 새로운 leakage
   guard를 전혀 작성하지 않음(ADR-0014 §3).
5. `single_position_limit`을 Position Sizing과 Risk Engine 양쪽에서
   독립적으로(서로 다른 config 값으로) 재검사 — Risk Engine이 상위
   계층의 결과를 무조건 신뢰하지 않는 defense-in-depth 원칙을 의도적으로
   적용(ADR-0014 §4).
6. `RiskConfig`의 각 한도값은 "설정 안 됨(`None`, 검사 자체를
   건너뜀)"과 "설정됐지만 이번 호출에 필요한 데이터가 없음(fail-closed
   REJECT)"을 명확히 구분 — 전자를 후자처럼 처리하면 구현되지 않은
   모든 constraint가 영구적으로 거래를 막고, 후자를 전자처럼 처리하면
   활성화된 검사가 데이터 없이도 조용히 통과하는 두 가지 잘못된 결과를
   모두 방지(ADR-0014 §5). 이 구분은 신규 위험 증가(BUY) 행동에만
   적용되며 HOLD/NO_TRADE/SELL/EXIT는 절대 차단되지 않음.
7. `PositionSizingConfig.cost_safety_margin`은 Phase 2
   `BuyAndHoldStrategy.COST_SAFETY_MARGIN`과 동일한 값·목적을 재사용 —
   지시사항이 명시한 Phase 2 현금 소진 버그의 재발 방지를 위한 전용
   regression test(`TestCashSafetyRegression`)로 직접 검증
   (ADR-0014 §7).
8. `risk_state`(PortfolioRiskState)는 별도 테이블 없이
   `risk_assessments.payload_json`에 내장 — `decision_outputs`가 이미
   `regime` context dict를 내장한 것과 동일한 선택(ADR-0014 §6).
9. `max_sector_weight`/`max_factor_exposure`는 `None`(설정 안 됨)으로
   유지 — `data_infra.models.SecurityMaster`에 sector/factor 필드
   자체가 없어 검사할 데이터가 없음. Phase 5의 Correlation/Stress
   3축 조합 미구현과 동일한 패턴으로 문서화된 확장 지점만 준비
   (ADR-0014 §9).
10. 다중 포지션 포트폴리오의 gross_exposure/position_weights는 현재
    호출 대상 종목을 제외한 나머지 보유 포지션에 대해 `average_cost`
    proxy를 사용 — Phase 2 `PortfolioAccounting.mark_to_market`이
    이미 사용하던 동일한 fallback이며, Phase 5부터 이어지는
    "종목 1개당 호출 1회" 아키텍처에서 상속된 한계임을 명시적으로
    문서화(ADR-0014 §10, Known Risks 참조) — 새로운 DECISION REQUIRED가
    아니라 이미 알려진 구조적 제약.
11. `DecisionAction.EXIT`는 `BaselineRuleDecisionAgent`가 아직 생성하지
    않지만, `PositionSizer`는 `SELL`과 동일하게(전량 청산) 처리하도록
    미리 구현 — 향후 Risk Engine이 강제 청산을 위해 `EXIT`를 생성하기
    시작해도 `risk.sizing` 변경이 필요 없음(ADR-0014 §11).
12. `turnover`는 `risk.engine`이 재계산하지 않고 호출자가 전달 —
    `PortfolioAccounting.turnover()`가 이미 추적하고 있는 값을
    중복 구현하지 않음. 호출자가 값을 갖고 있지 않으면(예: Strategy
    관찰자) `None`으로 정직하게 전달하고 `RiskConfig.max_turnover`는
    기본값 `None`(검사 비활성)으로 둠(ADR-0014 §12).

## Design Decisions (Phase 7 세션의 핵심 결정)

1. Phase 7 착수 전 Git/Branch Integrity Check를 **이전 세션의 PASS
   결과를 재사용하지 않고** 현재 HEAD 기준으로 처음부터 재수행 —
   사용자가 명시적으로 반복 요구했음. 실제 검증 결과는 PASS였으므로
   그대로 Phase 7 진행.
2. `DecisionOutput.action`은 `trade_journal.enums.DecisionAction`
   (Phase 3이 이미 "Phase 7 예약"으로 명시해둔 enum)을 그대로 재사용 —
   병렬 enum을 만들지 않음 (ADR-0013 §1).
3. `DecisionOutput`은 quantity/order_id/broker_order/execution_price/
   risk-limit-override 등 어떤 order/risk-shaped 필드도 구조적으로
   갖지 않음. weight 필드명도 `target_weight`가 아니라
   `target_weight_hint`로 명명해 Position Sizing(Phase 8)의 권위 있는
   출력이 아님을 타입 이름 자체로 표시. `BaselineRuleDecisionAgent`도
   `decide()` 외 공개 메서드가 없고 quantity/broker/risk override를
   전달할 파라미터가 없음 — reflection 기반 테스트로 검증
   (`test_decision_boundary.py`, ADR-0013 §2).
4. `DecisionAgent.decide()`는 이미 계산된 입력(prediction, regime,
   portfolio_state, risk_state)만 받는 순수 data-in/data-out 함수 —
   `AsOfDataView`나 어떤 저장소도 직접 호출하지 않음. Point-in-time
   안전성은 전적으로 Phase 5/6가 만든 입력에서 상속받으며, Phase 7은
   새로운 leakage guard를 전혀 작성하지 않음 (ADR-0013 §3).
5. Portfolio State/Risk State는 Phase 7이 생산하지 않는 optional
   파라미터로만 받음 — Portfolio State는 백테스트 루프의 실제
   `PortfolioView`, Risk State는 미래 Risk Engine(Phase 8)의 몫으로
   남겨두고 현재는 항상 `None` (ADR-0013 §4).
6. `portfolio_state is None` → `NO_TRADE`(reason:
   `portfolio_state_unavailable`)로 fail-closed — Master Plan §1.4의
   "Position Unknown → 신규 주문 차단" 규칙을 문자 그대로 구현
   (ADR-0013 §5).
7. Regime은 **존재할 때만** 추가 게이트(Trend UNKNOWN 또는 Stress
   HIGH → NO_TRADE)로 작동하고, Prediction은 없거나 불완전하면
   (`expected_return`/`confidence` 중 하나라도 `None`) 항상
   무조건 NO_TRADE — 두 입력의 비대칭적 취급은 의도적 설계
   (ADR-0013 §6).
8. `DecisionAction.EXIT`는 enum에는 존재하되 baseline 규칙 어디서도
   생성되지 않음 — Phase 2가 `OrderStatus.CANCELLED`를 미리 예약해둔
   것과 동일한 패턴으로, risk-driven 강제 청산은 Risk Engine(Phase 8)
   의 몫 (ADR-0013 §7).
9. 영속화 테이블명은 `decisions`가 아니라 `decision_outputs` — Phase 3
   Trade Journal이 이미 `decisions` 테이블(실제 체결된 결정의 기록)을
   갖고 있어, Phase 7의 (아직 order 생성에 연결되지 않은) hypothetical
   agent 출력과 명칭이 충돌하지 않도록 구분 (ADR-0013 §8).
10. Phase 5/6의 `attach_*_context` 패턴과 달리 `attach_decision_context`는
    **의도적으로 만들지 않음** — `ExperienceRecord.action`은 이미 실제
    체결(`Fill.side`)에서 나온 ground truth이며, 여기에
    `BaselineRuleDecisionAgent`의 hypothetical 병렬 판단을 덮어쓰면
    사실과 가설을 혼동시키는 결과가 됨. 대신 Decision↔Prediction↔Regime
    lineage는 한 DuckDB 카탈로그 안에서의 3-way SQL join으로만 증명
    (ADR-0013 §9).

## Design Decisions (Phase 6 세션의 핵심 결정)

1. Phase 6 착수 전 Git/Branch Integrity Check를 먼저 수행 — 사용자가
   명시적으로 요구했고, 결과가 FAIL이었다면 임의로 merge/rebase/reset/
   force-push를 하지 않고 DECISION REQUIRED로 보고한 뒤 작업을 중단할
   계획이었음. 실제 검증 결과는 PASS였으므로 그대로 Phase 6 진행.
2. `PredictionOutput`은 order/risk-shaped 필드(side, quantity,
   target_weight, risk_state, portfolio_state 등)를 구조적으로 전혀
   갖지 않음 — `Predictor.predict()`도 portfolio/risk 파라미터를 받지
   않음. "Prediction 결과만으로 주문 생성 금지"를 문서가 아니라 타입
   구조로 강제 (ADR-0012 §1).
3. `Predictor`는 Phase 5 `RegimeDetector`와 동일하게 오직
   `backtest.asof.AsOfDataView`만 입력으로 받음 — Phase 6에서 새로운
   point-in-time guard를 전혀 작성하지 않음 (ADR-0012 §2).
4. Baseline predictor 2종을 명확히 구분: `RandomWalkPredictor`(무정보
   null hypothesis, 데이터 조회 자체가 없음, expected_return=0/
   probability=0.5는 추정이 아니라 가설 자체) vs `DriftPredictor`(trailing
   mean return 외삽 + realized vol persistence — 둘 다 표준적인 naive
   forecasting baseline). `PredictionMethodType`(DETERMINISTIC_BASELINE/
   MODEL_BASED)으로 타입 레벨에서 구분 (ADR-0012 §3, §6).
5. `confidence`는 Phase 5의 `reliability`와 동일한 실제 data completeness
   비율을 재사용 — 가짜 confidence score 아님. `uncertainty`는 실제
   추정량(trailing mean return)의 standard error — RandomWalk는 추정 자체를
   하지 않으므로 uncertainty=None (ADR-0012 §4).
6. Phase 5에 **1건의 additive rename**: `regime.features.
   _annualized_realized_vol` → `annualized_realized_vol`(공개) — Phase 6가
   동일한 realized volatility 공식을 중복 구현하지 않도록 재사용. 동작
   변경 없음, Phase 5 기존 48개 테스트 전부 통과 확인 후 진행 (ADR-0012 §5).
7. `RegimeAwarePredictor`로 "Market Regime Detection → Prediction/Signal
   Engine" 데이터 흐름(Master Plan §4.1)을 실제로 연결하되, Phase 5의
   `RegimeConditionedStrategy`와 동일한 원칙 적용: 어떤 테스트도 조건부
   예측이 더 정확하다고 주장하지 않음, 오직 mechanism(EXTREME 변동성일
   때만 dampening 발생, 항상 0 방향으로만 이동)만 검증 (ADR-0012 §6).
8. Phase 5의 `RegimeConditionedStrategy`와 달리, Prediction → 주문을
   만드는 Strategy wrapper는 **의도적으로 만들지 않음** — 이번 Phase
   지시사항이 "Prediction 결과만으로 주문 생성 금지"를 Phase 5보다 더
   강하게 명시했고, Position Sizing/Risk Engine(Phase 8)이 아직 없어
   그런 wrapper를 만들면 지켜야 할 경계를 스스로 흐리게 됨. Backtest
   integration은 "매 체크포인트에서 prediction을 계산해도 백테스트
   결과가 바이트 단위로 동일함"을 증명하는 순수 관찰 방식으로만 구현
   (ADR-0012 §7).
9. Prediction/Regime/Trade Journal/Experiment 전부 Phase 4의 단일 DuckDB
   카탈로그에 저장 — `predictions` 테이블 1개만 추가, 기존 테이블 스키마
   변경 없음 (ADR-0012 §8).
10. Prediction↔Trade Journal lineage는 Phase 5의 `attach_regime_context`와
    동일한 비침습적 opt-in 패턴(`attach_prediction_context`)으로 구현 —
    Phase 3 코드 변경 없음, `ExperienceRecord.expected_outcome`(Phase 3가
    이미 예약해둔 필드)을 채움 (ADR-0012 §9).

## Design Decisions (Phase 5 세션의 핵심 결정)

1. `RegimeObservation`/`CompositeRegimeObservation.provenance`는
   `trade_journal.enums.TradeProvenance`를 그대로 재사용 — 병렬 enum을
   만들지 않음 (ADR-0009가 이미 확립한 "기존 타입 재사용" 원칙을 Phase 5
   에도 그대로 적용, ADR-0011 §1).
2. `RegimeDetector`는 오직 `backtest.asof.AsOfDataView`만 입력으로
   받음 — Phase 2가 이미 만들고 검증한 point-in-time-safe view를 그대로
   재사용하여 Phase 5에서 새로운 look-ahead guard를 전혀 작성하지 않음.
   Backtest 루프 밖(standalone) 사용은 `make_single_point_view()`가
   `BacktestClock`을 체크포인트 1개로 구성해 재사용 (ADR-0011 §2).
3. Regime observation/composite는 Phase 4가 만든 DuckDB 카탈로그에
   테이블 2개(`regime_observations`, `regime_composites`)를 추가하는
   방식으로 영속화 — Parquet가 아님. ADR-0010 §1이 이미 세운 기준(대용량
   시계열=Parquet, point-lookup/조인 중심 relational=DuckDB)을 그대로
   적용한 것으로, 기존 테이블 스키마는 전혀 변경하지 않음 (ADR-0011 §4).
4. Regime↔Trade Journal lineage는 Phase 3 코드(`build_experience_records`)
   를 수정하지 않고, `regime.experience.attach_regime_context()`라는
   별도의 opt-in enrichment 함수로 구현 — `ExperienceRecord.market_regime`
   필드는 Phase 3가 "Phase 5용으로 예약"해둔 것을 그대로 채움 (ADR-0011 §5).
5. `RegimeConditionedStrategy`는 Phase 2 `Strategy` Protocol을 그대로
   구현하는 예시적 wrapper이며, 이를 사용하는 모든 테스트는 조건부 실행
   결과가 더 우수하다고 주장하지 않음 — 오직 mechanism이 동작하는지와
   기계적 성질(BUY 억제 시 거래 수가 늘지 않음)만 검증 (ADR-0011 §6).
6. `reliability`는 실제로 계산 가능한 데이터 완전성 비율이며, 가짜
   ML confidence score가 아님 — lookback window 대비 실제 확보한 데이터
   비율이 `min_data_completeness` 미만이면 axis 상태를 `UNKNOWN`으로
   강제 (fail-closed) (ADR-0011 §7).
7. Phase 1~4 소스코드는 전혀 수정하지 않음 — Phase 5는 완전히 additive
   (신규 패키지 `src/regime/`, 신규 저장소 모듈, 기존 테이블에 영향 없는
   신규 테이블 2개만 추가).

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

- Position Sizing/Risk Engine의 출력(`RiskCheckedPosition`)을 실제로
  소비해 주문을 만드는 Order Creation 없음 (Phase 8+ 이후) — Phase 8은
  sizing/risk 계산을 생산/영속화/lineage 연결까지만 하고, 어떤
  Strategy도 아직 `RiskCheckedPosition`을 읽어 주문을 만들지 않는다
  (ADR-0014 Negative/Trade-offs — 의도적으로 만들지 않음).
- 다중 포지션 포트폴리오의 gross_exposure/position_weights/
  concentration은 현재 호출 대상 종목 외 나머지 포지션에 대해
  `average_cost` proxy를 사용 — 실시간 가격이 있는 종목은 1개
  호출당 1개뿐인 "종목당 호출 1회" 아키텍처(Phase 5~8 공통)에서
  상속된 제약이며 Phase 8이 새로 만든 문제가 아님(Design Decisions
  #10, ADR-0014 §10).
- `RiskConfig.max_sector_weight`/`max_factor_exposure`는 `None`(검사
  비활성) — `SecurityMaster`에 sector/factor 데이터가 없어 실제로
  검사할 수 없음(Design Decisions #9, ADR-0014 §9).
- `PositionSizingConfig`/`RiskConfig`의 threshold(`max_position_weight`,
  `reference_volatility`, `minimum_cash_ratio`, `max_drawdown` 등)는
  실제 성과 데이터에 맞춰 보정되지 않은 예시적 기본값 — 실 배포
  캘리브레이션 주장 없음(ADR-0014 "Negative/Trade-offs").
- `turnover`는 Risk Engine이 자체 계산하지 않고 호출자가 전달해야 함 —
  백테스트 루프의 Strategy 관찰자 컨텍스트에서는 이 값을 갖고 있지
  않아 `None`으로 전달되며, 기본 `RiskConfig.max_turnover=None`이라
  turnover_limit 검사는 기본적으로 비활성 상태(Design Decisions #12,
  ADR-0014 §12).
- `DecisionAction.EXIT`를 실제로 생성하는 risk-driven 강제 청산 로직
  없음 — Phase 8의 `PositionSizer`는 `EXIT`를 `SELL`과 동일하게 처리할
  준비만 되어 있을 뿐, 아직 아무 것도 `EXIT`를 생성하지 않는다(Phase 7
  Design Decisions #8 계속).
- `DecisionAction.EXIT`를 실제로 생성하는 risk-driven 강제 청산 로직
  없음 — enum만 예약(위 Design Decisions #8).
- `DecisionOutput`↔`ExperienceRecord` 간 비침습적 lineage enrichment
  함수(`attach_decision_context`) 없음 — 의도적 설계 결정(위 Design
  Decisions #10, ADR-0013 §9), 오류나 누락이 아님.
- `DecisionConfig`의 threshold(`min_confidence`,
  `min_signal_to_uncertainty_ratio`, `min_expected_return`,
  `exit_return_threshold`, `max_target_weight_hint`)는 실제 성과
  데이터에 맞춰 보정되지 않은 예시적 기본값 — 실 배포 캘리브레이션
  주장 없음(ADR-0013 "Negative/Trade-offs").
- (Phase 7/8에서 부분 해결) Prediction은 이제 Decision Agent(Phase 7)와
  Position Sizing(Phase 8, `expected_volatility` 소비)이 실제로
  사용한다. 다만 그 결과(`RiskCheckedPosition`)를 실제 주문으로
  연결하는 Order Creation은 여전히 없음 — Prediction → 주문을 만드는
  Strategy wrapper는 여전히 의도적으로 만들지 않음.
- Prediction의 model-based(`MODEL_BASED`) 구현 없음 — baseline
  (RandomWalk/Drift) 2종만 존재, 통계적/ML 모델은 baseline 검증 없이
  조기 구현하지 않음(지시사항에 따라 의도적으로 보류).
- `DriftPredictor.probability`는 개별 일별 수익률 중 양수 비율이라는
  거친(coarse) 근사치 — 정밀한 다일(multi-day) horizon 복리 확률이
  아님, 문서에 명시적으로 단순화로 기록됨 (ADR-0012 "Negative/Trade-offs").
- (Phase 7/8에서 부분 해결) Regime은 이제 Decision Agent(Phase 7,
  Trend/Stress 게이트)와 Position Sizing/Risk Engine(Phase 8,
  Liquidity 게이트)이 실제로 사용한다. 다만 Correlation/Volatility
  축은 아직 어떤 거래 판단 로직에도 소비되지 않음.
- Regime의 Correlation/Stress 조합 확장(3축 이상 조합) 미구현 — 필요성이
  아직 확인되지 않아 `features.py`에 확장 지점만 문서화 (ADR-0011
  "Alternatives Considered").
- Spread 기반 유동성 지표 미구현 — Phase 1 `PriceBar`에 bid/ask spread
  필드 자체가 없어 계산 불가 (문서화된 데이터 모델 한계, 은폐 아님).
- 일반화된 Feature Registry 미구현 — Phase 5는 Regime 자신에게 필요한
  최소한의 feature 메타데이터(`feature_version`/`method_version`/
  `configuration_version`)만 구현했으며, 향후 더 넓은 registry가
  이를 스키마 변경 없이 흡수할 수 있도록 설계됨 (ADR-0011).
- 실 데이터 provider 없음(ADR-0005), 벤치마크 return type 미결(위
  DECISION REQUIRED 참조) — Phase 4의 스토리지/베이스라인 구현과 무관하게
  계속 이연.
- Phase 3의 `data_version`(per-decision) 및 `portfolio_state`(corporate
  action 반영) 정밀도 한계 — 위 DECISION REQUIRED 참조. Phase 4는 이
  값을 있는 그대로 영속화할 뿐 해결하지 않는다.
- `prediction_error`, `timing_error`, `risk_estimation_error`,
  `regime_error`, `signal_error`, `market`/`sector`/`factor`/
  `selection`/`timing` attribution — 전부 `None` (Phase 5/6/8 부재).
- (Phase 7에서 해결) `DecisionOutput`을 통해 `NO_TRADE`가 정상적인
  결과로 명시적으로 기록되나, 이 기록은 여전히 Trade Journal의
  `decisions` 테이블(실제 주문)과는 분리된 별도 `decision_outputs`
  테이블에만 남는다 — Phase 2 Strategy가 실제로 주문 의도를 생성한
  경우만 Trade Journal에 기록되는 것은 변함없음.
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
- 일반화된 Feature Engine 없음, Order Creation/Validation/Broker 없음
  (Phase 9+) — Market Regime Detection(Phase 5), Prediction(Phase 6),
  Decision Agent(Phase 7), Position Sizing/Portfolio Risk Engine
  (Phase 8)은 구현 완료. Baseline 전략은 여전히 Phase 2의 단순 Strategy
  인터페이스로 직접 신호를 계산 (Regime을 조건으로 사용하는 것은
  `RegimeConditionedStrategy`로, Prediction을 Regime에 조건화하는
  것은 `RegimeAwarePredictor`로, Regime+Prediction+Portfolio State를
  결합하는 것은 `BaselineRuleDecisionAgent`로, 그 결과를 risk-aware
  포지션으로 변환하는 것은 `DeterministicPositionSizer`+
  `DeterministicPortfolioRiskEngine`으로 각각 시연만 함, 실제 주문에
  연결된 채택 전략/모델 아님).
- Limit order, Purged K-Fold/Embargo, 5종 corporate action 처리 없음
  (Phase 2부터 이어짐).
- Simple ML baseline 미구현 — Phase 2 spec이 `Strategy` Protocol만
  예약해두었고, 이번 Phase 지시사항도 필수가 아닌 선택 사항으로 명시함.
  Buy & Hold + Simple Momentum 두 baseline으로 최소 요구사항 충족.

## Recent Experiments

없음 (실제 데이터 기반 실험 없음). Phase 4/5/6/7/8의 baseline runner,
regime conditioning 실험, regime-aware prediction 실험, baseline rule
decision 실험, deterministic position sizing/risk 실험 모두 기존
Phase 1/2/3 목 데이터셋 패턴(테스트 fixture)으로만 검증되었으며, 실
시장 데이터 기반 실험은 아직 실행되지 않았다 (실 데이터 provider가
없으므로 — ADR-0005). Phase 5의 regime-conditioning 실험, Phase 6의
`RegimeAwarePredictor` 실험, Phase 7의 `BaselineRuleDecisionAgent`를,
Phase 8의 `DeterministicPositionSizer`+`DeterministicPortfolioRiskEngine`
까지 `RecordingStrategy`로 백테스트 루프에 관찰자로 연결한 실험 모두
조건부/파생 버전이 baseline보다 우수하다고 주장하지 않는다 —
mechanism 검증 목적으로만 존재.

## Current Model / Current Benchmark

Phase 2와 동일한 baseline 전략(Buy & Hold, Simple Momentum)과 벤치마크
엔진(S&P 500 Buy & Hold, PRICE_RETURN/TOTAL_RETURN 미결) — 변화 없음.
Phase 6는 baseline predictor 2종(RandomWalk, Drift), Phase 7은
`BaselineRuleDecisionAgent` 1종, Phase 8은 `DeterministicPositionSizer`+
`DeterministicPortfolioRiskEngine` 1쌍을 추가했으나 "현재 채택된
예측/의사결정/사이징 모델"이라 부를 수 있는 것은 없다 — 전부 향후 모델
비교의 기준선으로만 존재하며 실제 주문 생성에 연결되지 않는다.

## Last Validation

`python3 -m pytest tests/ -q` — **483 passed**
(Phase 1: 57, Phase 2: 82, Phase 3: 63, Phase 4: 51, Phase 5: 57, Phase 6: 39, Phase 7: 40, Phase 8: 94).
Phase 8의 94개 테스트는 Unit(정상 사이징/zero-confidence/high-vol/
low-liquidity/cash-shortage/기존 포지션/최대 한도/risk-budget/hint
무시/invalid-numeric/negative/boundary — sizing 36 + engine 31)/
Boundary(주문·broker·execution_price 생성 없음, Phase 7 경계 재확인,
reflection 기반 — 11)/Leakage(미래 데이터 차단, as-of replay,
deterministic replay — 3)/Integration(Phase5 Regime → Phase6
Prediction → Phase7 Decision → Phase8 Sizing/Risk 전체 체인이 실제
BacktestEngine 루프 안에서 관찰자로 동작, 체결 결과 불변 — 4)/
Persistence(저장/재시작/멱등성/as_of 조회/lineage round-trip — 6)/
5-way SQL join lineage(3) 카테고리를 모두 포함하며, Phase 2 현금
소진 버그의 전용 regression test도 포함한다.

---

## Not Yet Implemented

- AI trading decision / LLM API 호출 / Toss Securities / Live Trading
- 실제 외부 데이터 provider (ADR-0005 — Phase 1부터 이연)
- Limit order, Purged K-Fold/Embargo, 5종 corporate action 처리 (Phase
  2부터)
- Order Creation/Validation, Broker/Toss Securities API, Paper/Live
  Trading, Learning Engine/Model Evolution (Phase 9+) — Market Regime
  Detection(Phase 5), Prediction(Phase 6), Decision Agent(Phase 7),
  Position Sizing/Portfolio Risk Engine(Phase 8)는 완료
- Prediction의 model-based(통계적/ML) 구현 — `PredictionMethodType.
  MODEL_BASED`는 예약만 되어 있고 구현체 없음
- Decision Agent의 model-based(AI) 구현 — `DecisionAgent` Protocol은
  `BaselineRuleDecisionAgent` 1종만 구현, 향후 model 기반 agent를 위한
  drop-in 확장 지점만 마련됨
- Position Sizing/Risk Engine의 model-based 구현 — `PositionSizer`/
  `PortfolioRiskEngine` Protocol은 각각 `Deterministic*` 1종만 구현
- Risk Engine이 검증한 `RiskCheckedPosition`을 실제로 소비해 주문을
  만드는 Order Creation/Strategy — 의도적으로 Phase 8 범위 밖
- Sector/Factor limit 실제 검사 — `SecurityMaster`에 해당 데이터
  필드 자체가 없어 구현 불가(`RiskConfig`에 확장 지점만 예약)
- 일반화된 Feature Registry (Phase 5/6는 각자에게 필요한 범위만 구현;
  더 넓은 registry는 필요가 확인되는 시점에)
- 실제 Post Trade Analysis 알고리즘(prediction/timing/risk/regime/
  signal error), 실제 Performance Attribution(market/sector/factor/
  selection/timing), 모델 기반 Counterfactual — 전부 구조만 준비됨
  (Regime 필드는 Phase 5에서 실제로 채워지기 시작함 — `market_regime`)
- Paper/Live 브로커 어댑터 (Trade Journal의 `PAPER_TRADING`/
  `LIVE_TRADING` provenance를 실제로 생산할 producer 없음)
- Learning Engine (Phase 9) — 영속 Experience Dataset(Regime context
  포함)은 이제 존재하지만 아직 아무 것도 그것을 소비하지 않는다
- Model Registry / "왜 모델이 변경되었는가" 감사 질문 (Phase 11)
- DuckDB 다중 프로세스 동시 writer 지원 (Phase 15/16 필요 시 재검토)
- Regime의 HMM/통계적/ML 기반 확장 (baseline 검증 없이 조기 구현하지
  않음 — 지시사항에 따라 의도적으로 보류)

---

## Next Recommended Task

1. **DECISION REQUIRED 3건 확인**: 벤치마크 return type, per-decision
   data_version, corporate-action-aware portfolio_state 재구성 (여전히
   미결, 사용자 판단 대기).
2. **Phase 9 — Learning Engine** 착수: `PROJECT_MASTER_PLAN.md` §18.1의
   Phase 순서를 따를 것. Phase 8의 `RiskCheckedPosition`까지 전체
   deterministic 파이프라인(Prediction→Decision→Sizing→Risk)이 갖춰
   졌으므로, 이제 Trade Journal/Experience Dataset을 실제로 소비하는
   학습 파이프라인을 설계할 준비가 되어 있다. 참고: Master Plan §18.1의
   Phase 목록에는 "Order Creation/Validation/Broker Adapter"를 위한
   전용 Phase 번호가 명시적으로 없음(§2 아키텍처 다이어그램에는
   존재) — Phase 13(Toss Securities Adapter) 또는 그 이전 어느 시점에
   Order Creation이 실질적으로 필요해질 것으로 예상되나, 이는 Phase 8
   완료를 막는 문제가 아니며 사용자 판단 없이 임의로 Phase 번호를
   재배치하지 않는다(§18.4).
3. Phase 9(Learning Engine) 착수 시점에 DECISION REQUIRED 2건(데이터
   버전/corporate action lineage)을 재평가하고, `DuckDBExperienceRepository`
   (이제 `market_regime`과 `expected_outcome`이 채워진 레코드도 포함)를
   실제로 소비하는 학습 파이프라인을 설계.
4. 실 데이터 provider 선정(ADR-0005 기준)이 이루어지면, `data/` 아래
   실제 `StorageConfig.root_dir`를 지정하여 장기 ingestion을 시작할 수
   있다 — Phase 4/5/6/7/8이 그 대상 저장소를 이미 구현했다.
5. 향후 Phase 6의 `PredictionMethodType.MODEL_BASED`, Phase 7의
   model-based `DecisionAgent`, Phase 8의 model-based `PositionSizer`/
   `PortfolioRiskEngine`을 실제로 사용하는 첫 모델이 추가될 때, 반드시
   각 baseline(`RandomWalkPredictor`/`DriftPredictor`/
   `BaselineRuleDecisionAgent`/`DeterministicPositionSizer`/
   `DeterministicPortfolioRiskEngine`)과 비교해 실제로 가치가 있는지
   검증할 것 (baseline 우선 원칙).

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

### Session 6 — 2026-08-24 (Phase 5)
- Master Plan/ADR-0001~0010/Phase 1~4 spec/현재 src·tests 재조사
  (충돌 없음 확인)
- Phase 5 명세, ADR-0011 작성
- `src/regime/` 참조 구현: 5개 baseline regime 축(Trend/Volatility/
  Liquidity/Correlation/Stress) deterministic feature 계산,
  RegimeDetector(Phase2 AsOfDataView/BacktestClock 재사용 — 신규
  look-ahead guard 없음), RegimeRepository, 비침습적 Regime↔Trade
  Journal lineage, RegimeConditionedStrategy(alpha 주장 없는 예시적
  conditioning 실험)
- `src/storage/regime_repository.py` — Phase4 DuckDB 카탈로그에 신규
  테이블 2개 추가(기존 테이블 스키마 변경 없음)
- Phase 1~4 소스코드 변경 전혀 없음 (완전히 additive)
- regime 8개 + storage 1개 + integration 1개 카테고리 포함 57개 테스트
  작성, 전체 310개 테스트 전부 통과 (파일명 충돌 발견 및 즉시 수정 —
  `test_backtest_integration.py` → `test_regime_backtest_integration.py`)
- Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
  않다고 판단, 계속 이연 (임의 결정하지 않음)
- 실제 AI API, Toss Securities, Live Trading, LLM 기반 regime 판단은
  구현하지 않음 (지시대로)

### Session 7 — 2026-08-24 (Phase 6)
- **Phase 6 착수 전 Git/Branch Integrity Check 선행 수행** (사용자
  지시) — 단일 선형 히스토리 확인(Initial commit→Phase0→1→2→3→4→5),
  `origin/main`/`origin/claude/autonomous-ai-investment-system-wvscwe`
  모두 현재 HEAD의 조상이며 누락된 커밋 0개, 병합/분기/reset 흔적 없음,
  Phase 1~5 산출물 전부 실존, 310/310 테스트 통과 확인 → PASS 판정
- Master Plan/ADR-0001~0011/Phase 1~5 spec/현재 src·tests 재조사
  (충돌 없음 확인)
- Phase 6 명세(Git Integrity Check 결과 포함), ADR-0012 작성
- `src/predict/` 참조 구현: RandomWalk/Drift deterministic baseline
  predictor 2종(Predictor Protocol), PredictionOutput(order/risk-shaped
  필드 구조적으로 없음), PredictionRepository, 비침습적 Prediction↔Trade
  Journal lineage, RegimeAwarePredictor(alpha 주장 없는 예시적
  Regime-conditioning)
- `src/storage/prediction_repository.py` — Phase4 DuckDB 카탈로그에
  신규 테이블 1개 추가(기존 테이블 스키마 변경 없음)
- Phase 5에 additive rename 1건(`annualized_realized_vol` 공개) —
  Phase 5 기존 48개 테스트 영향 없음 확인. 그 외 Phase 1~5 소스코드
  변경 없음
- predict 7개 카테고리 + storage 1개 + integration 1개 카테고리 포함
  39개 테스트 작성, 전체 349개 테스트 전부 통과 (파일명 충돌 발견 및
  즉시 수정 — `test_point_in_time.py`/`test_version_lineage.py` →
  `test_predict_point_in_time.py`/`test_predict_version_lineage.py`)
- Prediction이 BUY/SELL을 직접 만들지 않음을 reflection 기반 구조
  테스트로 검증 (test_boundary.py)
- Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
  않다고 판단, 계속 이연 (임의 결정하지 않음)
- 실제 AI API, Toss Securities, Live Trading, 학습된 모델 기반
  prediction은 구현하지 않음 (지시대로)

### Session 8 — 2026-08-24 (Phase 7)
- **Phase 7 착수 전 Git/Branch Integrity Check를 이전 세션 PASS
  결과를 재사용하지 않고 처음부터 재수행** (사용자 지시) — 현재
  HEAD(`6c0b0f6`, Phase 6)부터 Phase 0~6 커밋 9개를 `merge-base
  --is-ancestor`로 개별 재확인, 병합 커밋 0개, `origin/main`과
  `origin/claude/autonomous-ai-investment-system-wvscwe` 모두 조상,
  두 branch 모두 HEAD에 없는 커밋 0개, Phase 0~6 산출물 전부 실존,
  349/349 테스트 통과, working tree clean → PASS 판정
- Master Plan/ADR-0001~0012/Phase 1~6 spec/현재 src·tests 재조사
  (충돌 없음 확인)
- Phase 7 명세(Git Integrity Check 결과 포함), ADR-0013 작성
- `src/decision/` 참조 구현: `BaselineRuleDecisionAgent`(Prediction
  필수/Regime은 존재 시에만 게이트/portfolio_state 없으면 fail-closed
  NO_TRADE의 6단계 순차 규칙), `DecisionOutput`(order/risk-shaped
  필드 구조적으로 없음, `trade_journal.enums.DecisionAction` 재사용),
  `DecisionRepository`
- `src/storage/decision_repository.py` — Phase4 DuckDB 카탈로그에
  `decision_outputs` 테이블 신규 추가(Trade Journal의 기존 `decisions`
  테이블과 명칭 충돌 회피, 기존 테이블 스키마 변경 없음)
- Phase 1~6 소스코드 변경 전혀 없음(`schema.py`/`serialization.py`에
  대한 순수 추가만 존재, `git diff | grep '^-'` 결과 두 파일 모두
  삭제/변경 없음으로 확인)
- decision 4개 카테고리(Unit/Boundary/Leakage/Integration) + storage
  1개 + integration 1개 카테고리 포함 40개 테스트 작성, 전체 389개
  테스트 전부 통과 (파일명 충돌 발견 및 즉시 수정 — `test_boundary.py`
  → `test_decision_boundary.py`)
- 미래 데이터 유출 방지 회귀 테스트 신규 작성 — 미래 bar 추가 후 과거
  시점 Decision 재계산 결과가 바이트 단위로 동일함을 확인
- Decision Agent가 quantity/order/broker/risk-bypass를 만들지 않음을
  reflection 기반 구조 테스트로 검증 (`test_decision_boundary.py`)
- Decision↔Prediction↔Regime lineage는 `attach_decision_context`를
  만들지 않고 3-way SQL join으로 증명(ADR-0013 §9 — `ExperienceRecord.
  action`이 이미 실제 체결 ground truth이므로 hypothetical Decision으로
  덮어쓰지 않는다는 의도적 결정)
- Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
  않다고 판단, 계속 이연 (임의 결정하지 않음)
- Position Sizing/Portfolio Risk Engine/Order Creation/Broker/Paper
  Trading/Live Trading/Learning Engine/Model Evolution은 이번 Phase
  범위에서 명시적으로 제외 (지시대로) — 실제 AI API, Toss Securities,
  Live Trading도 여전히 구현하지 않음

### Session 9 — 2026-08-25 (Phase 8)
- **Phase 8 착수 전 Git/Branch Integrity Check를 이전 세션 PASS
  결과를 재사용하지 않고 처음부터 재수행** (사용자 지시) — 현재
  HEAD(`6a1c937`, Phase 7)부터 Phase 0~7 커밋 10개를 `merge-base
  --is-ancestor`로 개별 재확인, 병합 커밋 0개, `origin/main`과
  `origin/claude/autonomous-ai-investment-system-wvscwe` 모두 조상,
  두 branch 모두 HEAD에 없는 커밋 0개, Phase 0~7 산출물 전부 실존,
  389/389 테스트 통과, working tree clean → PASS 판정
- Master Plan/ADR-0001~0013/Phase 1~7 spec/현재 src·tests 재조사
  (충돌 없음 확인)
- Phase 8 명세(Git Integrity Check 결과 포함), ADR-0014 작성
- `src/risk/` 참조 구현: `DeterministicPositionSizer`(confidence/
  volatility/liquidity/cash/risk_budget을 반영한 14단계 순차
  fail-closed 규칙, decision의 target_weight_hint는 어디서도 읽지
  않음), `DeterministicPortfolioRiskEngine`(cash_minimum→
  single_position_limit→gross_exposure→concentration→drawdown→
  portfolio_volatility→turnover→liquidity 순서로 재검사하는 최종
  권한자, single_position_limit은 Position Sizing과 독립적으로
  재검사하는 defense-in-depth), `PositionSizingResult`/
  `PortfolioRiskState`/`RiskCheckedPosition`(order_id/broker_order/
  execution_price 등 order-shaped 필드 구조적으로 없음),
  `PositionSizingRepository`/`RiskRepository`
- `src/storage/risk_repository.py` — Phase4 DuckDB 카탈로그에
  `position_sizing_results`/`risk_assessments` 테이블 신규 추가
  (risk_state는 별도 테이블 없이 payload_json에 내장, 기존 테이블
  스키마 변경 없음)
- Phase 1~7 소스코드 변경 전혀 없음(`schema.py`/`serialization.py`에
  대한 순수 추가만 존재, `git diff | grep '^-'` 결과 두 파일 모두
  삭제/변경 없음으로 확인)
- risk 5개 카테고리(sizing/engine/boundary/leakage/backtest-integration,
  85개) + storage 1개(6개) + integration 1개(3개) 포함 94개 테스트
  작성, 전체 483개 테스트 전부 통과 (파일명 충돌 없음 — 처음부터
  phase-prefixed 이름으로 작성)
- **Phase 2 현금 소진 버그의 전용 regression test 신규 작성**
  (`TestCashSafetyRegression`) — `BuyAndHoldStrategy.
  COST_SAFETY_MARGIN`과 동일한 목적의
  `PositionSizingConfig.cost_safety_margin`을 도입해 재발을 직접 검증
- 미래 데이터 유출 방지 회귀 테스트 신규 작성 — 미래 bar 추가 후 과거
  시점 Sizing/Risk 결과를 전체 체인으로 재계산해도 결과가 동일함을 확인
- Position Sizing/Risk Engine이 quantity/order/broker/execution_price를
  만들지 않음을 reflection 기반 구조 테스트로 검증하고, Phase 7
  DecisionOutput/BaselineRuleDecisionAgent의 경계가 여전히 유지됨을
  재확인 (`test_risk_boundary.py`)
- Sizing↔Risk↔Decision↔Prediction↔Regime lineage는
  `attach_sizing_context`/`attach_risk_context`를 만들지 않고 5-way
  SQL join으로 증명(Phase 7과 동일한 이유 — `ExperienceRecord.action`이
  이미 실제 체결 ground truth)
- Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
  않다고 판단, 계속 이연 (임의 결정하지 않음)
- Order Creation/Validation/Broker/Toss Securities API/Paper Trading/
  Live Trading/Prediction model training/Learning Engine/Model
  Evolution/AI Gateway/Model Registry/Drift Detection은 이번 Phase
  범위에서 명시적으로 제외 (지시대로)
