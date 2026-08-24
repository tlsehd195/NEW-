# PROJECT STATUS

> 새 Claude Code 세션은 이 파일 하나만 읽어도 현재 프로젝트가 어디까지
> 진행되었는지 파악할 수 있어야 한다. 이 파일은 각 세션 종료 시 반드시
> 최신 상태로 갱신한다.

**Last Updated:** 2026-08-24
**Updated By:** Claude Code (Session 3 — Phase 2 Backtesting)

---

## Current Phase

**Phase 2 — Backtesting** (설계 및 참조 구현 완료, 실제 데이터 provider
연동 및 영구 저장소 백엔드는 여전히 Phase 1부터 이어지는 후속 작업)

## Current Subtask

Phase 2 Definition of Done 충족: 명세 + 3개 ADR + Backtest Engine 전체
파이프라인(Clock/AsOfView/Strategy/Order/Fill/Cost/Slippage/Portfolio/
CorporateAction/Benchmark/Metrics/Integrity/Experiment) 참조 구현 +
15개 카테고리 테스트 전부 통과. **DECISION REQUIRED 1건 미결**
(벤치마크 return type — 아래 참조).

---

## Completed

### Session 1 (Phase 0)
- [x] Repository 조사, `PROJECT_MASTER_PLAN.md`, `docs/PROJECT_STATUS.md`,
      `docs/decisions/ADR-0001-master-architecture.md` 작성

### Session 2 (Phase 1)
- [x] `docs/specifications/PHASE-1-data-infrastructure.md`,
      `docs/architecture/data-catalog.md`, ADR-0002~0005 작성
- [x] `src/data_infra/` 참조 구현 (모델/품질/캘린더/저장소/provider/ingestion)
- [x] 14개 필수 테스트 카테고리, 57개 테스트 전부 통과

### Session 3 (Phase 2)
- [x] Phase 1 데이터 계층 재조사 (`DataRepository`, as_of_time,
      `available_time`, `UniverseMembership`, `CorporateAction`,
      `Provenance`, `DataQualityFramework` 시그니처 확인, 충돌 없음)
- [x] `docs/specifications/PHASE-2-backtesting.md` 작성 (Scope,
      Architecture, Leakage 카테고리별 방지 매핑, Strategy Interface,
      Order/Fill Simulation, Transaction Cost/Slippage, Portfolio
      Accounting, Benchmark Engine, Performance Metrics, Integrity
      Layer, Experiment Tracking, Validation 구조, Baseline 전략,
      연구 기반 적용 범위, Test Plan, DoD 체크리스트)
- [x] `docs/decisions/ADR-0006-backtest-broker-execution-timing.md` —
      Broker Interface + BacktestBroker, 실행 타이밍을 "T 종가로 결정,
      T+1 종가로 체결"로 확정 (T+1 시가 대안은 Phase 1 데이터 모델의
      단일 `available_time`으로는 안전하게 구현 불가능함을 근거로 기각)
- [x] `docs/decisions/ADR-0007-transaction-cost-slippage-model.md` —
      commission+spread+slippage(FixedBps/VolumeScaled), 항상 거래자에게
      불리한 방향으로만 조정, 기본값 비영(非零) 비용
- [x] `docs/decisions/ADR-0008-validation-protocol.md` — 시간순
      train/test split + WalkForwardSplitter 구현, Purged K-Fold/Embargo는
      `ValidationSplitter` 확장점만 예약(미구현)
- [x] `src/backtest/` 패키지 구현 (17개 모듈): `clock.py`, `asof.py`,
      `enums.py`, `strategy.py`(BuyAndHold/SimpleMomentum),
      `orders.py`, `fills.py`, `costs.py`, `corporate_actions.py`,
      `broker.py`, `portfolio.py`, `benchmark.py`, `metrics.py`,
      `validation.py`, `integrity.py`, `experiment.py`, `engine.py`
- [x] `tests/backtest/` — 15개 필수 테스트 카테고리 전부 포함, 82개
      테스트 작성. Phase 1(57) + Phase 2(82) = **139개 테스트 전부 통과**
      (`python3 -m pytest -q`)
- [x] 개발 중 발견 및 수정한 실제 버그 3건 (아래 "이번 세션에서 발견한
      버그" 참조) — 스모크 테스트 및 정식 테스트 작성 과정에서 발견,
      설계가 아닌 구현 결함이었음

## In Progress

없음 (Phase 2 설계+참조구현 단계는 완료). 아래 "Not Yet Implemented"는
의도적으로 Phase 2 스코프에서 제외된 항목이며 후속 작업으로 남는다.

## Blocked

**DECISION REQUIRED 1건 — 사용자 확인 필요** (아래 참조). 이 결정이
내려지기 전까지 Phase 2의 벤치마크 비교 결과는 "PRICE_RETURN 기준"이라는
전제하에서만 유효하다고 해석해야 한다. Phase 2 코드/테스트 자체는 이
결정과 무관하게 정상 동작하므로 구현이 차단된 것은 아니다.

## Design Decisions (이번 세션의 핵심 결정)

1. **실행 타이밍: T 종가로 결정 → T+1 종가로 체결** (ADR-0006). "T+1
   시가 체결"이 더 흔한 관례이지만, Phase 1의 `PriceBar`가 봉 전체에
   대해 단 하나의 `available_time`만 가지므로 시가만 더 일찍
   이용가능하다고 가정하는 것은 Phase 1 데이터 모델을 임의로 확장하는
   것과 같아 채택하지 않음. 이 선택은 자본 비용이 들지만(하루치 추가
   지연) Phase 1 코드 변경이 전혀 필요 없다는 장점이 있음.
2. **거래비용/슬리피지는 항상 거래자에게 불리한 방향으로만 작동**하며
   기본 설정이 비영(非零)임 (ADR-0007).
3. **Purged K-Fold/Embargo는 구현하지 않음** — 아직 학습된 모델도, 폴드
   실험도 없어 검증할 실제 누수 시나리오가 없기 때문 (ADR-0008).
   `ValidationSplitter` 인터페이스만 예약.
4. **Average-cost 기반 포트폴리오 회계** (FIFO tax-lot 아님) — Phase 2의
   전략 비교 목적에는 충분하다고 판단, 세무/규제 수준의 정확한 lot 추적이
   필요해지는 시점에 재검토.
5. `AsOfDataView`는 `as_of_time` 파라미터를 아예 노출하지 않아,
   Strategy 구현체가 실수로라도 미래 시점 데이터를 요청할 방법이
   구조적으로 없음 (Phase 1의 look-ahead guard를 시뮬레이션 계층까지
   확장).

## DECISION REQUIRED — 벤치마크 Return Type (미결, 사용자 확인 필요)

```
Problem:
S&P 500 벤치마크를 "가격 수익률(PRICE_RETURN)"로 비교할지 "총수익률
(TOTAL_RETURN, 배당 재투자 포함)"로 비교할지가 아직 결정되지 않았다.
이는 Phase 1이 이미 열어둔 채로 남긴 질문이다
(data-catalog.md의 mock_benchmark_sp500 항목).

Current Design:
Phase 1의 BenchmarkPoint는 return_type 필드(PRICE_RETURN | TOTAL_RETURN)를
가지고 있고, Phase 2의 BenchmarkEngine은 둘 중 어느 쪽이 들어와도 정확히
처리하고 결과에 실제 사용된 return_type을 명시한다. 그러나 Phase 1이
제공한 mock 벤치마크 데이터셋은 PRICE_RETURN만 존재하며, 실제 S&P 500
total-return 데이터를 제공하는 provider는 아직 선정되지 않았다
(ADR-0005, Phase 1).

Option A:
지금은 PRICE_RETURN으로 진행하고, 실제 provider 선정 시점(Phase 2
이후, 실 데이터 도입 시)에 TOTAL_RETURN으로 전환한다.
장점: 지금 당장 막힘이 없음. 단점: 배당을 재투자하는 실제 S&P500 지수
대비 전략의 초과수익이 구조적으로 과대평가될 수 있음(전략은 배당을
받지만 — CorporateActionApplier가 이미 이를 반영함 — 벤치마크는 배당을
반영하지 않으므로).

Option B:
실제 데이터 provider를 선정할 때 반드시 total-return 데이터(또는
가격 수익률 + 배당수익률을 합성할 수 있는 데이터)를 제공하는 provider를
우선 조건으로 삼는다.
장점: 처음부터 공정한 비교가 보장됨. 단점: provider 선택지가 줄어들거나
비용이 늘어날 수 있음.

Recommendation:
Option A로 지금 진행하되(막힘 방지), Phase 1 ADR-0005의 "실제 provider
선정" 결정 시점에 Option B의 조건(total-return 데이터 확보 가능 여부)을
선정 기준에 명시적으로 포함시킬 것을 권장한다. Phase 2 코드는 이미 두
경우 모두를 정확히 처리하도록 설계되어 있으므로(§9 of PHASE-2 spec),
이 결정이 나중에 바뀌어도 재구현이 필요하지 않다.

Impact:
현재 mock 데이터로 실행한 모든 Phase 2 벤치마크 비교 결과는
"배당을 제외한 가격 수익률 기준" 비교로 해석해야 하며, 실제 총수익 기준
초과수익(excess_return)과는 다를 수 있다. 이는 코드 버그가 아니라
정직하게 라벨링된 한계다.
```

**사용자 확인이 있기 전까지 이 항목은 열려 있는 것으로 취급한다.**

## Known Risks / Limitations (의도적으로 남겨둔 항목)

- (Phase 1에서 이어짐) `InMemoryDataRepository`는 참조 구현이며 영속성
  없음. DuckDB/Parquet 백엔드 미구현.
- (Phase 1에서 이어짐) `TradingCalendar`의 US/KR 구현은 최소 샘플
  휴일만 포함.
- 벤치마크 return type 미결 — 위 DECISION REQUIRED 참조.
- MERGER/ACQUISITION/SPIN_OFF/TICKER_CHANGE/DELISTING corporate
  action은 Phase 2에서 처리하지 않음 (경고만 기록, Phase 2 spec §8.4).
- Average-cost 포트폴리오 회계 (FIFO tax-lot 아님).
- Purged K-Fold/Embargo 미구현 (인터페이스만 예약, ADR-0008).
- `VolumeScaledSlippageModel`의 impact coefficient는 실제 시장 데이터로
  캘리브레이션되지 않음 — 메커니즘 실증용, 신뢰할 수 있는 비용 예측
  아님 (ADR-0007).
- Limit order 미구현 (구조만 예약, `OrderType.LIMIT` 사용 시
  `NotImplementedError`).
- 실제 외부 데이터 provider 및 실제 S&P500 historical constituent/배당
  데이터 여전히 미확보 (Phase 1 ADR-0005에서 이어지는 선행 조건).

## Recent Experiments

없음 (실제 데이터 기반 실험 없음 — 모든 Phase 2 테스트/스모크 실행은
mock/synthetic 데이터 기준). `ExperimentTracker`는 구현되어 있으며
"BT-000001" 형식으로 실행마다 기록되지만, 지속 저장소는 아직 없음.

## Current Model

없음 (Phase 4 Baseline Models 이전까지 학습된 모델 없음). Phase 2는
학습이 필요 없는 두 개의 baseline 전략(Buy & Hold, Simple Momentum)만
구현했다.

## Current Benchmark

S&P 500 Buy & Hold 구조는 구현 완료 (`BenchmarkEngine`), 단 위
DECISION REQUIRED가 해결되기 전까지는 PRICE_RETURN 기준으로만 사용
가능.

## Last Validation

`python3 -m pytest tests/ -q` — **139 passed** (Phase 1: 57, Phase 2: 82).
Phase 2의 82개 테스트는 지시된 15개 필수 카테고리(deterministic replay,
no-lookahead, transaction cost, slippage, cash accounting, position
accounting, PnL, drawdown, benchmark, corporate action, survivorship,
execution timing, duplicate order, reproducibility, integrity failure)를
전부 포함한다.

---

## 이번 세션에서 발견한 버그 (설계가 아닌 구현 결함)

스모크 테스트와 정식 테스트 작성 과정에서 다음 3개의 실제 버그를
발견하고 수정했다 (설계 문서/ADR의 결함이 아니라 구현 코드의 결함):

1. **`BuyAndHoldStrategy`/`SimpleMomentumStrategy`가 현금을 100% 소진**
   하여 수수료를 위한 여유가 없어 정상적인 주문이 `OrderSimulator`에
   의해 "insufficient cash"로 거부됨 → `COST_SAFETY_MARGIN`(2%) 도입.
2. **`BacktestEngine._compute_benchmark`가 체크포인트 시각(예: 20:00)을
   그대로 벤치마크 조회 시작 경계로 사용**하여, 봉 시작 시각(00:00)으로
   기록된 첫날의 벤치마크 데이터 포인트가 범위에서 누락됨 → 시작 경계를
   하루 전으로 당겨 조회하도록 수정.
3. **백테스트 마지막 체크포인트에서 생성된 주문 의도(intent)가 실제
   `Order` 객체로 변환되지 않고 조용히 폐기**되어 감사 가능성
   (auditability) 원칙에 위배됨 → `OrderStatus.NOT_EXECUTED` 상태의
   `Order` 객체를 명시적으로 생성하도록 수정.

세 버그 모두 테스트 작성 및 실행을 통해 발견되었으며, 이는 Phase 2의
핵심 목표("실전에서 믿을 수 있는 검증 방법을 만드는 것")가 실제로
작동했음을 보여주는 사례로 기록해 둔다 — 설계 문서만으로는 이런 버그를
잡을 수 없었을 것이다.

---

## Not Yet Implemented

- AI trading decision / LLM trading prompt / automatic strategy generation
- Model training / reinforcement learning / automatic model deployment
- Toss Securities 연동, 실계좌 주문, Live Trading, 자율 매매
- 실제 외부 데이터 provider 연동 (Phase 1부터 이어짐)
- DuckDB/Parquet 실 저장소 백엔드 (Phase 1부터 이어짐)
- Feature Engine, Market Regime Detection, Prediction/Decision Agent
  (Phase 2 Strategy는 이들 없이 baseline 신호를 직접 계산함),
  Position Sizing/Portfolio Risk Engine의 완전한 형태 (Phase 5-8)
- Limit order 실행 로직
- Purged K-Fold / Embargo validation
- MERGER/ACQUISITION/SPIN_OFF/TICKER_CHANGE/DELISTING corporate action
  처리
- 영속적 Experiment/Model Registry 저장소

---

## Next Recommended Task

1. **DECISION REQUIRED 확인**: 벤치마크 return type 결정 (위 참조) —
   사용자 확인 후 `docs/decisions/`에 후속 ADR로 기록 권장.
2. (선택) Phase 1/2 공통 follow-up: DuckDB/Parquet 백엔드 구현.
3. **Phase 3 — Trade Journal** 착수: `docs/specifications/
   PHASE-3-trade-journal.md` 작성부터 시작. Phase 2가 이미 생성하는
   `Order`/`Fill`/`ExperimentRecord`/`IntegrityReport`를 Trade
   Journal의 Decision Snapshot 입력으로 연결하는 것이 핵심 과제가 될
   것이다 (`PROJECT_MASTER_PLAN.md` §10, §30-31).

---

## 세션 이력 (Session Log)

### Session 1 — 2026-08-24 (Phase 0)
- 저장소 최초 조사, Phase 0 문서 기반 수립

### Session 2 — 2026-08-24 (Phase 1)
- Data Infrastructure 설계 및 참조 구현, 57개 테스트

### Session 3 — 2026-08-24 (Phase 2)
- Phase 1 데이터 계층 재조사 (충돌 없음 확인)
- Phase 2 명세, ADR-0006~0008 작성
- `src/backtest/` 참조 구현 (Clock/AsOfView/Strategy/Order/Fill/Cost/
  Slippage/Portfolio/CorporateAction/Broker/Benchmark/Metrics/
  Validation/Integrity/Experiment/Engine)
- 15개 필수 테스트 카테고리 포함 82개 테스트 작성, Phase1+Phase2 합계
  139개 테스트 전부 통과
- 스모크 테스트로 실제 구현 버그 3건 발견 및 수정
- 벤치마크 return type을 DECISION REQUIRED로 보고 (임의 결정하지 않음)
- 실제 AI API, Toss Securities, Live Trading은 여전히 구현하지 않음
  (지시사항 준수)
