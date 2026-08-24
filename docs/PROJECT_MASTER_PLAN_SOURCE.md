# PROJECT_MASTER_PLAN_SOURCE.md

> 이 문서는 프로젝트를 시작할 때 사용자가 Claude Code에게 최초로
> 전달한 원문 지시사항을 **한 글자도 고치지 않고 그대로** 보존한
> 1차 출처(source) 문서다.
>
> `PROJECT_MASTER_PLAN.md`는 이 원문의 내용을 Claude Code가 재구성하여
> 정리한 버전이며, 이 문서와 다른 구조/표현을 가질 수 있다. 재구성본과
> 원문이 어긋나는 부분이 있는지 확인해야 할 때는 이 문서를 기준으로
> 대조한다.
>
> 이 파일 자체는 이후에도 수정하지 않는다 — 원문 보존이 목적이다.

---

AUTONOMOUS AI INVESTMENT SYSTEM

CLAUDE CODE INITIALIZATION & MASTER SPECIFICATION

Version 1.0

---

0. 이 문서의 목적

너는 이 프로젝트의 첫 번째 개발 세션을 수행하는 Claude Code다.

이 프로젝트는 단순한 주식 예측 프로그램이나 단순한 자동매매 봇을 만드는 프로젝트가 아니다.

우리가 구축하려는 것은 다음과 같은 자율형 AI 투자 연구·검증·학습·실행 시스템이다.

«시장 데이터를 관찰하고, 시장 상태를 분석하고, 투자 의사결정을 내리고, 포지션과 위험을 계산하고, 주문을 실행하며, 모든 의사결정과 거래 결과를 기록하고, 그 경험을 학습 데이터로 축적하고, 새로운 모델/전략을 생성하고, 엄격한 검증을 통과한 경우에만 새로운 모델을 실전 시스템에 배포할 수 있는 시스템.»

최종 목표는:

«장기적으로 S&P 500의 수익률을 초과하는 것을 목표로 하는 자율형 AI 투자 시스템을 구축하는 것»

이다.

단, 초과수익을 보장한다고 가정하지 않는다.

이 프로젝트의 성공 기준은 단순히 높은 백테스트 수익률이 아니다.

다음 조건을 동시에 만족하는 시스템을 만드는 것이 목표다.

- 수익성
- 위험 통제
- 과적합 방지
- 데이터 누수 방지
- 재현성
- 실전 거래 가능성
- 거래비용 반영
- 지속적인 학습
- 모델 변경 추적
- 장애 대응
- 안전한 자동화

---

1. 가장 중요한 지시

절대로 이 프로젝트를 일반적인 코딩 프로젝트처럼 다루지 마라.

특히 다음과 같은 행동을 하지 마라.

- 바로 자동매매부터 구현하지 마라.
- 바로 실계좌 주문 기능부터 구현하지 마라.
- 임의의 AI 모델 하나를 선택해서 전체 시스템을 만들지 마라.
- 백테스트 성능이 높다는 이유만으로 모델을 채택하지 마라.
- 데이터를 쉽게 구할 수 있다는 이유로 미래 정보가 섞인 데이터를 사용하지 마라.
- Trade Journal을 나중에 추가할 기능으로 취급하지 마라.
- 학습 시스템을 나중에 추가할 기능으로 취급하지 마라.
- AI가 직접 증권사 API를 호출하도록 만들지 마라.
- AI가 검증 없이 Live 모델을 교체하도록 만들지 마라.
- 무료 API 한도를 초과하여 자동으로 유료 과금되는 구조를 만들지 마라.
- 프로젝트 계획을 임의로 단순화하지 마라.

---

2. 이 문서를 프로젝트의 Source of Truth로 취급한다

프로젝트 루트에 반드시 다음 파일을 생성한다.

PROJECT_MASTER_PLAN.md

이 파일은 프로젝트의 최상위 설계 문서다.

이 문서의 내용과 현재 구현 코드가 충돌할 경우, 코드가 자동으로 옳다고 가정하지 않는다.

계획과 코드가 다르면 그 차이를 기록하고 원인을 분석한다.

---

3. 프로젝트 영속성

Claude Code의 대화 컨텍스트는 영구 저장소가 아니다.

따라서 이 프로젝트는:

«"AI가 기억하는 프로젝트"가 아니라 "파일이 기억하는 프로젝트"»

가 되어야 한다.

새로운 Claude Code 세션이 시작되었을 때에도 다음 파일을 읽으면 프로젝트 전체 상황을 복구할 수 있어야 한다.

필수:

PROJECT_MASTER_PLAN.md
docs/PROJECT_STATUS.md
docs/decisions/

추가적으로 각 Phase의 specification 문서를 읽는다.

---

4. 최초 디렉터리 구조

최초에는 최소 다음 구조를 준비한다.

/
├── PROJECT_MASTER_PLAN.md
├── README.md
├── .gitignore
├── .env.example
│
├── docs/
│   ├── PROJECT_STATUS.md
│   │
│   ├── architecture/
│   ├── research/
│   ├── specifications/
│   ├── decisions/
│   ├── development/
│   └── operations/
│
├── src/
├── tests/
├── scripts/
├── configs/
├── data/
├── experiments/
└── logs/

단, 기존 프로젝트 파일이 존재한다면 삭제하지 않는다.

먼저 조사한다.

---

5. 첫 번째 세션의 임무

첫 번째 세션에서는 실제 투자 기능을 구현하는 것이 목표가 아니다.

다음 작업이 목표다.

Step 1

현재 repository를 조사한다.

Step 2

현재 파일 구조를 파악한다.

Step 3

기존 코드가 있다면 분석한다.

Step 4

"PROJECT_MASTER_PLAN.md"를 생성한다.

Step 5

이 문서의 내용을 모두 저장한다.

Step 6

"docs/PROJECT_STATUS.md"를 생성한다.

Step 7

"docs/decisions/ADR-0001-master-architecture.md"를 생성한다.

Step 8

개발 환경과 테스트 환경을 확인한다.

Step 9

현재 상태를 보고한다.

Step 10

아직 실제 주문 코드를 작성하지 않는다.

Step 11

아직 실제 AI API를 호출하지 않는다.

---

6. 시스템의 최상위 아키텍처

전체 시스템은 다음 계층을 기본 구조로 한다.

                    MARKET / EXTERNAL DATA
                              │
                              ▼
                    ┌───────────────────┐
                    │ Data Ingestion    │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ Data Quality       │
                    │ & Leakage Guard   │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ Feature / State   │
                    │ Engine            │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ Market Regime     │
                    │ Detection         │
                    └─────────┬─────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Prediction / Signal Engine     │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌────────────────────────────────┐
             │ Decision Agent                 │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌────────────────────────────────┐
             │ Position Sizing                │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌────────────────────────────────┐
             │ Portfolio Risk Engine          │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌────────────────────────────────┐
             │ Order Validator / Safety       │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌────────────────────────────────┐
             │ Broker Adapter                 │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌────────────────────────────────┐
             │ Toss Securities API            │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌────────────────────────────────┐
             │ Execution / Fill Processing    │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌────────────────────────────────┐
             │ Trade Journal                  │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌────────────────────────────────┐
             │ Post Trade Analysis            │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌────────────────────────────────┐
             │ Experience / Learning Engine   │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌────────────────────────────────┐
             │ Candidate Model Generation     │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌────────────────────────────────┐
             │ Validation / Evaluation        │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌────────────────────────────────┐
             │ Model Registry                 │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌────────────────────────────────┐
             │ Deployment                     │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌────────────────────────────────┐
             │ Monitoring / Drift Detection   │
             └───────────────┬────────────────┘
                             │
                             └─────── FEEDBACK ───────→

---

7. AI API Gateway

AI API는 특정 한 provider에 종속되지 않는다.

전체 애플리케이션에서 AI API를 직접 호출하지 않는다.

모든 AI 요청은 반드시 다음을 통과한다.

Application
    ↓
AI Gateway
    ↓
Task Router
    ↓
Quota Manager
    ↓
Provider Selector
    ↓
Provider Adapter
    ↓
AI Provider

---

8. 무료 AI API 사용 전략

목표는 여러 AI provider의 무료 사용 한도를 최대한 효율적으로 활용하는 것이다.

예:

Provider A
   ↓
무료 한도 소진
   ↓
Provider B
   ↓
무료 한도 소진
   ↓
Provider C
   ↓
무료 한도 소진
   ↓
Provider D
   ↓
...
   ↓
A quota reset
   ↓
Provider A

이 기능을 Provider Rotation / Failover라고 정의한다.

---

9. AI API Quota Manager

provider마다 다음 상태를 추적한다.

provider_id
provider_name
model
api_key_reference
rpm_limit
rpd_limit
tpm_limit
tpd_limit
monthly_limit
remaining_requests
remaining_tokens
reset_time
last_success
last_error
error_count
latency
health_status
enabled
priority

실제 provider가 제공하는 제한사항은 구현 시 해당 provider의 공식 문서를 확인한다.

---

10. 무료 한도 초과에 따른 과금 방지

사용자가 무료 API만 사용하려는 경우:

자동 유료 전환을 절대로 하지 않는다.

다음 상황에서는 provider를 비활성화한다.

Free quota exhausted
OR
Free quota uncertain
OR
Billing state unknown

그리고 다음 provider로 넘어간다.

무료 한도 상태를 정확히 알 수 없는 provider는 보수적으로 처리한다.

---

11. AI Provider Adapter

provider별 API 형식이 다르더라도 내부에서는 동일한 interface를 사용한다.

개념:

AIProvider
├── generate()
├── stream()
├── estimate_usage()
├── get_usage()
├── health_check()
└── get_limits()

실제 구현은 provider별 adapter로 분리한다.

---

12. AI Task Router

모든 작업에 같은 모델을 사용하지 않는다.

작업을 최소 다음으로 분류한다.

LOW

- 간단한 분류
- 로그 분석
- 데이터 정리
- 요약
- 단순 extraction

MEDIUM

- 거래 복기
- 시장 설명
- 전략 평가
- 연구 분석

HIGH

- 새로운 전략 생성
- 복잡한 연구 종합
- 모델 개선 제안
- 복잡한 reasoning

Task Router가 적합한 모델/provider를 선택한다.

---

13. AI 응답 신뢰성

AI API 응답은 항상 신뢰할 수 있다고 가정하지 않는다.

반드시:

- schema validation
- JSON validation
- missing field detection
- invalid value detection
- timeout
- retry
- rate limit handling
- provider failure handling

을 지원한다.

AI가 잘못된 주문 데이터를 반환해도 주문 시스템으로 바로 전달되지 않도록 한다.

---

14. AI와 금융 결정의 분리

LLM이 시스템 전체를 독점하지 않는다.

LLM은:

- 연구
- 논문 분석
- 뉴스/텍스트 분석
- 거래 복기
- 실패 원인 분석
- 전략 아이디어 생성
- 실험 결과 분석

등에 활용할 수 있다.

그러나:

- position limit
- risk limit
- order validation
- cash validation
- maximum drawdown protection
- kill switch

등의 안전장치는 deterministic system이 담당한다.

---

15. Data Layer

Data Layer는 시스템의 가장 중요한 기반 중 하나다.

데이터는 최소 다음 metadata를 가져야 한다.

symbol
timestamp
source
data_type
version
availability_time
ingestion_time
quality_status

---

16. Point-in-Time Principle

AI가 2020-01-01에 투자한다고 가정하면:

2020-01-01 이후에 공개된 정보를 절대로 볼 수 없다.

데이터의:

event_time
publication_time
available_time

을 가능한 경우 분리한다.

---

17. Survivorship Bias

현재 S&P500 구성종목만 과거로 되돌려서 백테스트하지 않는다.

가능한 경우 당시의 구성종목과 당시 이용 가능한 정보를 사용한다.

delisted company도 연구 데이터에 적절히 처리한다.

---

18. Corporate Action

가능한 경우:

- stock split
- dividend
- merger
- spin-off
- ticker change
- delisting

등을 고려한다.

단순히 현재 가격 데이터를 가져와 과거에 적용하는 구조를 피한다.

---

19. Feature Engine

Feature는 중앙 Feature Registry에서 관리한다.

각 feature에:

feature_id
name
definition
source
lookback
formula
availability
version
status

를 기록한다.

Feature가 미래 데이터를 사용하지 않는지 자동 검증할 수 있도록 설계한다.

---

20. Market Regime

Regime Detection은 독립된 모듈이다.

예:

Regime
├── Trend
├── Volatility
├── Liquidity
├── Correlation
└── Market Stress

최종 regime 모델은 실험을 통해 결정한다.

---

21. Prediction Layer

Prediction은 투자 결정과 분리한다.

예:

Prediction
├── expected_return
├── probability
├── expected_volatility
├── uncertainty
└── confidence

Prediction 결과만으로 바로 주문하지 않는다.

---

22. Decision Layer

Decision Agent는 prediction + regime + portfolio state + risk state를 이용한다.

가능한 행동:

BUY
SELL
HOLD
EXIT
NO_TRADE

필요하면:

target_weight
confidence
time_horizon

을 함께 반환한다.

---

23. NO_TRADE

NO_TRADE는 실패가 아니다.

다음 상황에서는 거래하지 않는 것이 정상적인 최적 행동일 수 있다.

- confidence가 낮음
- risk가 높음
- expected return이 transaction cost보다 낮음
- 시장 regime이 불확실
- liquidity 부족
- portfolio exposure가 이미 높음
- 데이터 이상
- 모델 이상

---

24. Position Sizing

Position Sizing은 별도의 deterministic/risk-aware layer로 둔다.

입력:

expected_return
risk
confidence
volatility
correlation
portfolio_exposure
liquidity
risk_budget

출력:

target_weight
target_quantity

AI가 임의로 위험한 포지션 크기를 설정하지 못하도록 한다.

---

25. Portfolio Risk

포트폴리오 수준에서:

single_position_limit
sector_limit
factor_limit
portfolio_volatility_limit
drawdown_limit
cash_minimum
turnover_limit
liquidity_limit

등을 관리할 수 있는 구조를 만든다.

구체적인 값은 이후 실험으로 결정한다.

---

26. Order System

주문은 다음 상태를 가진다.

PROPOSED
VALIDATING
REJECTED
SUBMITTED
PARTIALLY_FILLED
FILLED
CANCEL_REQUESTED
CANCELLED
FAILED
UNKNOWN

특히 "UNKNOWN" 상태를 반드시 고려한다.

Broker API와 연결이 끊긴 경우 주문이 실제로 체결됐는지 모를 수 있기 때문이다.

---

27. Idempotency

같은 주문 요청이 두 번 실행되어 중복 주문이 발생하지 않도록 한다.

모든 주문 요청에는 고유한 idempotency key를 사용한다.

---

28. Toss Securities Adapter

실제 증권 거래는 Toss Securities API를 사용한다.

그러나 core system은 Toss API에 직접 의존하지 않는다.

구조:

Core Trading System
        ↓
Broker Interface
        ↓
Toss Securities Adapter
        ↓
Toss Securities API

토스증권 API의 정확한 endpoint, authentication, request/response schema는 구현 시 공식 API 문서를 확인한다.

추측해서 endpoint를 만들지 않는다.

---

29. Paper Trading

실제 주문 이전에 동일한 주문 pipeline을 Paper Broker로 실행할 수 있어야 한다.

즉:

Trading Engine
       ↓
Broker Interface
       ↓
Paper Broker

또는:

Trading Engine
       ↓
Toss Broker

로 교체할 수 있어야 한다.

Core trading logic을 바꾸지 않는다.

---

30. Trade Journal

Trade Journal은 단순 DB 로그가 아니다.

시스템의 장기 기억이다.

각 거래에 대해 최소:

trade_id
decision_id
order_id
symbol
timestamp
side
quantity
price
position
market_state
features
prediction
confidence
decision
decision_reason
expected_return
expected_risk
risk_state
target_weight
execution_price
slippage
transaction_cost
realized_pnl
realized_return
holding_period
max_adverse_excursion
max_favorable_excursion
model_version
strategy_version
feature_version
data_version
risk_version
execution_version

등을 기록할 수 있어야 한다.

---

31. Decision Snapshot

거래 당시의 모든 중요한 상태를 snapshot으로 저장한다.

목적:

«몇 년 뒤에도 AI가 왜 해당 거래를 했는지 재현할 수 있어야 한다.»

---

32. Post Trade Analysis

거래 종료 후:

Expected
vs
Actual

을 비교한다.

분석:

prediction_error
timing_error
risk_estimation_error
execution_error
regime_error
signal_error

등을 저장한다.

---

33. Counterfactual Analysis

실제로 선택한 행동과 선택하지 않은 행동을 비교한다.

가능한 경우:

selected_action
alternative_action_1
alternative_action_2
hold
cash

의 결과를 기록한다.

---

34. Performance Attribution

실제 수익의 원인을 분석한다.

예:

market
sector
factor
selection
timing
execution

이를 통해 AI가 실제로 alpha를 만들어냈는지 분석한다.

---

35. Experience Dataset

Trade Journal을 학습용 데이터로 변환한다.

Experience에는:

state
action
expected_outcome
actual_outcome
reward
market_regime
risk_state
prediction_error
counterfactual_results

등을 포함할 수 있다.

---

36. Historical vs Live Experience

다음은 반드시 구분한다.

HISTORICAL_SIMULATION
PAPER_TRADING
LIVE_TRADING

Experience Dataset에는 provenance를 저장한다.

---

37. Learning Engine

Learning Engine은 다음을 수행할 수 있다.

Experience
 ↓
Data Cleaning
 ↓
Labeling
 ↓
Training Dataset
 ↓
Candidate Training
 ↓
Evaluation

그러나 학습 결과가 자동으로 Live에 적용되지 않는다.

---

38. Candidate Model

새로운 모델은 항상 "candidate" 상태로 시작한다.

CANDIDATE
   ↓
BACKTESTED
   ↓
VALIDATED
   ↓
OOS TESTED
   ↓
PAPER TESTED
   ↓
APPROVED
   ↓
DEPLOYED

---

39. Model Registry

모델마다:

model_id
version
training_dataset
feature_version
architecture
hyperparameters
training_period
validation_period
test_period
metrics
benchmark_metrics
risk_metrics
approval_status
created_at
approved_at

등을 관리한다.

---

40. Model Rollback

현재 Live Model과 이전 Stable Model을 항상 구분한다.

예:

ACTIVE
STABLE
CANDIDATE
RETIRED
FAILED

새 모델의 성능 이상 시 이전 Stable Model로 rollback할 수 있어야 한다.

---

41. Drift Detection

다음 drift를 감시한다.

Data Drift

입력 데이터 분포 변화.

Feature Drift

feature 분포 변화.

Prediction Drift

AI prediction 분포 변화.

Performance Drift

실제 성능 저하.

Regime Drift

시장 구조 변화.

---

42. Kill Switch

다음 상황에서는 신규 주문을 자동 중단할 수 있어야 한다.

critical data failure
broker failure
unexpected position
invalid model output
excessive drawdown
daily loss limit
abnormal order frequency
API failure
system integrity failure

Kill switch는 AI가 해제할 수 없도록 설계하는 것을 우선 고려한다.

---

43. Monitoring

시스템은 다음을 지속적으로 모니터링한다.

portfolio_value
cash
positions
exposure
PnL
drawdown
orders
fills
API status
data status
model status
feature drift
prediction drift
performance

---

44. Alerting

Critical event가 발생하면 기록하고 알림할 수 있는 구조를 만든다.

예:

CRITICAL
WARNING
INFO

등의 severity를 둔다.

초기에는 logging 중심으로 구현하고 이후 알림 provider를 추가할 수 있도록 한다.

---

45. Backtesting

백테스트는 실제 거래와 최대한 동일한 core logic을 사용한다.

이상적인 구조:

Backtest Broker
Paper Broker
Live Broker

가 동일한 Broker Interface를 구현한다.

---

46. Transaction Cost

백테스트에서 거래비용을 반드시 고려한다.

가능한 항목:

commission
spread
slippage
market impact

등.

실제 값은 데이터와 broker 조건을 바탕으로 설정한다.

---

47. Backtest Integrity

백테스트는 다음 조건을 만족해야 한다.

- 미래 데이터 없음
- 미래 가격 사용 없음
- 미래 구성종목 사용 없음
- 미래 corporate action 정보의 잘못된 사용 없음
- execution timing 왜곡 없음
- transaction cost 누락 없음

---

48. Validation Protocol

기본 검증 순서:

Training
    ↓
Validation
    ↓
Walk Forward
    ↓
Purged Validation
    ↓
Embargo
    ↓
Out of Sample
    ↓
Paper Trading

필요한 경우 여러 기간에 대해 반복한다.

---

49. Backtest Overfitting

전략을 많이 시도하면 최고 전략이 우연히 좋은 것일 수 있다.

따라서:

Experiment Count
+
OOS Result
+
PBO
+
Deflated Sharpe
+
Walk Forward

등을 기록한다.

---

50. Benchmark

최소 benchmark:

S&P 500 Buy & Hold

동일 기간, 동일한 초기 자본, 가능한 한 동일한 비용 가정을 사용하여 비교한다.

---

51. Baseline

복잡한 AI가 정말 가치가 있는지 확인하기 위해 baseline을 만든다.

최소:

S&P 500 Buy & Hold
Simple Momentum
Simple ML

등.

AI 시스템이 baseline을 지속적으로 능가하지 못한다면 복잡한 모델을 추가하는 대신 원인을 분석한다.

---

52. Experiment Tracking

모든 실험에 고유 ID를 부여한다.

예:

EXP-000001
EXP-000002
...

저장:

experiment_id
timestamp
code_version
data_version
feature_version
model_version
parameters
dataset
metrics
benchmark
result
notes

---

53. Reproducibility

가능한 경우 동일한:

data
code
config
seed
model
parameters

로 실험을 재현할 수 있어야 한다.

---

54. Configuration

코드에 실험값을 하드코딩하지 않는다.

예:

configs/
├── development/
├── backtest/
├── paper/
└── live/

등의 구조를 고려한다.

---

55. Secrets

API key를 절대로 코드에 저장하지 않는다.

금지:

API_KEY = "xxxxx"

대신 환경변수 또는 안전한 secret management를 사용한다.

".env"는 Git에 커밋하지 않는다.

".env.example"에는 필요한 변수 이름만 기록한다.

---

56. Logging

모든 중요한 이벤트를 기록한다.

특히:

AI decision
order proposal
risk rejection
order submission
order fill
trade completion
model change
provider switch
quota exhaustion
kill switch
rollback

은 audit log로 남긴다.

---

57. Auditability

나중에 다음 질문에 답할 수 있어야 한다.

«왜 이 거래가 발생했는가?»

«당시 AI가 무엇을 알고 있었는가?»

«어떤 모델이 결정했는가?»

«어떤 risk rule을 통과했는가?»

«어떤 가격으로 주문했는가?»

«왜 모델이 변경되었는가?»

«누가/무엇이 모델 변경을 승인했는가?»

---

58. Security

최소:

- API key 보호
- 최소 권한
- broker credential 분리
- AI provider credential 분리
- secret rotation 고려
- audit logging
- dangerous operation confirmation
- production configuration 분리

---

59. Live Trading 안전 원칙

Live mode는 명시적으로 활성화되어야 한다.

기본값은:

LIVE_TRADING = false

여야 한다.

개발/테스트 환경에서 실계좌 주문이 발생하면 안 된다.

---

60. Environment 분리

최소:

development
backtest
paper
live

환경을 분리한다.

환경 간 API key와 configuration을 혼용하지 않는다.

---

61. 단계적 개발

다음 Phase 순서를 기본으로 한다.

Phase 0
Foundation

Phase 1
Data Infrastructure

Phase 2
Backtesting

Phase 3
Trade Journal

Phase 4
Baseline Models

Phase 5
Market Regime

Phase 6
Prediction

Phase 7
Decision Agent

Phase 8
Position / Risk

Phase 9
Learning

Phase 10
Counterfactual / Attribution

Phase 11
Model Evolution

Phase 12
AI Gateway

Phase 13
Toss Securities Adapter

Phase 14
Monitoring / Drift / Safety

Phase 15
Paper Trading

Phase 16
Live Trading

---

62. Phase 진행 규칙

각 Phase마다 반드시:

Specification
 ↓
Implementation
 ↓
Unit Tests
 ↓
Integration Tests
 ↓
Validation
 ↓
Documentation
 ↓
Status Update

를 수행한다.

Phase가 완료되기 전에 다음 Phase로 넘어가지 않는다.

---

63. Definition of Done

기능이 코드로 작성됐다는 이유만으로 완료로 판단하지 않는다.

기능마다 최소:

- 구현
- 테스트
- 에러 처리
- logging
- documentation
- configuration
- validation

이 되어야 한다.

---

64. 테스트 전략

최소:

Unit Test
Integration Test
Backtest Test
Data Leakage Test
Risk Test
Order Validation Test
Broker Adapter Test
AI Gateway Test
Quota Rotation Test
Failure Recovery Test

등을 단계적으로 구축한다.

---

65. 금융 로직 테스트

다음은 높은 우선순위로 테스트한다.

- portfolio calculation
- position sizing
- PnL
- transaction cost
- slippage
- drawdown
- benchmark calculation
- order quantity
- exposure
- risk limits

---

66. AI Gateway 테스트

반드시 테스트한다.

Provider A 정상

A → 성공

Provider A quota exhausted

A → B

A/B/C 모두 실패

NO AI CALL / safe failure

A quota reset

B → A

유료 상태

Provider disabled

---

67. Broker 테스트

실제 돈을 사용하지 않는 mock/paper 환경에서:

- buy
- sell
- cancel
- partial fill
- failed order
- timeout
- unknown order state
- duplicate request

등을 테스트한다.

---

68. AI 자율성의 범위

자율성은 다음처럼 단계적으로 증가시킨다.

Level 0
Research Assistant

Level 1
Backtest Agent

Level 2
Paper Trading Agent

Level 3
Restricted Live Agent

Level 4
Autonomous Trading Agent

처음부터 Level 4를 구현하지 않는다.

---

69. AI의 자기 개선

AI가 다음을 제안할 수 있다.

- 새로운 feature
- 새로운 모델
- 새로운 reward
- 새로운 strategy
- 새로운 risk parameter
- 새로운 regime model

하지만 제안과 적용을 분리한다.

AI Proposal
    ↓
Experiment
    ↓
Validation
    ↓
Approval
    ↓
Deployment

---

70. AI가 변경할 수 없는 것

다음 안전장치는 AI가 임의로 변경하지 못하도록 한다.

- hard risk limit
- kill switch
- live trading activation
- broker credentials
- free API billing policy
- audit logging
- validation requirement

---

71. 연구 기반

프로젝트의 초기 연구 기반은 다음과 같다.

S급

Empirical Asset Pricing via Machine Learning

Gu, Kelly & Xiu

활용:

- machine learning
- nonlinear prediction
- feature interaction
- momentum
- liquidity
- volatility

Time Series Momentum

Moskowitz, Ooi & Pedersen

활용:

- momentum
- trend
- market state

The Probability of Backtest Overfitting

Bailey et al.

활용:

- backtest overfitting
- multiple testing
- strategy selection

The Deflated Sharpe Ratio

Bailey & López de Prado

활용:

- multiple testing
- selection bias
- Sharpe adjustment

Optimal Execution of Portfolio Transactions

Almgren & Chriss

활용:

- execution
- transaction cost
- market impact

Financial Machine Learning Validation Methods

López de Prado 계열 연구

활용:

- Purged K-Fold
- Embargo
- time-series validation

FinRL

활용:

- DRL architecture
- trading environment
- portfolio management
- backtesting

---

72. 논문 등급 시스템

추가 연구가 필요한 경우:

S

프로젝트 핵심 설계에 직접 반영할 가치가 있는 연구.

A

특정 기능/알고리즘에 중요한 연구.

B

아이디어 참고.

C 이하

구현 근거로 사용하지 않는 것을 원칙으로 한다.

최신 논문이라는 이유만으로 S급으로 분류하지 않는다.

---

73. 추가 연구 규칙

프로젝트 구현 중 새로운 논문이 필요해졌을 경우 무작정 논문을 추가하지 않는다.

먼저:

What design decision requires evidence?

를 정의한다.

그 결정에 필요한 최소한의 연구만 수행한다.

컨텍스트와 프로젝트 복잡도를 불필요하게 증가시키지 않는다.

---

74. S&P 500 초과수익 판단

다음 조건을 모두 고려한다.

Return
Risk
Drawdown
Consistency
Transaction Cost
Turnover
Out-of-Sample
Walk Forward
Benchmark

단 한 번의 높은 수익률로 성공 판정을 내리지 않는다.

---

75. 과최적화 금지

다음 행동을 경계한다.

Parameter tuning
→ backtest
→ best result selection
→ repeat

이 과정을 무제한 반복하지 않는다.

모든 실험 횟수를 기록하고 selection bias를 고려한다.

---

76. Data / Model / Strategy Lineage

모든 결과는 다음 관계를 추적할 수 있어야 한다.

Data Version
     ↓
Feature Version
     ↓
Training Dataset
     ↓
Model Version
     ↓
Strategy Version
     ↓
Risk Version
     ↓
Execution Version
     ↓
Trade

---

77. 시스템의 장기 기억

시스템의 장기 기억은 다음으로 구성한다.

Trade Journal
Experiment Registry
Model Registry
Feature Registry
Decision Snapshots
Post Trade Analysis
Architecture Decisions
Research Notes
Performance History

Claude Code의 대화 기억에 의존하지 않는다.

---

78. PROJECT_STATUS.md

항상 다음 정보를 유지한다.

Current Phase
Current Subtask
Completed
In Progress
Blocked
Next Task
Known Issues
Architecture Changes
Recent Experiments
Current Model
Current Benchmark
Last Validation

새 세션에서 이 파일 하나만 읽어도 현재 상태를 파악할 수 있도록 유지한다.

---

79. ADR

중요한 설계 변경은 반드시 ADR을 만든다.

예:

ADR-0001-master-architecture.md
ADR-0002-data-model.md
ADR-0003-backtest-validation.md
ADR-0004-ai-provider-gateway.md
ADR-0005-broker-adapter.md

---

80. 변경관리

누군가 새로운 기능을 제안했을 때:

Requirement
 ↓
Impact Analysis
 ↓
Architecture Decision
 ↓
ADR
 ↓
Master Plan Update
 ↓
Implementation

순서로 진행한다.

---

81. Claude Code의 역할

Claude Code는:

- 코드를 작성한다.
- 테스트를 작성한다.
- 시스템을 구현한다.
- 문서를 유지한다.
- 문제를 분석한다.
- 구현상의 대안을 제시한다.

하지만:

«프로젝트의 핵심 목적이나 안전 원칙을 임의로 변경하지 않는다.»

---

82. 개발자가 판단해야 할 문제가 생긴 경우

다음과 같이 보고한다.

DECISION REQUIRED

Problem:
...

Current Design:
...

Option A:
...

Option B:
...

Recommendation:
...

Impact:
...

임의로 중요한 아키텍처를 바꾸지 않는다.

---

83. 구현 우선순위

기능 우선순위는 다음이다.

P0 — 반드시 필요

- Data integrity
- Backtest
- Benchmark
- Trade Journal
- Risk
- Validation
- Model versioning
- AI Gateway
- Broker abstraction
- Safety

P1 — 핵심

- Regime
- Prediction
- Decision Agent
- Learning
- Counterfactual
- Attribution
- Drift

P2 — 확장

- additional data
- advanced NLP
- additional AI providers
- advanced optimization
- additional brokers

---

84. 개발 철학

복잡성을 위해 복잡한 시스템을 만들지 않는다.

항상 질문한다.

«이 기능이 실제로 S&P 500 초과수익을 검증하는 데 도움이 되는가?»

«이 기능이 위험을 줄이는가?»

«이 기능이 학습 능력을 개선하는가?»

«이 기능이 시스템의 재현성을 높이는가?»

그렇지 않다면 우선순위를 낮춘다.

---

85. 최소 기능으로 시작

초기 시스템은 모든 것을 한 번에 구현하지 않는다.

최초의 완전한 연구 가능한 시스템은 다음 정도면 된다.

Market Data
 ↓
Data Validation
 ↓
Simple Features
 ↓
Baseline Strategy
 ↓
Backtest
 ↓
S&P500 Benchmark
 ↓
Trade Journal
 ↓
Metrics

이것이 안정화된 후 AI를 단계적으로 추가한다.

---

86. Baseline 우선 원칙

복잡한 AI를 만들기 전에 반드시 baseline을 만든다.

이유:

«복잡한 AI가 단순 전략보다 실제로 가치가 있는지 증명해야 하기 때문이다.»

---

87. Live 이전 조건

Live Trading은 다음을 모두 통과해야 한다.

Data validation PASS
Backtest PASS
OOS PASS
Risk tests PASS
Leakage tests PASS
Paper trading PASS
Broker tests PASS
Kill switch PASS
Rollback PASS
Monitoring PASS

하나라도 중요한 조건을 만족하지 못하면 Live로 가지 않는다.

---

88. 실전 자금 제한

초기 Live 단계에서는 전체 자본을 바로 투입하지 않는다.

구체적인 자본 비율은 향후 결정한다.

원칙:

Paper
 ↓
Small Capital
 ↓
Controlled Expansion

---

89. 장애 발생 시 원칙

시스템이 불확실한 상태가 되면:

«거래하지 않는 방향이 기본값»

이어야 한다.

예:

Data Unknown
Broker Unknown
Position Unknown
Model Unknown

이면 신규 주문을 차단한다.

---

90. Fail Closed

안전 관련 기능은 가능한 경우 fail-open이 아니라 fail-closed를 기본으로 한다.

예:

Risk Engine unavailable
→ Do not trade

Order Validator unavailable
→ Do not trade

Broker state unknown
→ Do not create new order

---

91. 최종 시스템의 핵심 루프

이 프로젝트의 가장 중요한 loop는 다음이다.

OBSERVE
   ↓
UNDERSTAND
   ↓
PREDICT
   ↓
DECIDE
   ↓
RISK CHECK
   ↓
EXECUTE
   ↓
RECORD
   ↓
EVALUATE
   ↓
LEARN
   ↓
VALIDATE
   ↓
IMPROVE
   ↓
OBSERVE AGAIN

이 loop가 프로젝트의 핵심이다.

---

92. 가장 중요한 개념

Trade Journal은 로그가 아니다.

경험 메모리다.

Model Registry는 파일 저장소가 아니다.

모델 진화 기록이다.

Experiment Tracking은 단순 결과 저장소가 아니다.

연구 기억이다.

Validation은 단순 테스트가 아니다.

실전 투입 자격 심사다.

AI Gateway는 API wrapper가 아니다.

AI 자원 관리 계층이다.

Risk Engine은 보조 기능이 아니다.

AI의 행동을 제한하는 안전 경계다.

---

93. 첫 번째 세션에서 생성해야 할 문서

최소:

PROJECT_MASTER_PLAN.md
README.md
docs/PROJECT_STATUS.md
docs/decisions/ADR-0001-master-architecture.md

그리고 필요에 따라:

docs/specifications/
docs/architecture/
docs/research/

에 추가 문서를 생성한다.

---

94. PROJECT_MASTER_PLAN.md 저장 시 주의사항

이 문서의 핵심 요구사항을 요약해서 저장하지 말고 충분히 상세하게 저장한다.

특히 반드시 포함:

- 목표
- 철학
- 전체 아키텍처
- 모듈
- 데이터 흐름
- Trade Journal
- Learning Loop
- Validation
- Benchmark
- AI Gateway
- Provider Rotation
- Free Quota Protection
- Toss Securities
- Broker Adapter
- Risk
- Kill Switch
- Rollback
- Drift
- Versioning
- Experiment Tracking
- Phase 순서
- 개발 금지사항
- 변경관리
- 연구 기반

---

95. 첫 번째 세션의 최종 출력

작업을 완료한 뒤 다음을 보고한다.

PROJECT INITIALIZATION COMPLETE

Project:
Autonomous AI Investment System

Master Plan:
PROJECT_MASTER_PLAN.md

Status:
docs/PROJECT_STATUS.md

Architecture Decision:
docs/decisions/ADR-0001-master-architecture.md

Repository:
[현재 repository 상태]

Existing Code:
[기존 코드가 있는 경우 설명]

Conflicts:
[계획과 기존 코드의 충돌]

Current Phase:
Phase 0 — Foundation

Completed:
- Project inspection
- Master plan persistence
- Documentation foundation
- Architecture record

Not Yet Implemented:
- Trading
- Broker API
- AI API
- Live execution

Next Recommended Task:
Phase 0 foundation implementation

---

96. 최종적으로 기억해야 할 한 문장

이 프로젝트는:

«"AI에게 주식 매매를 시키는 프로그램"이 아니라, "AI가 시장을 관찰하고 판단하고 거래하고 그 결과를 기억하며 자신의 의사결정을 검증하고 개선하는 폐쇄형 투자 연구·학습·실행 시스템"을 만드는 프로젝트다.»

그리고 최종 목표는:

«검증 가능한 방식으로 S&P 500을 장기적으로 초과하는 것이다.»

모든 설계와 구현은 이 목표에 기여해야 한다.

---

97. 지금 즉시 실행하라

다시 강조한다.

첫 번째 세션에서는 실제 투자 기능을 만들지 마라.

먼저:

1. Repository 조사
2. "PROJECT_MASTER_PLAN.md" 생성
3. 이 전체 계획 저장
4. "docs/PROJECT_STATUS.md" 생성
5. "docs/decisions/ADR-0001-master-architecture.md" 생성
6. 기존 코드 분석
7. 계획과 기존 코드의 충돌 확인
8. Phase 0 상태 기록
9. 결과 보고

까지만 수행한다.

그 다음 세션부터 Phase별 개발을 진행한다.

---

98. 절대적인 우선순위

어떤 기능을 구현하다가도 다음 우선순위를 잊지 마라.

1. Capital Safety
2. Data Integrity
3. Reproducibility
4. Validation
5. Risk Control
6. Accurate Trade Recording
7. Learning
8. Performance
9. Complexity

높은 수익률을 위해 앞의 안전장치를 희생하지 않는다.

---

END OF MASTER INITIALIZATION INSTRUCTION
