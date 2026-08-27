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

Phase 16이 `PROJECT_MASTER_PLAN.md`에 정의된 원래 마지막 공식 Phase다.
**Phase 17/18/19/20은 Master Plan의 정식 Phase가 아니라, Live 전환 전에
발견된 안전성·검증 문제를 보완하고 실제 시장 데이터 기반을 놓는 사후
검증/기반 작업**이다.

**Phase 20 — Real Market Data Foundation & Documentation Sync** (Live
Trading 활성화는 여전히 구조적으로 불가능 — Toss capability gap이
유일하지만 확실한 차단 사유는 그대로다). 실 미국 주식 시장 데이터를
안전하게 저장/조회할 수 있는 기반을 additive하게 구축했다: Tiingo를
1순위 provider로 선정(ADR-0025, 이 세션에서 접근 자체는 검증 불가 —
`api.tiingo.com` 포함 모든 후보 도메인이 네트워크 차단됨), 실제
`DataProvider` Protocol을 구현하는 `TiingoDataProvider`(가격 데이터 +
분할/배당 corporate action 추출), 16개 종목(15개 대형주 + SPY) pilot
universe 설계, 실 데이터용 데이터 품질 검사 5종 추가(Phase 1
`DataQualityFramework` 확장, 기존 동작 불변), S&P 500 벤치마크는 SPY를
proxy로 채택하고 TOTAL_RETURN을 목표 수익률 유형으로 결정(ADR-0026,
Phase 2부터 미결이던 DECISION REQUIRED 해소) — 배당 재투자 total-return
인덱스 생성기(`backtest.total_return`)까지 구현했으나 실 SPY 데이터는
아직 없어 실제 벤치마크 데이터는 여전히 없음(BENCHMARK_UNAVAILABLE
유지). 실 데이터 → `PaperMarketDataSource` → `PaperBrokerAdapter` →
Trade Journal → Monitoring → Performance Report 전체 경로가 구조적으로
연결됨을 end-to-end 테스트로 증명(항상 켜져 있는 polling loop는 이번
phase 요구사항이 아니어서 구현 안 함). Live risk limit 3개
(`max_daily_loss`/`max_turnover`/`max_order_frequency_per_hour`)에
대해 근거를 갖춘 제안값을 문서화했으나 최종 승인은 여전히 사람의 몫
(`docs/operations/LIVE-RISK-POLICY.md`, DECISION REQUIRED 유지).
Walk-Forward/PBO/Deflated Sharpe는 구체적 trigger 조건(스킬을 주장하는
첫 trainer 등장/복수 후보 비교/Live 승인 직전)을 문서화했으나 어느
조건도 아직 발생하지 않아 DEFER 유지. **세션 중간에 사용자가 Toss
Securities 공식 OpenAPI 3.1.0 스펙 전체를 직접 제공**했고, 이를 Tier 1
근거로 `TOSS-API-GAP-ANALYSIS.md`에 상세히 반영했으나(ACCOUNT_BALANCE/
POSITIONS/ORDER_STATUS/CANCEL_ORDER 엔드포인트/스키마 확인) Phase 13
어댑터 코드 자체는 이번 phase에서 변경하지 않음 — Phase 20 지침 자체가
"공식 문서가 오면 분석은 하되 구현은 별도 Phase로 제안"을 요구했기
때문(다음 권장 Phase로 명시). 상세는 `docs/PROJECT_STATUS.md` 참조.

**Phase 19 — Production Blocker Resolution** (Live Trading 활성화는
여전히 구조적으로 불가능. Toss capability gap이 유일하지만 확실한
차단 사유, `docs/operations/PRODUCTION-READINESS-MATRIX.md` 참조).
이번 phase는 코드를 전혀 수정하지 않았다 — Toss 공식 도메인 4곳
(`openapi`/`developers`/`home`/`corp`.tossinvest.com) 전부가 여전히
네트워크 차단되어 있음을 재확인했고, risk policy/Walk-Forward 채택
여부는 여전히 사람의 정책 판단이 필요하며, Paper Trading 상시 실행
loop는 실 시세 데이터 provider가 없어(ADR-0005 미해결과 동일한 외부
의존성) 지금 구현할 수 없음을 확인했다. 이 phase의 성공 기준은 "Live를
어떻게든 활성화하는 것"이 아니라 "불확실한 부분은 UNKNOWN으로,
정책 결정이 필요한 부분은 DECISION REQUIRED로 남기고 안전성을
유지하는 것"이었다.
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
- Phase 12 — AI Gateway: 완료 (`src/ai_gateway/`, 99 tests) — Master
  Plan §5의 `Application → AI Gateway → Task Router → Quota Manager →
  Provider Selector → Provider Adapter` 파이프라인을 그대로 구현. 유일한
  구현체 `MockProviderAdapter`는 결정적·오프라인이며 실제 네트워크 호출도
  `os.environ`/`os.getenv` 호출도 패키지 어디에도 없음(AST 스캔으로 검증)
  — API key 없이도 §6.5가 요구하는 5개 시나리오(A 정상 성공 / A quota
  exhausted → B 전환 / A·B·C 모두 실패 → 안전한 실패(NO AI CALL, 절대
  임의 콘텐츠 생성 없음) / A quota reset → 우선순위 복귀 / billing 감지 →
  disabled)를 전부 검증. `QuotaManager`가 모든 provider quota/health/
  billing 변화를 append-only 관측 기록으로 추적하고, 상태가 불확실한
  provider(UNKNOWN health/billing)는 항상 보수적으로(사용 중단 방향으로)
  처리. `trade_journal.enums.DecisionAction`/`learning.enums.
  CandidateModelStatus` import 자체가 패키지 어디에도 없어 Decision/Risk/
  Order/Broker나 Model Evolution의 APPROVED·DEPLOYED로 가는 경로가
  구조적으로 없음. Phase 1~11 소스코드 변경 없이 완전히 additive. Toss
  Securities Adapter, Monitoring, Paper/Live Trading은 여전히 범위 밖
  (Phase 13+)
- Phase 13 — Toss Securities Adapter: 완료 (`src/broker/`, 133 tests) —
  Master Plan §9.3의 broker-neutral `BrokerAdapter` Protocol
  (submit_order/cancel_order/get_order_status/get_account/
  get_positions/get_capabilities)을 구현. `risk.models.
  RiskCheckedPosition.final_target_quantity`(절대 목표치)와 caller가
  제공하는 현재 수량의 차이로 실제 매매 side/quantity를 계산하는
  `build_validated_order`가 이 저장소에서 유일하게 주문을 만드는
  지점(Decision/Risk를 우회하는 경로 없음, `decision.agent`/
  `risk.sizing`/`risk.engine`/`ai_gateway.gateway`/`learning.enums`
  import 자체가 `broker/*.py` 어디에도 없음을 AST 스캔으로 검증).
  `execution_mode` 기본값은 `OFFLINE`이며 `LIVE` 전환에는
  `execution_mode=LIVE`와 `live_opt_in=True` 두 개의 독립적인 명시적
  신호가 모두 필요(credential 존재만으로 활성화 불가) —
  `MockBrokerAdapter`만이 이 저장소 코드/테스트/backtest가 실제로
  호출하는 유일한 adapter. 실제 Toss증권 Open API를 리서치(공식
  GA 2026-08-13, **공개 sandbox 없음**을 확인)하여 확인된 것만 구현
  (`POST /oauth2/token` 인증, `POST /api/v1/orders` 주문 생성, 실제
  주문 상태값), 확인하지 못한 취소/상태조회/계좌조회 엔드포인트는
  추측하지 않고 `CapabilityStatus.UNKNOWN`/`BrokerCapabilityError`로
  처리. `os.environ`/`os.getenv`는 `broker/toss/auth.py` 단 한 곳에서만
  사용(AST 스캔으로 검증), 영속화된 request/response 어디에도 실제
  secret 값이 없음. Phase 1~12 소스코드 변경 없이 완전히 additive.
  Paper/Live Trading, Monitoring, 실제 실계좌 주문은 여전히 범위 밖
  (Phase 14+)
- Phase 14 — Monitoring: 완료 (`src/monitoring/`, 135 tests) — Master
  Plan §12(Kill Switch & 장애/복구 규칙)/§11.6(Drift Detection)을
  따르는 완전히 읽기 전용(read-only)인 관찰 계층. Phase 1~13의
  이미 계산된 결과만 소비해 데이터 품질/예측/의사결정/사이징/리스크/
  브로커/AI Gateway/학습/모델 진화 9개 컴포넌트의 metric을 계산하고
  (`metrics.py`), `MonitoringConfig` threshold로 `HEALTHY`/`DEGRADED`/
  `UNAVAILABLE`/`UNKNOWN` health를 판정하며(`health.py`), mean/variance/
  distribution shift 3종 deterministic drift 검출기(`drift.py`)와
  event/health/drift → `Alert` 순수 매핑(`alerts.py`)을 제공.
  `ComponentHealthStatus.UNKNOWN`/`DriftStatus.UNKNOWN`은 어디에서도
  `HEALTHY`/`NO_DRIFT`로 강제 변환되지 않고, drift 관찰은 항상 재검증
  트리거일 뿐 자동 모델 교체로 이어지지 않음(`learning.enums.
  CandidateModelStatus.APPROVED`/`DEPLOYED`로 가는 코드 경로가 전혀
  없음). 9개 collector(`collectors.py`) 전부 `as_of_time` 이전 레코드만
  명시적으로 필터링한 뒤 metric을 계산해 미래 데이터 유출을 구조적으로
  차단(leakage regression test로 검증). Phase 4 저장소(`monitoring_events`/
  `component_health_states`/`drift_results`/`alerts` 4개 테이블)에
  영속화, `risk_assessments`⋈`monitoring_events` SQL join(DuckDB
  `json_extract`)으로 lineage 증명. Phase 1~13 소스코드 변경 없이
  완전히 additive. 실제 alert 발송 채널(email/Slack), Alert
  승인·해제 워크플로우, Paper/Live Trading은 여전히 범위 밖(Phase 15+)
- Phase 15 — Paper Trading: 완료 (`src/broker/paper/`, 91 tests) —
  Master Plan §9.4("Trading Engine → Broker Interface → Paper
  Broker(개발/검증 기본값) / Toss Broker(Live 전용)")를 구현하는 완전히
  시뮬레이션된 `broker.protocol.BrokerAdapter`. 실행 가격 계산은 Phase
  2의 `TransactionCostModel`/`SlippageModel`/`Fill`을, 현금·포지션
  회계는 Phase 2의 `PortfolioAccounting`을 그대로 재사용(신규 병렬
  로직 없음). 주문은 여러 `advance_simulation` 호출에 걸쳐 부분
  체결이 누적될 수 있고(`PENDING`→`PARTIAL_FILLED`→`FILLED`), 동일
  `client_order_id` 재제출은 중복 체결을 만들지 않음. 시장 데이터는
  항상 caller가 공급하는 `PaperMarketDataSource`를 통해서만 접근하며
  (`available_time <= as_of`인 bar만 반환해 미래 데이터 유출을 구조적
  차단), `broker.paper.*` 어디에도 `data_infra.repository`/
  `backtest.asof`/`broker.toss.*`/`os.environ`/`os.getenv`/네트워크
  모듈 import가 없음(AST 스캔으로 검증, 유일한 예외는 `guard.py`의
  `TossBrokerAdapter` isinstance 전용 참조). `PaperTradingConfig.
  environment`는 구조적으로 `"paper"` 값만 허용. `PaperTradingSession.
  restore`가 재시작 후 현금/포지션/주문 상태를 완전히 동일하게
  재구성함을 실제 DuckDB 카탈로그로 검증. `build_trade_record`가
  Phase 3의 `TradeRecord`를 그대로 생성(provenance=PAPER_TRADING
  고정)하고, Phase 14의 `collect_broker`가 `monitoring/*.py` 수정 없이
  Paper의 request/response 감사 기록을 그대로 관찰함을 확인. Phase
  1~14 소스코드 변경 없이 완전히 additive. Live Trading 활성화 로직,
  상시 실행 Trading Engine 스케줄러, `paper_account_equity` 등 계정
  단위 지표의 Monitoring 연결은 여전히 범위 밖(Phase 16+, ADR-0021
  §8에 근거 명시)
- Phase 16 — Live Trading: 완료 (`src/broker/live/`, 137 tests) —
  Master Plan §9.4/§1.5/§12/§14.4를 구현하는 Live Trading 안전 계층.
  `evaluate_safety_gate`가 environment/live_trading_enabled/사람 승인/
  broker capability/risk health/order validator/kill switch/계좌·
  포지션 상태/model 상태/configuration integrity 11개 조건을 모두
  독립적으로 검사하는 순수 함수이며, 단 하나라도 실패하면 제출을 차단.
  **핵심 발견**: 이 게이트를 실제 `TossBrokerAdapter.get_capabilities()`
  (Phase 13이 `ACCOUNT_BALANCE`/`POSITIONS`/`ORDER_STATUS`/
  `CANCEL_ORDER`를 이미 정직하게 `UNKNOWN`으로 보고하도록 구현해 둔
  것)와 결합하면, 다른 모든 조건이 충족되어도 실제 Toss 계좌에 대한
  Live Trading이 구조적으로 활성화 불가능함을 실제 코드 실행으로 직접
  확인(새로운 제약이 아니라 Phase 13의 정직한 설계가 낳은 자연스러운
  결과, ADR-0022 §2). Kill switch는 `engage_kill_switch`(deterministic
  코드가 자동 호출 가능)와 `release_kill_switch`(`LiveActivationApproval`
  필수 — `approved_by`가 "AI"/"SYSTEM"/"CLAUDE"이면 구조적으로 거부)로
  비대칭 설계되어 해제 경로가 저장소 전체에서 자기 자신의 테스트 외에는
  없음을 AST로 검증. Reconciliation(계좌/포지션/주문상태 3종 순수 비교)
  은 불일치·불명 상태를 절대 MATCHED로 강제 변환하지 않고 세션 전체의
  신규 주문을 차단하며, 제출 중 예외는 재시도 없이 UNKNOWN으로 기록.
  `build_trade_record`가 Phase 3의 `TradeRecord`를 그대로 생성
  (provenance=LIVE_TRADING 고정)하고, Phase 14의 `collect_broker`가
  `monitoring/*.py` 수정 없이 Live의 감사 기록을 그대로 관찰함을 확인.
  Phase 1~15 소스코드 변경 없이 완전히 additive. daily loss limit 구체
  숫자, 자본 배분 정책, 상시 스케줄러, Toss 미확인 endpoint 확인은
  여전히 범위 밖(운영 절차는 `docs/operations/LIVE-TRADING-RUNBOOK.md`)

- Phase 17 — Production Safety Review: 완료 (신규 기능 없음, 검증 +
  최소 수정 + 신규 테스트 81개) — 10개 검토 영역 전부 판정. **실제
  버그 발견/수정**: Trade Journal의 `record_trade` 자연키가
  `fill.order_id`만 사용해 한 주문의 두 번째 이후 partial fill이
  조용히 소실되던 문제(Phase 3부터, Paper/Live 공통)를 `fill.
  execution_time` 추가로 수정. Toss 5xx 응답이 `REJECTED`로 오분류되던
  문제를 신규 `BrokerProviderError`로 분리해 수정. Kill Switch에
  `data_health` 트리거 추가, Phase 15/ADR-0021이 미해결로 남긴 계좌
  equity/PnL/drawdown → Monitoring 연결(`MonitoringComponent.ACCOUNT`)을
  완료(신규 ADR-0023). Candidate→APPROVED/DEPLOYED 자동 전이 경로 없음을
  `evolution` 패키지 한정이 아닌 저장소 전체 AST 스캔으로 재확인.
  Paper→Journal→Experience→Learning 5개 시나리오(A-E)를 실제 코드로
  추적. Toss 공식 문서 접근은 여전히 차단(3rd-party 미러에서 후보
  endpoint 발견했으나 승격하지 않음). 신규 문서: `docs/operations/
  LIVE-RISK-POLICY.md`, `docs/operations/TOSS-API-GAP-ANALYSIS.md`,
  `docs/operations/PRODUCTION-READINESS-MATRIX.md`, ADR-0023. 남은
  Known Issue: Paper Trading에 Sharpe/Sortino/Calmar 등 자체 성과
  리포트가 아직 없음 — "Paper 수익률 > benchmark"만으로 Live 자격을
  판단하지 않는다는 원칙에 따라 향후 Phase에서 구축 필요.

- Phase 18 — Production Safety Follow-up + Paper Trading Validation:
  완료 (`src/broker/paper/performance.py`, 신규 테스트 54개) — Paper
  Trading의 자체 성과 리포트(Sharpe/Sortino/Calmar/drawdown/turnover/
  transaction cost/slippage/승률/평균 거래 수익/실현 손익 + S&P 500
  벤치마크 비교)를 신규 구현. 데이터가 부족하거나 분모가 0인 모든
  경우를 `0.0`으로 임의 대체하지 않고 명시적 reason(`insufficient_data`/
  `zero_volatility`/`zero_downside_deviation`/`zero_drawdown`)으로
  기록. `backtest.metrics`는 수정하지 않고 병렬 모듈로 구현(기존 동작
  보존), `PaperBrokerAdapter`가 이미 쓰던 `PortfolioAccounting`을
  읽기 전용 property 1개로 노출해 재사용(중복 accounting 시스템 없음).
  실제 S&P 500 데이터가 이 저장소에 없음을 재확인 — 벤치마크 비교는
  `BENCHMARK_UNAVAILABLE`을 정직하게 반환. Phase 17의 두 버그 수정
  (partial fill 자연키, Toss 5xx 처리)을 Live 경로와 전체 파이프라인
  으로 재검증. Live Safety Gate의 9개 차단 차원(계좌/포지션/주문상태/
  브로커 capability/reconciliation/model/risk/data health/monitoring
  health) 전부가 실제로 차단하는지 확인 — 이미 보장되던 구조는
  중복 구현하지 않고 regression test만 추가. Walk-Forward/PBO/Deflated
  Sharpe Ratio를 원 논문 인용과 함께 연구
  (`docs/research/walk-forward-pbo-deflated-sharpe.md`), 구현 여부는
  DECISION REQUIRED로 남김. risk policy가 미설정일 때 Live를 구조적
  으로 차단할지 여부도 별도 DECISION REQUIRED로 보고 — 임의로 결정하지
  않음.

- Phase 19 — Production Blocker Resolution: 완료, **코드 변경 없음**
  (조사만 수행). Toss 공식 도메인 4곳(`openapi`/`developers`/`home`/
  `corp`.tossinvest.com) 전부 재시도했으나 여전히 네트워크 차단 —
  도메인 전체 차단(경로별 문제 아님)임을 확인. Risk policy `None` 값을
  "미집행"으로 둘지 Live를 구조적으로 차단할지 양쪽 근거를 상세 분석
  했으나 여전히 사람의 위험 허용도 판단이 필요해 DECISION REQUIRED로
  유지(임의 결정 안 함). Walk-Forward/PBO/Deflated Sharpe는 Live
  Safety Gate에 불필요하고(gate는 실행 안전성, 이것은 모델 신뢰도
  문제) 적용할 후보 모델도 아직 없어 DEFER로 판정. Paper Trading 상시
  실행 loop는 실 시세 provider가 없어(ADR-0005 미해결과 동일한 외부
  의존성) 구현 불가능함을 확인 — DEFER. 이 모든 결론은 "Live를 어떻게든
  활성화하는 것"이 아니라 "불확실하면 UNKNOWN, 정책이 필요하면 DECISION
  REQUIRED, 해결 불가능하면 BLOCKED로 정직하게 남기는 것"을 기준으로
  내려졌다.

- Phase 20 — Real Market Data Foundation & Documentation Sync: 완료
  (`src/data_infra/providers/`, `src/backtest/total_return.py`, 신규
  테스트 49개 + 문서 다수) — 신규 소스 모듈: `TiingoDataProvider`(실제
  `DataProvider` Protocol 구현체, 2-인자 `normalize()` 시그니처를
  `IngestionRunner`와 정확히 맞춤, `_fetched_as_of` 레코드 스탬핑으로
  `datetime.now()` 없이 point-in-time 준수), 전용 credential 격리
  파일(`tiingo_auth.py`, AST 스캔으로 `broker/toss/auth.py`와 함께
  허용 목록에 추가), `TiingoHttpTransport`(stdlib `urllib.request`
  기반, 모든 테스트는 stub/monkeypatch만 사용 — 실제 네트워크 호출
  없음). `DataQualityFramework`에 5개 체크 추가
  (`ingestion_precedes_availability`/`missing_timestamp_gaps`/
  `split_consistency`/`dividend_consistency`/`insufficient_coverage`,
  전부 opt-in 파라미터로 기존 호출부 동작 불변). `backtest.
  total_return.build_total_return_benchmark_points`가 원시 가격 +
  corporate action으로부터 배당재투자 지수를 point-in-time-safe하게
  재구성(과거 지수 값이 나중에 발견된 배당/분할로 절대 재계산되지
  않음, look-ahead guard와 동일한 `available_time` 규율 재사용).
  **실제로 발견/수정한 버그**: `TiingoDataProvider.
  normalize_corporate_actions`가 corporate action의 `available_time`을
  이벤트 발효일로 역산해 설정하고 있었음 — "나중에 발견된 사실이 그
  발효일 기준으로 즉시 조회 가능해지는" point-in-time 유출이었고, 신규
  point-in-time regression test(실제 DuckDB 저장소 + 재시작 검증)로
  발견해 `ingestion_time`으로 수정, 동일 버그 클래스를 잡는
  `ingestion_precedes_availability` 품질 체크도 함께 추가.
  세션 중간에 사용자가 제공한 Toss 공식 OpenAPI 스펙을 Tier 1 근거로
  `TOSS-API-GAP-ANALYSIS.md`에 전면 반영(엔드포인트/스키마/주문취소 시
  신규 orderId 발급/OAuth2 토큰 TTL 86400초로 정정 등)했으나 어댑터
  코드는 의도적으로 변경하지 않음 — 구현은 별도 Phase로 제안. 신규
  문서: ADR-0025(provider 선정), ADR-0026(벤치마크 return type),
  `docs/operations/MARKET-DATA-PROVIDER.md`(pilot universe),
  `docs/operations/MARKET-DATA-FX-REFERENCE.md`(KRW/USD, 값 없이
  placeholder만), `LIVE-RISK-POLICY.md`/`walk-forward-pbo-deflated-
  sharpe.md` 확장. Phase 1~19 소스코드 변경 없이 완전히 additive(Trade
  Journal/Monitoring/Paper Trading Session/Broker 계층 등 하위 모듈은
  전혀 수정하지 않음). Live Trading 활성화, 실제 Tiingo 네트워크 접근
  검증, 실 SPY 데이터 수집은 여전히 범위 밖/BLOCKED.

전체 테스트: **최신 카운트는 `docs/PROJECT_STATUS.md` 참조**
(Phase 1+2+...+19 = 1399 + Phase 20 신규 49 = 1448 이상; 정확한 최종
숫자는 이 Phase의 최종 전체 테스트 실행 결과를 따른다).

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

## AI Gateway (Phase 12)

`src/ai_gateway/`는 Master Plan §5가 요구하는 "전체 애플리케이션에서 AI
API를 직접 호출하지 않는다"는 원칙의 단일 진입점이다. `AIGateway.
generate(request, as_of=...)`가 `TaskRouter`(작업 등급별 provider
후보) → `ProviderSelector`(`QuotaManager`가 지금 실제로 쓸 수 있다고
판단한 후보만 필터) → `AIProviderAdapter.generate()` 순서로
오케스트레이션한다. 이번 Phase가 제공하는 유일한 구현체는
`MockProviderAdapter` — 결정적이고 완전히 오프라인이며, 실제 provider에
연결하지 않고 API key도 요구하지 않는다(`os.environ`/`os.getenv`
호출은 물론 `socket`/`http`/`urllib`/`requests`/`httpx` import조차
패키지 어디에도 없음을 AST 스캔으로 검증). `failure_mode` 파라미터로
Master Plan §6.5가 요구하는 모든 시나리오(정상 성공, timeout, auth
실패, rate limit, malformed/missing-field 응답, provider 자체 오류)를
결정적으로 재현한다. `QuotaManager`는 provider별 quota/health/billing
상태를 Phase 5의 `RegimeObservation`과 동일한 append-only 관측 기록으로
추적하며, `is_available`이 모든 라우팅 결정이 반드시 거치는 단일
fail-closed 게이트다 — health/billing 상태가 불확실한(UNKNOWN) provider는
UNAVAILABLE/PAID_DETECTED와 동일하게 보수적으로 처리되어 절대 선택되지
않는다. Provider가 전부 소진/실패하면 `AIGateway`는 절대 임의의 콘텐츠를
만들어내지 않고 사실적인 실패 상태(`TIMEOUT`/`AUTH_FAILED`/
`RATE_LIMITED`/`INVALID_RESPONSE`/`PROVIDER_ERROR`/`NO_PROVIDER_AVAILABLE`/
`MISSING_CONFIGURATION`)를 반환한다(`AIResponse.__post_init__`이
SUCCESS↔content 존재, 그 외 상태↔error_reason 존재를 구조적으로
강제). `trade_journal.enums.DecisionAction`/`learning.enums.
CandidateModelStatus`는 `ai_gateway/*.py` 어디에서도 import되지 않아
Decision/Risk/Order/Broker나 Model Evolution의 APPROVED/DEPLOYED로
가는 경로가 구조적으로 없다. `generate()`는 `as_of`를 기본값 없는 필수
인자로 요구하고 `data_infra.repository`/`backtest.asof`를 전혀
import하지 않아 이 계층이 직접 시장/의사결정 데이터를 조회할 방법이
없다. 결과는 Phase 4의 DuckDB 저장소(`ai_requests`/`ai_responses`/
`provider_quota_states` 테이블)에 영속화된다. 자세한 설계는
`docs/specifications/PHASE-12-ai-gateway.md`와
`docs/decisions/ADR-0018-ai-gateway.md` 참조.

## Toss Securities Adapter (Phase 13)

`src/broker/`는 Master Plan §9.3의 broker-neutral 인터페이스
(`BrokerAdapter` Protocol: submit_order/cancel_order/
get_order_status/get_account/get_positions/get_capabilities)를
구현한다. `broker.validation.build_validated_order`가 이 저장소에서
유일하게 실제 매매 side/quantity를 계산하는 지점이다 — Phase 8의
`RiskCheckedPosition.final_target_quantity`는 절대 목표치(delta 아님)
이므로, caller가 제공하는 현재 보유 수량과의 차이를 계산해야만 실제
주문이 나온다. `client_order_id`는 decision/sizing/risk lineage +
symbol/side/quantity/as_of_time의 결정적 해시라서, 모호한 실패 후
재시도해도 동일한 idempotency key로 재제출된다(중복 주문 방지).
`decision.agent`/`risk.sizing`/`risk.engine`/`ai_gateway.gateway`/
`learning.enums` import 자체가 `broker/*.py` 어디에도 없어(AST
스캔으로 검증) Decision/Risk/AI Gateway를 우회하거나 Model Evolution의
APPROVED/DEPLOYED에 접근할 방법이 구조적으로 없다.

`BrokerConfig.execution_mode` 기본값은 `OFFLINE`이며, `LIVE`로
전환하려면 `execution_mode=LIVE`와 `live_opt_in=True` 두 개의 독립적인
명시적 신호가 모두 필요하다 — credential이 환경변수에 존재하는 것만으로는
활성화되지 않는다(`live_opt_in`이 패키지 어디서도 동적으로 계산되지
않고 항상 리터럴 값으로만 전달됨을 AST 스캔으로 검증). 이 저장소
자체의 코드/테스트/backtest가 실제로 호출하는 adapter는
`MockBrokerAdapter`(결정적, 완전 오프라인, accepted/rejected/
partially filled/filled/cancelled/broker unavailable 전부 시뮬레이션)
뿐이다.

`src/broker/toss/`는 실제 Toss증권 Open API(2026-08-13 정식 출시,
**공개 sandbox 환경 없음**을 리서치로 확인 — 이 환경의 network egress
proxy가 공식 문서 호스트를 차단해 OpenAPI spec을 직접 읽지 못했으나,
공식 GA 발표와 제3자 기술 문서로 base URL/인증 방식/주문 생성 API/실제
주문 상태값/에러 코드를 간접 확인) 연동을 위한 어댑터다. 확인된
엔드포인트(`POST /oauth2/token` 인증, `POST /api/v1/orders` 주문
생성)만 실제로 구현했고, 확인하지 못한 취소/상태조회/계좌조회
엔드포인트는 추측하지 않고 `CapabilityStatus.UNKNOWN`/
`BrokerCapabilityError`로 정직하게 처리한다. `TossBrokerAdapter`는
생성 시점에 `execution_mode == LIVE`를 강제하여 OFFLINE/SANDBOX 설정으로
아무 동작도 하지 않는 채 조용히 넘어가는 경로 자체가 없다.
`os.environ`/`os.getenv`는 `broker/toss/auth.py` 단 한 곳에서만
사용되며(AST 스캔으로 검증), resolve된 credential이나 access token은
어떤 영속 모델 필드에도 저장되지 않는다. 결과는 Phase 4의 DuckDB
저장소(`broker_requests`/`broker_responses`/`order_status_events`
테이블)에 영속화되며, Decision→Risk→ValidatedOrder→BrokerRequest→
BrokerResponse→OrderStatusObservation 전체 체인이 SQL join으로
증명된다. Phase 1~12 소스코드는 전혀 수정하지 않았다. 자세한 설계는
`docs/specifications/PHASE-13-toss-securities-adapter.md`와
`docs/decisions/ADR-0019-toss-securities-adapter.md` 참조.

## Monitoring (Phase 14)

`src/monitoring/`는 Master Plan §12(Kill Switch & 장애/복구 규칙)와
§11.6(Drift Detection)을 구현하는, Phase 1~13 위에 완전히 읽기 전용
(read-only)으로 얹히는 관찰 계층이다. 핸드오프의 표현을 그대로 빌리면
"Monitoring은 거래를 결정하는 계층이 아니다" — 이 패키지 어디에도
`broker.models.ValidatedOrder`를 생성/제출하거나
`risk.sizing`/`risk.engine`/`decision.agent`/`ai_gateway.gateway`를
직접 호출하는 코드 경로가 없다(AST 스캔으로 검증).

`monitoring.collectors`는 데이터 품질/예측/의사결정/사이징/리스크/
브로커/AI Gateway/학습/모델 진화 9개 컴포넌트 각각에 대해, 이미
계산되어 넘어온 레코드 시퀀스를 `<field> <= as_of_time`으로 먼저
필터링한 뒤에만 `monitoring.metrics`의 순수 함수를 호출한다 — 모든
collector가 기본값 없는 필수 `as_of_time` 파라미터를 요구하며, 미래
레코드를 추가해도 과거 시점 결과가 전혀 바뀌지 않음을 leakage
regression test로 직접 검증한다. `monitoring.health`는 실패율 기반
(Broker/AI Gateway/Risk/Sizing)과 존재 여부 기반(Prediction/Decision/
Learning/Model Evolution — `NO_TRADE`/`HOLD`는 정당한 출력이므로
"무엇을 생산했는가"가 아니라 "생산했는가"만 판정) 두 가지 평가자와
데이터 전용 평가자, 그리고 전체 파이프라인을 worst-of로 집계하는
평가자를 제공한다. `ComponentHealthStatus.UNKNOWN`은 다수의
`HEALTHY`에 의해 묻히지 않도록 `DEGRADED`보다 집계 우선순위가 높다 —
"모른다"를 절대 "건강하다"로 조용히 바꾸지 않는다.

`monitoring.drift`는 mean shift(z-score)/variance shift(분산 비율)/
distribution shift(baseline 범위 기준 등폭 버킷 빈도 차이 — 교과서적
PSI가 아닌 단순화된 "PSI-like" 통계량으로 명시) 3종의 deterministic
검출기를 제공하며, 표본이 `min_drift_sample_count` 미만이거나
baseline이 degenerate하면 항상 `UNKNOWN`을 반환한다. Drift가
감지되어도(`DriftStatus.DRIFT_DETECTED`) `monitoring.alerts`는 이를
`WARNING`으로만 처리한다(`CRITICAL`이 아님) — §11.6이 요구하는 대로
재검증 프로세스의 트리거일 뿐, 어떤 코드 경로도 이를 자동 모델 교체로
연결하지 않는다(`learning.enums.CandidateModelStatus.APPROVED`/
`DEPLOYED`로 가는 경로가 패키지 전체에 없음 — 단,
`compute_model_evolution_metrics`가 관측된 상태 전이를 세는 목적으로
그 enum을 읽기만 하는 것은 허용).

결과는 Phase 4의 DuckDB 저장소(`monitoring_events`/
`component_health_states`/`drift_results`/`alerts` 4개 테이블)에
영속화되며, `risk_assessments`⋈`monitoring_events`가 DuckDB
`json_extract`로 `MonitoringEvent.source_record_ids`를 조회하는 SQL
join으로 lineage가 증명되고 프로세스 재시작 후에도 그대로 보존된다.
Phase 1~13 소스코드는 전혀 수정하지 않았다. 실제 alert 발송 채널
(email/Slack 등)과 Alert 승인·해제(acknowledgement/resolution)
워크플로우는 Master Plan §12.5의 "초기에는 logging 중심으로 구현"에
따라 이번 Phase 범위에서 의도적으로 제외했다. 자세한 설계는
`docs/specifications/PHASE-14-monitoring.md`와
`docs/decisions/ADR-0020-monitoring.md` 참조.

## Paper Trading (Phase 15)

`src/broker/paper/`는 Master Plan §9.4("Trading Engine → Broker
Interface → Paper Broker(개발/검증 기본값) / Toss Broker(Live에서만,
명시적 활성화 후)")를 구현하는 완전히 시뮬레이션된
`broker.protocol.BrokerAdapter`(Phase 13) 구현체다. `PaperBrokerAdapter`
는 절대로 `TossBrokerAdapter`/Toss API/실제 네트워크/실계좌를 호출하지
않는다 — `broker.paper.*` 어디에도 `broker.toss.*`/`os.environ`/
`os.getenv`/`socket`/`http`/`urllib`/`requests`/`httpx` import가 없음을
AST 스캔으로 검증했고(유일한 예외는 `broker.paper.guard`의
`TossBrokerAdapter` isinstance 전용 참조 — 절대 생성/호출하지 않음),
`PaperTradingConfig.environment`는 구조적으로 `"paper"` 값만 허용한다.

실행 로직은 새로 만들지 않고 Phase 2를 그대로 재사용한다:
`backtest.costs.TransactionCostModel`/`FixedBpsSlippageModel`이 스프레드
·슬리피지·수수료를 계산하고, `backtest.portfolio.PortfolioAccounting`이
average-cost 기준으로 현금·포지션·realized PnL을 추적하며,
`backtest.fills.Fill`이 체결 결과 타입 그대로 쓰인다. 주문은
`floor(bar.volume × max_participation)`만큼만 한 번에 체결되고, 남은
수량은 이후 `advance_simulation(as_of)` 호출(시장 데이터가 더 확보될
때마다 명시적으로 시뮬레이션 시간을 진행시키는 Paper 전용 훅)에 걸쳐
누적 체결된다 — `PENDING → PARTIAL_FILLED → FILLED`. 동일
`client_order_id` 재제출은 새 주문을 만들지 않고 기존 응답을 그대로
반환한다(Phase 13의 idempotency 설계 그대로 재사용). 시장 데이터는
`PaperMarketDataSource`(caller가 직접 공급 — `broker.paper.*`는
`data_infra.repository`/`backtest.asof`를 전혀 import하지 않는다)를
통해서만 접근하며, `available_time <= as_of`인 bar만 반환해 미래 가격
유출을 구조적으로 차단한다.

현금 부족(`insufficient_cash`)/보유 초과 매도(`insufficient_position`,
`allow_short=False` 기본값)/최대 수량·명목가 초과는 전부 `REJECTED`로
fail-closed 처리하며, `failure_mode`(`timeout`/`auth`/`rate_limit`/
`unavailable`/`malformed`/`unknown_status`/`rejected`)로 실제 장애를
결정적으로 시뮬레이션할 수 있다 — `malformed`/`unknown_status`는
`UNKNOWN` 상태를 반환할 뿐 절대 체결(`FILLED`)로 오인되지 않는다.

`PaperBrokerAdapter` 자체는 Phase 13의 `MockBrokerAdapter`처럼 순수
in-memory이며 아무것도 영속화하지 않는다 — 영속화와 재시작 복구는
오케스트레이션 계층인 `PaperTradingSession`의 역할이다.
`PaperTradingSession.restore(...)`가 영속화된 주문(`paper_orders`)과
체결(`paper_fills`)만으로 어댑터의 현금·포지션·주문 상태를 완전히
동일하게 재구성함을 실제 DuckDB 카탈로그 재시작 테스트로 검증했다.
주문 상태 이력은 Phase 13의 기존 `order_status_events` 테이블을,
request/response 감사 로그는 기존 `broker_requests`/`broker_responses`
테이블을 스키마 변경 없이 그대로 재사용한다 — 신규 테이블은
`paper_orders`/`paper_fills` 2개뿐이다.

`broker.paper.journal.build_trade_record`는 Phase 3의
`trade_journal.models.TradeRecord`를 그대로 생성한다(별도의 독립적인
journal 체계를 만들지 않음) — provenance는 항상
`TradeProvenance.PAPER_TRADING`으로 고정된다. Phase 14의
`monitoring.collectors.collect_broker`/`compute_broker_metrics`는
`src/monitoring/*.py`를 전혀 수정하지 않고도 Paper Trading의
`broker_requests`/`broker_responses`를 그대로 관찰한다 — Monitoring
입장에서 Paper는 "또 하나의 broker_id"일 뿐이다.
`paper_account_equity`/`paper_pnl`/`paper_drawdown`은
`PaperTradingSession.account_summary()`로 값 자체는 제공하지만,
`MonitoringEvent`로의 실제 연결(Phase 14의 닫힌 `MonitoringComponent`
enum을 확장할지 여부)은 임의로 결정하지 않고 이번 Phase 범위에서
의도적으로 보류했다(ADR-0021 §8). Phase 1~14 소스코드는 전혀 수정하지
않았다. 자세한 설계는 `docs/specifications/PHASE-15-paper-trading.md`와
`docs/decisions/ADR-0021-paper-trading.md` 참조.

## Live Trading (Phase 16)

`src/broker/live/`는 Master Plan §9.4(Live Trading)/§1.5(kill switch는
AI가 해제 불가)/§12(Kill Switch & 장애/복구 규칙)/§14.4(`LIVE_TRADING
= false` 기본값)를 구현하는 안전 계층이다. Phase 15의 `PaperBrokerAdapter`
와 마찬가지로 `broker.protocol.BrokerAdapter`를 감싸지만, 목적은
"실제 broker를 호출한다"가 아니라 "언제, 어떤 조건 아래에서만 그것이
허용되는가"를 결정하는 것이다.

`broker.live.safety_gate.evaluate_safety_gate`는 순수 함수로 11개
조건 — environment == "live" / `live_trading_enabled` / 사람이 만든
`LiveActivationApproval` / broker capability 검증 / risk engine
health / order validator 결과 / kill switch / 계좌 상태 / 포지션
상태 / model 상태(`APPROVED`/`DEPLOYED`만 유효 — Phase 11이 애초에 그
경로를 만들지 않았으므로 오늘 기준 항상 미충족) / configuration
integrity — 를 전부 독립적으로 검사하며, 단 하나라도 실패하면 주문이
broker에 도달하지 않는다.

**가장 중요한 발견**: 이 게이트의 broker capability 조건을 실제
`TossBrokerAdapter.get_capabilities()`(Phase 13이 `ACCOUNT_BALANCE`/
`POSITIONS`/`ORDER_STATUS`/`CANCEL_ORDER`를 이미 정직하게 `UNKNOWN`
으로 보고하도록 구현해 둔 것, ADR-0019)과 결합해 실제로 실행해 보면,
다른 열 가지 조건이 전부 충족되어도 실제 Toss 계좌에 대한 Live
Trading이 구조적으로 활성화되지 않는다(`tests/broker/live/
test_live_safety_gate.py::TestRealTossCapabilitiesStructurallyBlockLiveTrading`
로 직접 검증). 이는 이번 Phase가 만든 새로운 제약이 아니라, Phase
13이 "확인되지 않은 endpoint는 추측하지 않는다"고 정직하게 내린
설계 결정이 활성화 게이트까지 그대로 이어진 자연스러운 결과다
(ADR-0022 §2).

Kill switch는 비대칭으로 설계된다: `engage_kill_switch`는
deterministic 파이프라인 코드(`LiveTradingSession` 자신)가 자동으로
호출할 수 있지만, `release_kill_switch`는 `LiveActivationApproval`을
반드시 요구하며 그 객체의 `approved_by` 필드가 "AI"/"SYSTEM"/"CLAUDE"
이면 구조적으로 생성 자체가 거부된다 — 저장소 전체를 AST로 스캔해
`release_kill_switch`의 실제 호출 지점이 자기 자신의 테스트 외에는
없음을 확인했다. Reconciliation(`compare_account`/`compare_positions`/
`compare_order_status`)은 내부 상태와 broker의 authoritative 상태가
다르거나 어느 한쪽이라도 확인 불가능하면 절대 `MATCHED`로 강제
변환하지 않고, `LiveTradingSession`은 그 결과가 해소되기 전까지 세션
전체의 신규 주문을 차단한다. 제출 중 timeout/connection lost가
발생해도 재시도하지 않고 주문을 `UNKNOWN`으로 기록한다 — "응답을 받지
못했다"는 "주문이 생성되지 않았다"는 뜻이 아니기 때문이다.

`broker.live.journal.build_trade_record`는 Phase 3의 `TradeRecord`를
그대로 생성하며(provenance=LIVE_TRADING 고정), Toss의 확인된 응답
스키마가 기준가/스프레드/슬리피지 분해를 제공하지 않는다는 사실을
`reference_price = price`로 정직하게 문서화한다(측정되지 않은 값을
0으로 조작하지 않음). Phase 14의 `collect_broker`는 `monitoring/*.py`
수정 없이 Live의 `broker_requests`/`broker_responses`를 그대로
관찰한다. Phase 1~15 소스코드는 전혀 수정하지 않았다. daily loss
limit 구체 숫자나 자본 배분 정책은 이번 Phase가 임의로 정하지 않고
`LiveTradingConfig.max_daily_loss=None`(미설정)으로 남겨두었다 —
운영자가 명시적으로 설정해야만 효과가 있다. 실제 활성화 절차는
`docs/operations/LIVE-TRADING-RUNBOOK.md`에 별도로 문서화했다(어떤
secret 값도 포함하지 않음). 자세한 설계는
`docs/specifications/PHASE-16-live-trading.md`와
`docs/decisions/ADR-0022-live-trading.md` 참조.

## Production Safety Review (Phase 17)

Phase 16이 만든 Live Trading 안전 인프라를 실제 돈이 들어가기 전에
검증하는 단계 — 새 기능을 만드는 phase가 아니다. "자동화된 테스트
통과 ≠ 프로덕션 준비 완료"를 원칙으로 10개 영역(Toss API capability,
Live risk policy, Paper Trading readiness, Paper→Learning lineage,
Candidate 검증 경계, Live activation 안전성, Broker reconciliation,
Monitoring/drift, Kill switch/rollback, Runbook)을 실제 코드를
실행하고 읽어 재검증했다.

이 과정에서 실제 버그 두 건을 발견해 수정했다: (1) Trade Journal의
`record_trade`가 `fill.order_id`만으로 자연키를 구성해, 한 주문이 여러
번에 나뉘어 체결될 때(partial fill) 두 번째 이후 체결이 "이미 기록된
중복"으로 오인되어 조용히 소실되고 있었다 — Paper와 Live 모두에
영향을 미치는, Phase 3부터 존재했던 결함이다. `fill.execution_time`을
자연키에 추가해 수정했고, 기존 idempotency 테스트는 전부 그대로
통과한다(진짜 재시도는 여전히 중복 제거됨). (2) Toss의 5xx 응답이
`REJECTED`(확정적 거부)로 매핑되고 있었는데, 5xx는 브로커 인프라
장애일 뿐 주문이 실제로 처리되었는지 여부를 전혀 알려주지 않는다 —
신규 `BrokerProviderError`로 분리해 `LiveTradingSession`이 이미 갖고
있던 UNKNOWN/RECONCILIATION_REQUIRED 경로로 정확히 흐르게 했다
(`session.py` 자체는 수정 불필요).

추가로 Phase 15/ADR-0021이 미해결로 남겨둔 "`paper_account_equity`/
`paper_pnl`/`paper_drawdown`이 MonitoringEvent로 연결되지 않음" 문제를
`MonitoringComponent.ACCOUNT`(신규, additive)로 해결했고, Phase 14의
data quality health가 지금까지 Kill Switch 트리거에 연결되어 있지
않았던 gap도 메웠다. Candidate 모델이 `APPROVED`/`DEPLOYED`로 자동
전이하는 경로가 없다는 사실은 `evolution` 패키지 범위가 아닌 **저장소
전체(`src/`)**를 AST로 스캔해 재확인했다.

Toss 공식 문서(`openapi.tossinvest.com`, `developers.tossinvest.com`)에
대한 네트워크 접근은 이번 세션에서도 여전히 차단되어 있음을 직접
재확인했다. 제3자 GitHub 저장소(`BEOKS/tossinvest-skill`)가 미러링하는
OpenAPI 스펙에서 `/api/v1/accounts`/`/api/v1/holdings`/`/api/v1/orders`
후보 endpoint를 발견했지만, 공식 1차 문서가 아니므로 어떤 capability도
`ENABLED`로 승격하지 않았다 — `ACCOUNT_BALANCE`/`POSITIONS`/
`ORDER_STATUS`/`CANCEL_ORDER`는 여전히 `UNKNOWN`이며, 이는 지금도
Live Trading을 구조적으로 차단하는 유일하지만 확실한 사유다.

Paper Trading의 실제 코드 경로(Order→Fill→Journal→Experience)를 5개
시나리오(BUY 체결, partial→full 체결, Risk에 의한 REJECTED, 브로커
장애, 완결된 거래→Post Trade Analysis→Counterfactual→Learning
Dataset)로 추적해 모두 통과를 확인했다. 다만 Paper Trading에는
`backtest.metrics.PerformanceReport`에 해당하는 자체 성과 리포트
(Sharpe/Sortino/Calmar/변동성/turnover/benchmark 비교)가 전혀 없다는
사실도 함께 확인했다 — "Paper 수익률이 벤치마크보다 높다"는 것만으로
Live 자격을 판단해서는 안 된다는 원칙을 지키기 위해 반드시 필요하지만,
이번 phase의 최소 수정 범위를 넘어서는 신규 구축이므로 향후 Phase로
남겼다.

신규 문서: `docs/specifications/PHASE-17-production-safety-review.md`,
`docs/operations/LIVE-RISK-POLICY.md`(13개 정책 항목 분류, 숫자를
임의로 정하지 않고 DECISION REQUIRED 3건으로 남김),
`docs/operations/TOSS-API-GAP-ANALYSIS.md`,
`docs/operations/PRODUCTION-READINESS-MATRIX.md`,
`docs/decisions/ADR-0023-production-safety-review.md`. 이번 phase가
내린 최종 판정은 하나: **READY FOR HUMAN REVIEW** — "사람의 최종
검토를 받을 만큼 기술적으로 준비되었다"는 뜻이며, "실제 돈을 넣어도
안전하다"는 뜻이 결코 아니다.

## Paper Trading Performance Report (Phase 18)

Phase 17이 남긴 가장 명확한 gap — Paper Trading에 raw PnL 외의 성과
평가가 전혀 없었던 문제 — 를 해결하는 phase. `broker.paper.performance`
가 total return/CAGR/변동성/Sharpe/Sortino/Calmar/최대 drawdown/
turnover/거래비용/슬리피지/거래 건수/승률/평균 거래 수익/실현 손익과
S&P 500 벤치마크 비교를 계산한다. `backtest.metrics`(Phase 2)는 데이터
부족이나 0으로 나누는 경우를 전부 `0.0`으로 대체하는데, 이는 이번
phase의 "값이 없으면 0을 임의로 넣지 않는다" 원칙과 충돌하므로 그
모듈을 수정하는 대신(기존 Phase 2/4 동작을 깨뜨릴 위험) 완전히 새로운
병렬 모듈을 만들었다 — 모든 계산 불가 상황은 `insufficient_data`/
`zero_volatility`/`zero_downside_deviation`/`zero_drawdown`/
`not_supplied` 같은 명시적 사유로 기록된다.

중복 회계 시스템을 만들지 않기 위해, `PaperBrokerAdapter`가 이미
내부적으로 쓰고 있던 `backtest.portfolio.PortfolioAccounting` 인스턴스를
읽기 전용 property(`adapter.accounting`) 하나로 노출해 그대로
재사용했다 — 기존 호출자 누구의 동작도 바뀌지 않는다. 거래 건수/승률/
평균 수익/실현 손익/거래비용/슬리피지는 `PortfolioAccounting`의 자체
거래 목록이 아니라 Trade Journal(Phase 3)의 `TradeRecord`에서 집계한다
— 두 개의 경쟁하는 거래 목록을 만들지 않기 위함이다. 벤치마크는
`backtest.benchmark.BenchmarkEngine`(Phase 2)을 그대로 재사용했는데,
이 저장소에는 실제 S&P 500 가격 데이터가 전혀 없으므로(ADR-0005 미해결)
가짜 데이터를 만드는 대신 `BENCHMARK_UNAVAILABLE`을 정직하게 반환하도록
설계했다.

이번 phase는 또한 Phase 17이 고친 두 버그 — Trade Journal의 partial
fill 자연키 충돌, Toss 5xx 오분류 — 를 Live 경로/전체 파이프라인으로
재검증했고, Live Safety Gate의 9개 차단 차원(계좌/포지션/주문상태/
브로커 capability/reconciliation/model/risk/data health/monitoring
health)이 실제로 신규 주문을 막는지 확인했다 — `evaluate_safety_gate`의
실제 호출 지점이 정확히 두 곳뿐이고 둘 다 이미 reconciliation을
독립적으로 확인하고 있음을 발견해, 코드를 중복 추가하는 대신 각
차원의 실제 집행 경로를 증명하는 regression test만 추가했다.

Walk-Forward Validation/Purged K-Fold/Embargo/PBO/Deflated Sharpe
Ratio는 원 논문(Bailey/Borwein/López de Prado/Zhu 2015; Bailey/López
de Prado 2014)을 인용해 연구했지만(`docs/research/
walk-forward-pbo-deflated-sharpe.md`) 구현하지 않았다 — 이를 향후 모델
신뢰 기준으로 채택할지는 DECISION REQUIRED로 남겼다. Risk policy가
`None`(미설정)일 때 Live를 구조적으로 차단할지 여부도 마찬가지로
DECISION REQUIRED로 보고했다 — 둘 다 이 프로젝트의 "AI가 정책을 임의로
결정하지 않는다"는 원칙에 따라 코드로 임의 결정하지 않았다. 자세한
설계는 `docs/specifications/PHASE-18-paper-performance-and-validation.md`
와 `docs/decisions/ADR-0024-paper-performance-and-validation.md` 참조.

## 개발 원칙

- Live 모드는 기본값이 `false`이며 명시적으로 활성화해야 한다.
- API key 등 secret은 코드에 저장하지 않는다. `.env`는 커밋하지 않으며
  `.env.example`에는 변수 이름만 기록한다.
- Phase 순서를 임의로 건너뛰지 않는다 (`PROJECT_MASTER_PLAN.md` §18 참조).
