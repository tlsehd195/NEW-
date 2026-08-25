# Autonomous AI Investment System

자율형 AI 투자 연구·검증·학습·실행 시스템.

시장 데이터를 관찰하고, 시장 상태를 분석하고, 투자 의사결정을 내리고,
포지션과 위험을 계산하고, 주문을 실행하며, 모든 의사결정과 거래 결과를
기록하고, 그 경험을 학습 데이터로 축적하고, 새로운 모델/전략을 생성하고,
엄격한 검증을 통과한 경우에만 새로운 모델을 실전 시스템에 배포할 수
있는 시스템을 목표로 한다.

최종 목표: **검증 가능한 방식으로 S&P 500의 장기 수익률을 초과하는 것.**
(초과수익을 보장하지 않는다.)

## 시작하기 전에 반드시 읽어야 할 문서

새 세션(사람이든 Claude Code든)은 아래 순서로 읽으면 프로젝트 전체
맥락을 복구할 수 있다:

1. [`PROJECT_MASTER_PLAN.md`](./PROJECT_MASTER_PLAN.md) — 프로젝트의
   목적, 철학, 헌법(절대 금지 사항 및 우선순위), 전체 아키텍처, 모듈
   책임과 경계, 데이터 흐름, Trade Journal, AI Gateway, Toss Securities
   Adapter, 백테스트/검증 규칙, Kill Switch, Phase 순서와 각 Phase의
   진행 규칙, 변경관리 절차 등 **Source of Truth**.
2. [`docs/PROJECT_STATUS.md`](./docs/PROJECT_STATUS.md) — 현재 어느
   Phase까지 왔는지, 무엇이 완료/진행중/차단 상태인지.
3. [`docs/decisions/`](./docs/decisions/) — 왜 그렇게 설계했는지에 대한
   ADR(Architecture Decision Record) 모음.
4. `docs/specifications/` — 진행 중인 Phase의 상세 명세.

## 절대 원칙 (요약)

- Capital Safety > Data Integrity > Reproducibility > Validation >
  Risk Control > Accurate Trade Recording > Learning > Performance >
  Complexity.
- 시스템이 불확실한 상태이면 기본값은 **거래하지 않음(Fail-Closed)**.
- 실계좌 주문, kill switch, risk limit, broker credential, 무료 API
  과금 정책은 AI가 스스로 변경할 수 없다.
- 새 모델은 검증(백테스트 → OOS → Paper Trading 등)을 통과하고 사람이
  승인해야만 Live로 배포된다. 학습 결과가 자동으로 Live에 적용되지 않는다.

자세한 내용은 `PROJECT_MASTER_PLAN.md`를 참조한다.

## 디렉터리 구조

```
/
├── PROJECT_MASTER_PLAN.md   Source of Truth
├── docs/
│   ├── PROJECT_STATUS.md    현재 진행 상태
│   ├── decisions/           ADR
│   ├── architecture/
│   ├── research/
│   ├── specifications/      Phase별 상세 명세
│   ├── development/
│   └── operations/
├── src/                     구현 코드 (Phase 1부터)
├── tests/
├── scripts/
├── configs/{development,backtest,paper,live}/
├── data/
├── experiments/
└── logs/
```

## 현재 상태

**Phase 11 — Model Evolution** (설계 및 참조 구현 완료).
상세는 `docs/PROJECT_STATUS.md` 참조.

- Phase 0 — Foundation: 완료 (문서 기반 수립)
- Phase 1 — Data Infrastructure: 완료 (`src/data_infra/`, 57 tests)
- Phase 2 — Backtesting: 완료 (`src/backtest/`, 82 tests)
- Phase 3 — Trade Journal: 완료 (`src/trade_journal/`, 63 tests)
- Phase 4 — Baseline Models + Persistent Storage: 완료
  (`src/storage/`, `src/baseline/`, 51 tests) — DuckDB+Parquet 영속
  저장소(Raw/Clean Market Data, Security Master, Universe Membership,
  Corporate Actions, Benchmark, Trade Journal, Experiment, Experience
  Dataset 전부 포함), Buy & Hold / Simple Momentum baseline을 동일
  Backtest Engine에서 실행하고 벤치마크와 비교하는 리포트
- Phase 5 — Market Regime Detection: 완료 (`src/regime/`, 57 tests) —
  Trend/Volatility/Liquidity/Correlation/Stress 5개 축의 deterministic
  baseline regime 분류기, Phase 2의 `AsOfDataView`를 재사용하는
  point-in-time-safe `RegimeDetector`, Phase 4 저장소에 영속화, Trade
  Journal/Experience Dataset과 비침습적 lineage 연결
- Phase 6 — Prediction: 완료 (`src/predict/`, 39 tests) — RandomWalk/
  Drift deterministic baseline predictor 2종, Decision/Risk/Execution과
  구조적으로 분리된 `PredictionOutput`, Phase 2의 `AsOfDataView`를
  재사용하는 point-in-time-safe 예측 계산, Phase 4 저장소에 영속화,
  Trade Journal/Experience Dataset과 비침습적 lineage 연결
- Phase 7 — Decision Agent: 완료 (`src/decision/`, 40 tests) —
  Prediction + Regime + Portfolio State를 결합해 BUY/SELL/HOLD/EXIT/
  NO_TRADE를 판단하는 `BaselineRuleDecisionAgent`, quantity/order/
  broker/risk-bypass 필드가 구조적으로 없는 `DecisionOutput`, Phase 5/6
  출력만 소비하는 point-in-time-safe 계산(신규 leakage guard 없음),
  Phase 4 저장소(`decision_outputs` 테이블)에 영속화, Regime→
  Prediction→Decision 3-way SQL join으로 증명된 lineage — Position
  Sizing/Risk Engine/Order Creation/Broker/Paper·Live Trading은 명시적
  범위 밖(Phase 8+)
- Phase 8 — Position Sizing + Portfolio Risk Engine: 완료 (`src/risk/`,
  94 tests) — Decision + Prediction + Regime + Portfolio State를 결합해
  target_weight/target_quantity를 계산하는 `DeterministicPositionSizer`,
  포트폴리오 수준 hard limit(single position/gross exposure/
  concentration/drawdown/portfolio volatility/cash minimum/turnover/
  liquidity)을 독립적으로 재검사하는 최종 권한자
  `DeterministicPortfolioRiskEngine`, order_id/broker_order/
  execution_price 등 order-shaped 필드가 구조적으로 없는
  `PositionSizingResult`/`RiskCheckedPosition`, Phase 5~7 출력만
  소비하는 point-in-time-safe 계산(신규 leakage guard 없음), Phase 4
  저장소(`position_sizing_results`/`risk_assessments` 테이블)에
  영속화, Phase 2 현금 소진 버그의 전용 regression test — Order
  Creation/Validation/Broker/Paper·Live Trading은 명시적 범위 밖
  (Phase 9+)
- Phase 9 — Learning Engine: 완료 (`src/learning/`, 70 tests) — Trade
  Journal의 Experience Dataset을 Data Cleaning(VALID/INVALID/EXCLUDED/
  UNKNOWN 4상태, 절대 조용히 버리지 않음) → Labeling(각 거래의 실제
  realized_return을 label로 사용) → Training Dataset(시간순
  non-shuffled train/validation/test split, 실제 sample 내용을 해싱하는
  content-hash 버전으로 재현 가능) → Candidate Training
  (`MeanRewardBaselineTrainer` — TRAIN split 평균만 사용하는
  null-hypothesis baseline, 항상 CANDIDATE 상태만 생산) → Evaluation
  (MAE/MSE + baseline 비교, candidate 우위 주장 없음)까지 연결하는
  파이프라인. `CandidateModelStatus`는 Master Plan의 7개 상태를 전부
  예약하되 이번 Phase 코드는 APPROVED/DEPLOYED를 생성할 수 있는 경로가
  전혀 없음(사람의 승인 없이는 배포되지 않는다는 원칙을 구조적으로
  보장). Phase 4 저장소(`training_datasets`/`candidate_models`/
  `evaluation_results`/`learning_experiments` 테이블)에 영속화 —
  Order/Broker/Model Deployment는 명시적 범위 밖(Phase 10+) —
  `DECISION REQUIRED` 3건 여전히 미결(벤치마크 return type,
  per-decision data version, corporate-action-aware portfolio state
  재구성) — `docs/PROJECT_STATUS.md` 참조
- Phase 10 — Counterfactual / Attribution: 완료 (`src/counterfactual/`,
  54 tests) — 선택한 행동과 HOLD/CASH 대안을 비교하는 Counterfactual
  Analysis, `market + selection + execution == cumulative_return`
  항등식을 항상 정확히 만족하는 Performance Attribution. Phase 3가
  이미 예약해 둔 `AlternativeOutcome`/`CounterfactualRecord`/
  `AttributionResult` 타입을 그대로 재사용(신규 병렬 타입 없음).
  `alternative_action_1`/`alternative_action_2`(다른 모델의 가상
  의사결정 비교)와 `timing`/`sector`/`factor` attribution은 검증되지
  않은 추정값을 사실처럼 저장하지 않기 위해 Phase 11로 명시적으로 이연
- Phase 11 — Model Evolution: 완료 (`src/evolution/`, 62 tests) —
  `learning.enums.CandidateModelStatus`가 Phase 9부터 예약해 둔
  `CANDIDATE → BACKTESTED → VALIDATED → OOS_TESTED` 상태 전이를 명시적,
  버전 관리되는 수치 기준으로 실제로 구현(실패한 전이도 항상 auditable
  기록으로 남김, `APPROVED`/`DEPLOYED`로 가는 경로는 구조적으로 아예
  없음 — 사람의 승인이 필요). 두 번째 candidate 생성기
  (`TrailingWindowMeanTrainer`)로 후보 비교(`compare_candidates`,
  winner/champion 필드 없음)를 실제로 exercise. 후보의 generation을
  항상 parent로부터만 파생시키는 `ModelLineageRecord`로 Model Registry
  lineage/versioning 완성(Phase 9가 "Model Registry completion (Phase
  11)"로 이미 지정해 둔 범위). Phase 10이 이연했던
  `alternative_action_1`/`alternative_action_2`도 이번 Phase에서 구현
  — 실제 Predictor+DecisionAgent를 거래의 decision_time에 실행해 얻은
  가상 결정을 Phase 3/10의 hold/cash 수익률 계산으로 그대로 변환.
  Phase 1~10 소스코드 변경 없이 완전히 additive. PBO/Deflated
  Sharpe/Walk-Forward validation, AI Gateway, 실제 브로커/주문은 여전히
  범위 밖(Phase 12+)

전체 테스트: **669 passed** (Phase 1+2+3+4+5+6+7+8+9+10+11 합산).

## 테스트 실행

```bash
pip install -e ".[dev]"
python3 -m pytest tests/ -q
```

## 영속 저장소 (Phase 4)

`src/storage/`는 DuckDB(관계형/메타데이터: Security Master, Corporate
Actions, Benchmark, Universe Membership, Trade Journal, Experiment,
Experience Dataset) + Parquet(대용량 시계열: Raw/Clean Market Data)
조합으로 재시작 후에도 데이터가 유실되지 않는 영속 계층을 제공한다.
Application/Backtest/Trade Journal 코드는 이 구현을 직접 호출하지 않고
Phase 1/3가 정의한 `DataRepository`/`TradeJournalRepository`
Protocol(및 Phase 4가 추가한 `ExperimentRepository`/
`ExperienceRepository`)을 통해서만 접근한다. 자세한 설계는
`docs/specifications/PHASE-4-baseline-models-and-storage.md`와
`docs/decisions/ADR-0010-persistent-storage-backend.md` 참조.

## Market Regime (Phase 5)

`src/regime/`는 시장 상태(Trend/Volatility/Liquidity/Correlation/
Stress)를 독립적으로 탐지하는 계층이다. Prediction/Decision과 분리되어
있으며 BUY/SELL을 직접 결정하지 않는다. Regime 계산은 Phase 2의
`AsOfDataView`를 그대로 재사용해 point-in-time 안전성을 상속받고,
결과는 Phase 4의 DuckDB 저장소에 영속화되며, Trade Journal/Experience
Dataset과 비침습적으로 lineage가 연결된다. 자세한 설계는
`docs/specifications/PHASE-5-market-regime.md`와
`docs/decisions/ADR-0011-market-regime-detection.md` 참조.

## Prediction (Phase 6)

`src/predict/`는 expected_return/probability/expected_volatility/
uncertainty/confidence를 산출하는 Prediction 계층이다. Decision/Risk/
Execution과 구조적으로 분리되어 있으며(`PredictionOutput`에는
order/risk-shaped 필드가 아예 존재하지 않는다), Prediction 결과만으로
주문을 생성하지 않는다. RandomWalk(무정보 baseline)와 Drift(trailing
mean return 외삽) 두 deterministic baseline이 존재하며, 향후 model-based
predictor를 위한 인터페이스(`PredictionMethodType.MODEL_BASED`)만 예약
되어 있다. 계산은 Phase 2의 `AsOfDataView`를 재사용해 point-in-time
안전성을 상속받고, 결과는 Phase 4의 DuckDB 저장소에 영속화되며, Trade
Journal/Experience Dataset과 비침습적으로 lineage가 연결된다. 자세한
설계는 `docs/specifications/PHASE-6-prediction.md`와
`docs/decisions/ADR-0012-prediction-layer.md` 참조.

## Decision Agent (Phase 7)

`src/decision/`는 Prediction(Phase 6) + Regime(Phase 5) + Portfolio
State(+ 향후 Risk State)를 종합해 BUY/SELL/HOLD/EXIT/NO_TRADE 중
하나를 판단하는 Decision 계층이다. `DecisionOutput`에는 quantity,
order_id, broker_order, execution_price 등 Position Sizing/Order
Creation/Execution의 책임에 해당하는 필드가 구조적으로 전혀 존재하지
않는다 — `target_weight_hint`는 참고용 힌트일 뿐 권위 있는 주문
수량이 아니다. `BaselineRuleDecisionAgent`는 이미 계산된 Prediction/
Regime/PortfolioView만 입력으로 받는 순수 함수이며, 어떤 저장소나
`AsOfDataView`도 직접 호출하지 않아 point-in-time 안전성은 전적으로
Phase 5/6 출력에서 상속받는다(신규 leakage guard 없음).
`portfolio_state`가 없으면 항상 `NO_TRADE`로 fail-closed 처리한다
(`PROJECT_MASTER_PLAN.md` §1.4). 결과는 Phase 4의 DuckDB 저장소
(`decision_outputs` 테이블)에 영속화되며, Prediction/Regime과의
lineage는 한 카탈로그 안에서의 SQL join으로 증명된다. Position
Sizing, Portfolio Risk Engine, Order Creation/Validation, Broker,
Paper/Live Trading은 모두 이후 Phase의 몫으로 명시적으로 범위 밖에
있다. 자세한 설계는 `docs/specifications/PHASE-7-decision-agent.md`와
`docs/decisions/ADR-0013-decision-agent.md` 참조.

## Position Sizing + Portfolio Risk Engine (Phase 8)

`src/risk/`는 Phase 7의 `DecisionOutput`을 얼마나(target_weight/
target_quantity) 매매할지로 변환하는 Position Sizing(`sizing.py`)과,
그 제안을 포트폴리오 수준 hard limit에 대해 독립적으로 재검사하는
Portfolio Risk Engine(`engine.py`) 두 계층이다. `DeterministicPositionSizer`
는 confidence/volatility/liquidity/현금/risk_budget을 반영해
target_weight를 계산하되 `DecisionOutput.target_weight_hint`는 어디서도
읽지 않는다 — Phase 7이 "hint"라고 이름 붙인 이유가 이 계층에서
literal하게 지켜진다. `DeterministicPortfolioRiskEngine`은 cash_minimum
→ single_position_limit → gross_exposure → concentration → drawdown →
portfolio_volatility → turnover → liquidity 순서로 자체 한도를 재검사
하는 파이프라인의 최종 권한자이며, single_position_limit은 Position
Sizing이 이미 적용했더라도 독립적으로 다시 검사한다(defense in depth).
`RiskCheckStatus`(PASS/REDUCE/REJECT/UNKNOWN)를 두 계층이 공유하며,
설정된 한도인데 필요한 데이터가 없으면 항상 `REJECT`(fail-closed)로
처리하고, 설정되지 않은 한도(예: sector/factor — 데이터 자체가 없음)는
단순히 검사를 건너뛴다. `PositionSizingResult`/`RiskCheckedPosition`
어디에도 order_id/broker_order/execution_price 등 order-shaped 필드가
구조적으로 존재하지 않는다. 두 계층 모두 이미 계산된
Decision/Prediction/Regime/PortfolioView와 호출자가 이미 조회한
`current_price`만 입력으로 받는 순수 함수이며, 어떤 저장소나
`AsOfDataView`도 직접 호출하지 않아 point-in-time 안전성은 전적으로
Phase 5~7 출력에서 상속받는다(신규 leakage guard 없음). 결과는 Phase 4의
DuckDB 저장소(`position_sizing_results`/`risk_assessments` 테이블)에
영속화되며, Decision/Prediction/Regime과의 lineage는 한 카탈로그 안에서의
5-way SQL join으로 증명된다. Phase 2에서 발견됐던 "현금을 100% 소진해
거래비용을 낼 여유가 없었던" 버그의 재발을 막는 전용 regression test도
포함한다. Order Creation/Validation, Broker, Paper/Live Trading은 모두
이후 Phase의 몫으로 명시적으로 범위 밖에 있다. 자세한 설계는
`docs/specifications/PHASE-8-position-sizing-and-risk.md`와
`docs/decisions/ADR-0014-position-sizing-and-risk-engine.md` 참조.

## Learning Engine (Phase 9)

`src/learning/`는 Trade Journal의 Experience Dataset(Phase 3/4)을
`Experience → Data Cleaning → Labeling → Training Dataset → Candidate
Training → Evaluation` 순서로 연결하는 Learning Engine이다.
`DataCleaner`는 모든 샘플에 VALID/INVALID/EXCLUDED/UNKNOWN 중 하나의
상태와 사실적인 reason을 부여하며 절대 조용히 제거하지 않는다.
`Labeler`는 각 거래의 이미 실현된 `realized_return`만 label로 사용하고
(가격 데이터 기반의 새로운 forward-return 계산 없음), feature cutoff와
label 시작 시점을 구조적으로 분리해 유지한다. `build_training_dataset`
은 `as_of_cutoff`가 주어지면 그 이후 시점의 experience를 Data Cleaning이
보기도 전에 배제하고(`AsOfDataView`의 "미래 데이터는 존재하지 않는다"
원칙을 Experience Dataset 구성에도 동일하게 적용), 시간순
non-shuffled train/validation/test 분할을 만들며, 실제 sample 내용을
해싱한 content-hash `dataset_version`으로 재현성을 보장한다.
`MeanRewardBaselineTrainer`는 TRAIN split 평균만 사용하는
null-hypothesis baseline "trainer"로 VALIDATION/TEST에는 전혀 접근하지
않으며, `CandidateModelArtifact.status`는 항상
`CandidateModelStatus.CANDIDATE`만 생산한다 — Master Plan §11.2의 나머지
6개 상태(BACKTESTED/VALIDATED/OOS_TESTED/PAPER_TESTED/APPROVED/
DEPLOYED)는 enum에 예약만 되어 있을 뿐 `learning/*.py` 어디에도 이를
생성하는 코드 경로가 없다(사람의 명시적 승인 없이 배포로 전이될 수
없다는 Master Plan §11.5 원칙이 구조적으로 보장됨). `Evaluator`는
MAE/MSE와 trivial baseline 비교만 제공하며 candidate가 baseline보다
우수하다고 주장하는 필드는 존재하지 않는다. provenance는
`build_training_dataset`의 `provenance` 파라미터에 기본값을 두지 않아
HISTORICAL_SIMULATION/PAPER_TRADING/LIVE_TRADING이 섞이는 것을 구조적으로
방지한다. 결과는 Phase 4의 DuckDB 저장소(`training_datasets`/
`candidate_models`/`evaluation_results`/`learning_experiments` 테이블)에
영속화되며, 각 저장소는 자연키로 멱등성을 확인한 뒤 storage-level
시퀀스로 새 id를 발급한다(독립적인 두 파이프라인 실행이 in-process
allocator 충돌로 PRIMARY KEY를 침해하지 않도록 하는, Phase 4가 이미
확립한 것과 동일한 패턴). Order Creation, Broker, Model Registry/
Deployment는 모두 이후 Phase의 몫으로 명시적으로 범위 밖에 있다. 자세한
설계는 `docs/specifications/PHASE-9-learning-engine.md`와
`docs/decisions/ADR-0015-learning-engine.md` 참조.

## Counterfactual / Attribution (Phase 10)

`src/counterfactual/`는 실제 선택한 행동의 결과를 선택하지 않은 대안
(HOLD, CASH)과 비교하는 Counterfactual Analysis와, 실현 수익을
market/selection/execution 세 요소로 분해하는 Performance Attribution
을 구현한다. Phase 3가 이미 "미래 Phase가 채울 예약 필드" 형태로
정의해 둔 `trade_journal.models.AlternativeOutcome`/
`CounterfactualRecord`/`AttributionResult`를 그대로 재사용하며(신규
병렬 타입 없음), HOLD counterfactual은 Phase 3의 기존
`compute_hold_counterfactual`을 변경 없이 재사용하고 CASH
counterfactual만 신규로 추가한다. `market + selection + execution ==
cumulative_return` 항등식을 항상 정확히 만족하도록 `selection`을
정확한 residual(`cumulative_return - market - execution`)로 계산하여,
AI가 실제로 alpha를 만들어냈는지 시장 베타를 alpha로 착각하고 있는지를
분석할 수 있게 한다. `timing`/`sector`/`factor` attribution과
`alternative_action_1`/`alternative_action_2`(다른 모델/전략의 가상
의사결정 비교)는 검증되지 않은 방식으로 그럴듯하지만 틀릴 수 있는
숫자를 만드는 위험을 피하기 위해 계속 `None`으로 예약하고 Phase 11로
이연한다. 결과는 Phase 4의 DuckDB 저장소(`attribution_results` 테이블,
`CounterfactualRecord`는 Phase 3의 기존 `counterfactuals` 테이블을 그대로
재사용)에 영속화된다. 자세한 설계는
`docs/specifications/PHASE-10-counterfactual-attribution.md`와
`docs/decisions/ADR-0016-counterfactual-attribution.md` 참조.

## Model Evolution (Phase 11)

`src/evolution/`는 Phase 9의 `learning.enums.CandidateModelStatus`가
예약해 둔 `CANDIDATE → BACKTESTED → VALIDATED → OOS_TESTED` 상태
전이와, Phase 3/10이 이연한 `alternative_action_1`/
`alternative_action_2`, Phase 9가 "Model Registry completion (Phase
11)"으로 지정해 둔 lineage/versioning을 구현한다. `evolution.criteria.
evaluate_transition`은 각 전이마다 명시적, 버전 관리되는(`Promotion
Config`) 수치 기준(sample count 충분성, MAE/MSE finite 여부 등)을
검사하며, 실패한 시도도 절대 조용히 버리지 않고 항상 `passed`/`reason`
/`criteria` 딕셔너리를 담은 auditable `ModelStatusTransition` 레코드로
남긴다. `next_status`는 `APPROVED`/`DEPLOYED`로 매핑되는 항목이 dict
자체에 구조적으로 없어(AST 스캔으로 검증) 사람의 명시적 승인 없이는
그 어떤 코드 경로로도 배포 상태에 도달할 수 없다
(`PROJECT_MASTER_PLAN.md` §11.5). 두 번째 candidate 생성기
`TrailingWindowMeanTrainer`(ML 의존성 없는 deterministic baseline,
Phase 9의 `MeanRewardBaselineTrainer`와 동일한 "파이프라인을 증명하되
모델 자체를 주장하지 않는다" 원칙)로 여러 후보를 생성하고,
`compare_candidates`로 (winner/champion 필드 없이) 순위만 매겨
비교한다. `ModelLineageRecord`는 candidate의 generation을 항상
parent로부터만 파생시켜(caller가 임의로 지정 불가) lineage 체인의
깊이가 항상 일관되도록 보장한다 — 테스트 작성 중 서로 다른
`CandidateTrainer` 인스턴스의 독립적인 in-process id 발급기가 우연히
같은 candidate_id를 만들어 lineage가 자기 자신을 부모로 참조할 수
있는 버그를 발견해 구조적 검증을 추가로 고쳤다.
`compute_candidate_decision_alternative`는 실제 존재하고 실행 가능한
대안 결정 프로세스(Predictor + DecisionAgent)를 거래의 decision_time에
고정된 `AsOfDataView`로 실행해(신규 leakage guard 없이 기존
point-in-time 장치 재사용) 가상 결정을 얻고, 이를 Phase 3/10의 기존
hold/cash 수익률 계산으로 변환해 Phase 10의 `(HOLD, CASH)` 레코드에
추가만 한다(Phase 3/10 소스 수정 없음). Phase 1~10 소스코드는 전혀
수정하지 않고 `storage/schema.py`/`serialization.py`에 대한 순수
추가(`model_status_transitions`/`model_lineage` 테이블)만 있다. 자세한
설계는 `docs/specifications/PHASE-11-model-evolution.md`와
`docs/decisions/ADR-0017-model-evolution.md` 참조.

## 개발 원칙

- Live 모드는 기본값이 `false`이며 명시적으로 활성화해야 한다.
- API key 등 secret은 코드에 저장하지 않는다. `.env`는 커밋하지 않으며
  `.env.example`에는 변수 이름만 기록한다.
- Phase 순서를 임의로 건너뛰지 않는다 (`PROJECT_MASTER_PLAN.md` §18 참조).
