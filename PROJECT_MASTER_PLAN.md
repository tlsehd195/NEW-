# PROJECT MASTER PLAN

## Autonomous AI Investment System

**Version:** 1.0
**Status:** ACTIVE — Source of Truth
**Last Updated:** 2026-09-11 (dangling §references corrected across the
document, ADR-0115; the constitution/architecture content itself is
unchanged since Phase 0 — for the project's actual current progress,
which has moved far past Phase 0, see `docs/PROJECT_STATUS.md`'s own
"Current Phase" section and session log, never this stamp)

---

> ## 이 문서를 읽는 모든 Claude Code 세션에게
>
> 이 문서는 이 프로젝트의 **최상위 설계 문서(Source of Truth)**다.
> 너의 대화 컨텍스트는 영구 저장소가 아니다. 이 프로젝트는
> **"AI가 기억하는 프로젝트"가 아니라 "파일이 기억하는 프로젝트"**다.
>
> 새 세션을 시작했다면 반드시 다음 순서로 읽어라:
> 1. 이 파일 (`PROJECT_MASTER_PLAN.md`) 전체
> 2. `docs/PROJECT_STATUS.md` — 현재 어디까지 왔는지
> 3. `docs/decisions/` 전체 — 왜 그렇게 결정했는지
> 4. 현재 작업 중인 Phase의 `docs/specifications/` 문서
>
> 이 문서와 실제 코드가 충돌하면 **코드가 자동으로 옳다고 가정하지 않는다.**
> 차이를 기록하고 원인을 분석한 뒤 ADR로 남긴다.

---

## 0. 한 문장 정의

이 프로젝트는:

> **"AI에게 주식 매매를 시키는 프로그램"이 아니라, "AI가 시장을 관찰하고
> 판단하고 거래하고 그 결과를 기억하며 자신의 의사결정을 검증하고
> 개선하는 폐쇄형 투자 연구·학습·실행 시스템"을 만드는 프로젝트다.**

최종 목표:

> **검증 가능한 방식으로 S&P 500의 장기 수익률을 초과하는 것을 목표로 하는
> 자율형 AI 투자 시스템을 구축하는 것.** (초과수익을 보장한다고 가정하지 않는다.)

성공 기준은 백테스트 수익률 하나가 아니라 다음을 **동시에** 만족하는 것이다:

- 수익성 (Profitability)
- 위험 통제 (Risk Control)
- 과적합 방지 (Overfitting Prevention)
- 데이터 누수 방지 (Leakage Prevention)
- 재현성 (Reproducibility)
- 실전 거래 가능성 (Executability)
- 거래비용 반영 (Transaction Cost Realism)
- 지속적인 학습 (Continual Learning)
- 모델 변경 추적 (Lineage / Versioning)
- 장애 대응 (Fault Tolerance)
- 안전한 자동화 (Safe Automation)

---

## 1. 프로젝트 헌법 (Constitution)

이 섹션은 프로젝트의 **바뀌지 않는 최상위 규칙**이다. 이 헌법과 충돌하는
어떤 코드/제안/실험도 헌법이 우선한다. 헌법을 바꾸려면 §19(변경관리
프로세스)을 반드시 거쳐야 하며, 사용자의 명시적 승인 없이 Claude Code가
임의로 개정할 수 없다.

### 1.1 절대 금지 사항 (Never Do)

- 바로 자동매매부터 구현하지 않는다.
- 바로 실계좌 주문 기능부터 구현하지 않는다.
- 임의의 AI 모델 하나를 선택해서 전체 시스템을 만들지 않는다.
- 백테스트 성능이 높다는 이유만으로 모델을 채택하지 않는다.
- 데이터를 쉽게 구할 수 있다는 이유로 미래 정보가 섞인 데이터를 사용하지 않는다.
- Trade Journal을 "나중에 추가할 기능"으로 취급하지 않는다.
- 학습 시스템을 "나중에 추가할 기능"으로 취급하지 않는다.
- AI가 직접 증권사 API를 호출하도록 만들지 않는다.
- AI가 검증 없이 Live 모델을 교체하도록 만들지 않는다.
- 무료 API 한도를 초과하여 자동으로 유료 과금되는 구조를 만들지 않는다.
- 프로젝트 계획을 임의로 단순화하지 않는다.
- 안전장치를 우회하기 위해 테스트를 건너뛰거나(skip), 비활성화하거나,
  격리하지 않는다.
- 실계좌 주문, kill switch, risk limit, broker credential, 무료 과금 정책을
  AI(LLM)나 자동화 로직이 스스로 변경하게 하지 않는다.

### 1.2 절대 우선순위 (Absolute Priority Order)

기능을 구현하다가도 아래 우선순위를 절대 잊지 않는다. 상위 항목을
하위 항목을 위해 희생하지 않는다.

1. Capital Safety (자본 안전)
2. Data Integrity (데이터 무결성)
3. Reproducibility (재현성)
4. Validation (검증)
5. Risk Control (위험 통제)
6. Accurate Trade Recording (정확한 거래 기록)
7. Learning (학습)
8. Performance (성능/수익률)
9. Complexity (복잡성 — 최하위, 필요할 때만 추가)

### 1.3 핵심 철학 질문

새 기능을 추가하기 전 항상 스스로 질문한다:

- 이 기능이 실제로 S&P 500 초과수익을 **검증**하는 데 도움이 되는가?
- 이 기능이 위험을 줄이는가?
- 이 기능이 학습 능력을 개선하는가?
- 이 기능이 시스템의 재현성을 높이는가?

그렇지 않다면 우선순위를 낮춘다. **복잡성을 위해 복잡한 시스템을 만들지 않는다.**

### 1.4 Fail-Closed 원칙

시스템이 불확실한 상태가 되면 **"거래하지 않는 것"이 기본값**이다.

| 상태 | 조치 |
|---|---|
| Data Unknown | 신규 주문 차단 |
| Broker Unknown | 신규 주문 차단 |
| Position Unknown | 신규 주문 차단 |
| Model Unknown | 신규 주문 차단 |
| Risk Engine unavailable | 거래하지 않음 |
| Order Validator unavailable | 거래하지 않음 |
| Broker state unknown | 신규 주문 생성하지 않음 |

안전 관련 기능은 fail-open이 아니라 **fail-closed**를 기본으로 한다.

### 1.5 AI가 절대 변경할 수 없는 것

다음은 deterministic system이 담당하며, LLM/AI가 임의로 변경할 수 없다:

- hard risk limit
- kill switch
- live trading activation (`LIVE_TRADING` 플래그)
- broker credentials
- free API billing policy (무료 한도 정책)
- audit logging
- validation requirement (검증 절차 자체를 생략하는 것)

### 1.6 AI와 금융 결정의 분리

LLM은 시스템 전체를 독점하지 않는다.

LLM이 담당할 수 있는 영역:
- 연구, 논문 분석
- 뉴스/텍스트 분석
- 거래 복기(post-trade review)
- 실패 원인 분석
- 전략 아이디어 생성
- 실험 결과 분석

**Deterministic system**이 반드시 담당하는 영역 (LLM이 대신할 수 없음):
- position limit
- risk limit
- order validation
- cash validation
- maximum drawdown protection
- kill switch

---

## 2. 시스템 최상위 아키텍처

전체 시스템은 다음 계층 구조를 기본으로 한다. 각 계층은 단방향 데이터
흐름을 가지며, 마지막 Monitoring/Drift 단계에서 다시 학습 루프로
피드백된다.

```
                    MARKET / EXTERNAL DATA
                              │
                              ▼
                    ┌───────────────────┐
                    │ Data Ingestion    │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ Data Quality      │
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
             │ Prediction / Signal Engine      │
             └───────────────┬────────────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Decision Agent                  │
             └───────────────┬────────────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Position Sizing                 │
             └───────────────┬────────────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Portfolio Risk Engine           │
             └───────────────┬────────────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Order Validator / Safety        │
             └───────────────┬────────────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Broker Adapter                  │
             └───────────────┬────────────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Toss Securities API             │
             └───────────────┬────────────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Execution / Fill Processing     │
             └───────────────┬────────────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Trade Journal                   │
             └───────────────┬────────────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Post Trade Analysis             │
             └───────────────┬────────────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Experience / Learning Engine    │
             └───────────────┬────────────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Candidate Model Generation      │
             └───────────────┬────────────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Validation / Evaluation         │
             └───────────────┬────────────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Model Registry                  │
             └───────────────┬────────────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Deployment                      │
             └───────────────┬────────────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │ Monitoring / Drift Detection    │
             └───────────────┬────────────────┘
                              │
                              └─────── FEEDBACK ───────→ (Feature/Regime/Prediction/Decision 단계로)
```

### 2.1 핵심 루프 (가장 중요한 개념)

```
OBSERVE → UNDERSTAND → PREDICT → DECIDE → RISK CHECK → EXECUTE
   → RECORD → EVALUATE → LEARN → VALIDATE → IMPROVE → OBSERVE AGAIN
```

이 loop가 프로젝트의 핵심이다. 어떤 기능을 만들든 이 루프의 어느
단계를 강화하는지 명확히 알아야 한다.

---

## 3. 모듈 책임과 경계 (Module Responsibilities & Boundaries)

각 모듈은 **단일 책임**을 가지며, 다른 모듈의 책임을 침범하지 않는다.
모듈 간 통신은 명확히 정의된 인터페이스/데이터 계약을 통해서만 이루어진다.

| 모듈 | 책임 | 하지 않는 것 (경계) |
|---|---|---|
| **Data Ingestion** | 외부 데이터 수집, 원본 저장, 메타데이터 부착 | 데이터 해석/가공, 매매 판단 |
| **Data Quality & Leakage Guard** | 데이터 검증, point-in-time 무결성 검사 | 데이터 수집, feature 계산 |
| **Feature/State Engine** | Feature 계산, Feature Registry 관리 | 예측, 매매 판단 |
| **Market Regime Detection** | 시장 상태(추세/변동성/유동성 등) 분류 | 종목 선택, 매매 판단 |
| **Prediction/Signal Engine** | 기대수익률/확률/불확실성 산출 | 매매 여부 결정, 포지션 크기 결정 |
| **Decision Agent** | BUY/SELL/HOLD/EXIT/NO_TRADE 결정 | 포지션 크기 계산, risk limit 적용, 주문 전송 |
| **Position Sizing** | target_weight/target_quantity 계산 (risk-aware) | 매매 여부 결정, 주문 검증 |
| **Portfolio Risk Engine** | 포트폴리오 수준 리스크 한도 관리 | 개별 종목 예측, 주문 전송 |
| **Order Validator/Safety** | 주문 최종 검증, kill switch 체크 | 리스크 한도 설계, 예측 |
| **Broker Adapter** | 표준 인터페이스 ↔ 특정 broker API 변환 | 매매 판단, 리스크 계산 |
| **Toss Securities Adapter** | Broker Adapter의 구체 구현체 | core trading logic |
| **Execution/Fill Processing** | 체결 결과 수신·정규화 | 매매 판단 |
| **Trade Journal** | 모든 의사결정/거래의 영구 기록 | 판단, 분석 (기록만 담당) |
| **Post Trade Analysis** | Expected vs Actual 비교 분석 | 기록, 매매 판단 |
| **Experience/Learning Engine** | Trade Journal → 학습 데이터셋 변환, 후보 모델 학습 | 배포 결정 |
| **Validation/Evaluation** | 후보 모델의 실전 투입 자격 심사 | 학습, 배포 실행 |
| **Model Registry** | 모델 버전/메타데이터/승인 상태 관리 | 검증 로직 자체 |
| **Deployment** | 승인된 모델을 Live로 전환 | 검증 기준 결정 |
| **Monitoring/Drift Detection** | 지속적 관찰, 이상 감지, 피드백 트리거 | 모델 재학습 자체 실행 |
| **AI Gateway** | 모든 LLM 호출의 단일 진입점, quota/provider 관리 | 금융 의사결정 자체 |
| **Kill Switch** | 위기 상황 시 신규 주문 전면 차단 | 정상 운영 로직 |

**경계 원칙:** 어떤 모듈도 자신의 책임이 아닌 계층의 역할을 대신 수행하지
않는다. 예: Decision Agent는 절대 직접 주문을 전송하지 않고, Position
Sizing과 Risk Engine과 Order Validator를 반드시 거친다.

---

## 4. 데이터 흐름: 데이터 → 의사결정 → 주문 → 학습

시스템 전체의 데이터 흐름을 4단계 파이프라인으로 명확히 정의한다.

### 4.1 단계 A — 데이터 → Feature/Regime/Prediction

```
Raw Market/External Data
   → [ingestion_time, source, version 메타데이터 부착]
   → Data Quality & Leakage Guard
       (point-in-time 검증: availability_time <= 현재 판단 시점)
   → Feature Engine
       (Feature Registry에 등록된 정의로만 계산, lookback 명시)
   → Market Regime Detection
   → Prediction/Signal Engine
       (expected_return, probability, expected_volatility, uncertainty, confidence)
```

**불변식:** 이 단계에서 만들어지는 어떤 output도 `availability_time`
이후 시점에 존재하지 않았던 정보를 참조해서는 안 된다. (§7.2 Point-in-Time
Principle)

### 4.2 단계 B — 의사결정 → 포지션 → 리스크 → 주문

```
Prediction (expected_return, confidence, ...)
   + Market Regime
   + Portfolio State (현재 포지션, 현금, exposure)
   + Risk State
   → Decision Agent
       → action ∈ {BUY, SELL, HOLD, EXIT, NO_TRADE}
       → (target_weight, confidence, time_horizon) [optional]
   → Position Sizing (deterministic, risk-aware)
       → target_weight, target_quantity
   → Portfolio Risk Engine
       (single_position_limit, sector_limit, drawdown_limit, ...)
   → Order Validator / Safety
       (kill switch 상태 확인, cash validation, idempotency key 부착)
   → Broker Adapter (Paper 또는 Toss)
   → 주문 전송
```

**불변식:** Decision Agent의 출력만으로는 절대 주문이 발생하지 않는다.
Position Sizing → Risk Engine → Order Validator를 전부 통과해야 한다.
AI(LLM)는 이 파이프라인의 어느 단계도 우회할 수 없다.

### 4.3 단계 C — 체결 → 기록

```
Broker Adapter (fill event)
   → Execution/Fill Processing
       (execution_price, slippage, transaction_cost 계산)
   → Trade Journal
       (Decision Snapshot 전체를 함께 저장: 그 순간의 features, prediction,
        regime, risk_state, model_version 등 — §10.3)
   → Post Trade Analysis
       (Expected vs Actual, prediction_error, timing_error, ...)
```

### 4.4 단계 D — 기록 → 학습 → 검증 → 배포

```
Trade Journal (+ Post Trade Analysis + Counterfactual Analysis)
   → Experience Dataset
       (state, action, expected_outcome, actual_outcome, reward,
        provenance: HISTORICAL_SIMULATION | PAPER_TRADING | LIVE_TRADING)
   → Learning Engine
       Data Cleaning → Labeling → Training Dataset → Candidate Training → Evaluation
   → Candidate Model (상태: CANDIDATE → BACKTESTED → VALIDATED → OOS TESTED
       → PAPER TESTED → APPROVED → DEPLOYED)
   → Validation/Evaluation (§13.4 Validation Protocol 전체 통과 필요)
   → Model Registry (버전 등록, lineage 기록)
   → Deployment (사람 승인 이후에만 ACTIVE로 전환 — §11.2, §11.5)
   → Monitoring/Drift Detection
   → (문제 발견 시) Rollback to STABLE, 또는 새로운 Experience로 피드백
```

**불변식:** 학습 결과(새 모델)는 **자동으로 Live에 적용되지 않는다.**
CANDIDATE는 반드시 전체 검증 단계를 통과하고 승인(§11.2, §11.5)받아야
DEPLOYED 상태가 될 수 있다.

### 4.5 Lineage 추적

모든 결과는 다음 관계를 추적할 수 있어야 한다 (§11.3):

```
Data Version → Feature Version → Training Dataset → Model Version
   → Strategy Version → Risk Version → Execution Version → Trade
```

---

## 5. AI API Gateway

전체 애플리케이션에서 AI API를 직접 호출하지 않는다. AI API는 특정 provider에
종속되지 않는다. 모든 AI 요청은 다음 계층을 통과한다:

```
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
```

### 5.1 AI Provider Adapter 인터페이스

provider별 API 형식이 다르더라도 내부에서는 동일한 interface를 사용한다.

```
AIProvider
├── generate()
├── stream()
├── estimate_usage()
├── get_usage()
├── health_check()
└── get_limits()
```

실제 provider별 구현은 개별 adapter로 분리한다.

### 5.2 AI Task Router — 작업 분류

모든 작업에 같은 모델을 사용하지 않는다. 최소 3단계로 분류한다:

- **LOW**: 간단한 분류, 로그 분석, 데이터 정리, 요약, 단순 extraction
- **MEDIUM**: 거래 복기, 시장 설명, 전략 평가, 연구 분석
- **HIGH**: 새로운 전략 생성, 복잡한 연구 종합, 모델 개선 제안, 복잡한 reasoning

Task Router가 작업 등급에 맞는 provider/model을 선택한다.

### 5.3 AI 응답 신뢰성

AI API 응답은 항상 신뢰할 수 있다고 가정하지 않는다. 반드시 지원:

- schema validation
- JSON validation
- missing field detection
- invalid value detection
- timeout
- retry
- rate limit handling
- provider failure handling

AI가 잘못된 형식/값의 데이터를 반환해도 **주문 시스템으로 직접 전달되지
않는다.** (§13, §14와 연결 — AI 출력은 항상 deterministic validation을 거친다.)

---

## 6. AI API 무료 한도 로테이션 — 상세 요구사항

### 6.1 목표

여러 AI provider의 **무료 사용 한도**를 최대한 효율적으로 활용하며,
**어떤 상황에서도 사용자 동의 없이 자동으로 유료 과금이 발생하지 않는다.**

### 6.2 Provider Rotation / Failover 동작

```
Provider A (무료 한도 사용)
   → 한도 소진 → Provider B
   → 한도 소진 → Provider C
   → 한도 소진 → Provider D
   → ... 모든 provider 소진 시 → "NO AI CALL / safe failure" (요청 자체를 안전하게 실패 처리, 절대 유료로 전환하지 않음)
   → (시간 경과 후) Provider A quota reset → 다시 Provider A부터 로테이션 재개
```

### 6.3 Quota Manager가 provider별로 추적해야 하는 상태

```
provider_id
provider_name
model
api_key_reference     # 실제 키 값이 아니라 참조(secret manager 등)
rpm_limit              # requests per minute
rpd_limit              # requests per day
tpm_limit              # tokens per minute
tpd_limit              # tokens per day
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
```

각 provider가 실제로 제공하는 제한사항(정확한 rpm/rpd/tpm 값 등)은
**구현 시점에 해당 provider의 공식 문서를 확인**하여 설정한다. 추측하지 않는다.

### 6.4 무료 한도 초과에 따른 과금 방지 규칙

사용자가 무료 API만 사용하려는 경우, **자동 유료 전환을 절대로 하지
않는다.** 다음 상황에서는 해당 provider를 즉시 **비활성화**하고 다음
provider로 넘어간다:

- Free quota exhausted (무료 한도 소진 확인됨)
- Free quota uncertain (한도 소진 여부를 확실히 알 수 없음)
- Billing state unknown (과금 상태를 확인할 수 없음)

**무료 한도 상태를 정확히 알 수 없는 provider는 보수적으로(사용 중단
방향으로) 처리한다.** 이것은 hard rule이며 §1.5(AI가 변경할 수 없는 것)에
포함된다 — "free API billing policy"는 AI가 임의로 바꿀 수 없다.

### 6.5 AI Gateway 테스트 시나리오 (필수)

- Provider A 정상 → A가 성공 응답
- Provider A quota exhausted → A에서 B로 자동 전환
- A/B/C 모두 실패 → NO AI CALL, 시스템은 안전하게 실패 (예외적으로
  거래를 막는 방향으로만 영향, 절대 무단으로 유료 API를 부르지 않음)
- A quota reset → 다시 B에서 A로 복귀 (우선순위 원복)
- Provider가 유료 상태로 전환된 것이 감지되면 → 해당 provider disabled

---

## 7. Data Layer

### 7.1 필수 메타데이터

모든 데이터 레코드는 최소 다음 메타데이터를 가져야 한다:

```
symbol
timestamp
source
data_type
version
availability_time
ingestion_time
quality_status
```

### 7.2 Point-in-Time Principle (핵심 원칙)

AI가 특정 시점(예: 2020-01-01)에 투자 판단을 내린다고 가정하면, **그
시점 이후에 공개된 정보를 절대로 볼 수 없다.** 데이터의 다음 세 시각을
가능한 한 분리하여 관리한다:

```
event_time         # 실제 사건이 발생한 시점
publication_time    # 정보가 외부에 공개된 시점
available_time       # 시스템이 실제로 그 데이터를 사용할 수 있게 된 시점
```

백테스트/학습/실전 판단 모두 `available_time` 기준으로만 데이터에 접근한다.

### 7.3 Survivorship Bias 방지

현재 S&P500 구성종목만 과거로 되돌려서 백테스트하지 않는다. 가능한 경우
**당시의 구성종목**과 **당시 이용 가능했던 정보**를 사용한다. 상장폐지된
종목(delisted company)도 연구 데이터에 적절히 포함하여 처리한다.

### 7.4 Corporate Action 처리

가능한 경우 다음을 고려한다:
- stock split
- dividend
- merger
- spin-off
- ticker change
- delisting

단순히 현재 가격 데이터를 그대로 과거에 적용하는 구조를 피한다.

### 7.5 Feature Registry

Feature는 중앙 Feature Registry에서 관리한다. 각 feature는 다음을 기록한다:

```
feature_id
name
definition
source
lookback
formula
availability
version
status
```

Feature가 미래 데이터를 사용하지 않는지 **자동으로 검증**할 수 있는
구조(leakage test)를 설계한다.

### 7.6 Market Regime

Regime Detection은 독립된 모듈이다. 예시 분류축:

```
Regime
├── Trend
├── Volatility
├── Liquidity
├── Correlation
└── Market Stress
```

최종 regime 모델은 실험을 통해 결정하며, 초기 구현에서 특정 알고리즘을
전제하지 않는다.

---

## 8. Prediction / Decision / Risk Layer

### 8.1 Prediction Layer

Prediction은 투자 결정과 분리한다. 출력 예:

```
Prediction
├── expected_return
├── probability
├── expected_volatility
├── uncertainty
└── confidence
```

Prediction 결과만으로 바로 주문하지 않는다.

### 8.2 Decision Layer

Decision Agent는 prediction + regime + portfolio state + risk state를
종합하여 판단한다. 가능한 행동:

```
BUY / SELL / HOLD / EXIT / NO_TRADE
```

필요 시 `target_weight`, `confidence`, `time_horizon`을 함께 반환한다.

**NO_TRADE는 실패가 아니다.** 다음 상황에서는 거래하지 않는 것이 정상적인
최적 행동일 수 있다:

- confidence가 낮음
- risk가 높음
- expected return이 transaction cost보다 낮음
- 시장 regime이 불확실
- liquidity 부족
- portfolio exposure가 이미 높음
- 데이터 이상
- 모델 이상

### 8.3 Position Sizing

별도의 **deterministic/risk-aware** 계층으로 둔다 (AI가 아님).

입력: `expected_return, risk, confidence, volatility, correlation,
portfolio_exposure, liquidity, risk_budget`

출력: `target_weight, target_quantity`

AI가 임의로 위험한 포지션 크기를 설정하지 못하도록 이 계층에서 강제한다.

### 8.4 Portfolio Risk Engine

포트폴리오 수준에서 다음을 관리할 수 있는 구조를 만든다:

```
single_position_limit
sector_limit
factor_limit
portfolio_volatility_limit
drawdown_limit
cash_minimum
turnover_limit
liquidity_limit
```

구체적인 값(숫자)은 이후 실험을 통해 결정한다 — 지금 하드코딩하지 않는다.

---

## 9. Order System & Broker Layer

### 9.1 주문 상태 머신

```
PROPOSED → VALIDATING → REJECTED
                       → SUBMITTED → PARTIALLY_FILLED → FILLED
                                   → CANCEL_REQUESTED → CANCELLED
                                   → FAILED
                                   → UNKNOWN
```

**UNKNOWN 상태를 반드시 고려한다.** Broker API와 연결이 끊긴 경우 주문이
실제로 체결됐는지 시스템이 모를 수 있다. 이 경우 §1.4(Fail-Closed)에 따라
포지션/현금 상태가 확인될 때까지 신규 주문을 차단한다.

### 9.2 Idempotency

같은 주문 요청이 두 번 실행되어 중복 주문이 발생하지 않도록, 모든 주문
요청에는 고유한 **idempotency key**를 사용한다.

### 9.3 토스증권 Adapter 구조

실제 증권 거래는 Toss Securities API를 사용하지만, **core system은
Toss API에 직접 의존하지 않는다.**

```
Core Trading System
        ↓
Broker Interface           (추상 인터페이스: place_order, cancel_order,
                             get_position, get_cash, get_order_status ...)
        ↓
Toss Securities Adapter    (Broker Interface의 구체 구현체)
        ↓
Toss Securities API
```

**규칙:**
- 토스증권 API의 정확한 endpoint, authentication 방식, request/response
  schema는 **구현 시점에 공식 API 문서를 확인**한다. 추측해서 endpoint를
  만들지 않는다.
- Broker Interface는 broker에 중립적으로 설계하여, Toss Adapter 대신
  Paper Broker Adapter로 즉시 교체 가능해야 한다.
- Toss Adapter 내부에서만 Toss 고유의 인증/서명/요청 포맷을 다루고,
  이를 표준 Order/Fill/Position 데이터 모델로 변환하여 상위 계층에
  전달한다.
- Toss Adapter는 broker credential을 직접 보관하지 않고 secret
  management를 통해서만 접근한다 (§1.5).

### 9.4 Paper Trading

실제 주문 이전에 동일한 주문 pipeline을 Paper Broker로 실행할 수 있어야
한다.

```
Trading Engine → Broker Interface → Paper Broker   (개발/검증 기본값)
Trading Engine → Broker Interface → Toss Broker    (Live에서만, 명시적 활성화 후)
```

Core trading logic은 broker를 교체해도 바뀌지 않는다.

---

## 10. Trade Journal — 상세 요구사항

### 10.1 정의

**Trade Journal은 단순 DB 로그가 아니다. 시스템의 장기 기억(long-term
memory)이다.** Claude Code의 대화 기억이나 임시 상태에 의존하지 않고,
이 Journal 하나만으로 과거 모든 거래의 전체 맥락을 재구성할 수 있어야 한다.

### 10.2 거래당 최소 기록 필드

```
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
```

### 10.3 Decision Snapshot

거래 당시의 **모든 중요한 상태를 snapshot**으로 저장한다. 목적:

> 몇 년 뒤에도 AI가 왜 해당 거래를 했는지 **재현**할 수 있어야 한다.

Decision Snapshot은 최소한 그 시점의 features 값, prediction 출력,
regime 분류, risk_state, 그리고 어떤 model_version/strategy_version이
결정을 내렸는지를 함께 저장해야 한다.

### 10.4 Post Trade Analysis

거래 종료 후 **Expected vs Actual**을 비교하고 다음을 저장한다:

```
prediction_error
timing_error
risk_estimation_error
execution_error
regime_error
signal_error
```

### 10.5 Counterfactual Analysis

실제로 선택한 행동과 선택하지 않은 행동을 비교한다. 가능한 경우:

```
selected_action
alternative_action_1
alternative_action_2
hold
cash
```

각각의 결과를 기록한다.

### 10.6 Performance Attribution

실제 수익의 원인을 분해하여 분석한다:

```
market / sector / factor / selection / timing / execution
```

이를 통해 AI가 실제로 alpha를 만들어냈는지, 아니면 시장 베타를 alpha로
착각하고 있는지를 분석한다.

### 10.7 Experience Dataset로의 변환

Trade Journal은 학습용 데이터(Experience Dataset)로 변환된다. Experience는
다음을 포함할 수 있다:

```
state / action / expected_outcome / actual_outcome / reward
market_regime / risk_state / prediction_error / counterfactual_results
```

**Historical vs Live 구분(provenance)은 필수다:**

```
HISTORICAL_SIMULATION | PAPER_TRADING | LIVE_TRADING
```

이 구분 없이 세 가지 출처의 데이터를 섞어서 학습하지 않는다.

---

## 11. Learning Engine & Model Lifecycle — 자동학습 및 자동배포 안전장치

### 11.1 Learning Engine 파이프라인

```
Experience → Data Cleaning → Labeling → Training Dataset
   → Candidate Training → Evaluation
```

**핵심 안전장치: 학습 결과(새 모델)는 절대 자동으로 Live에 적용되지
않는다.** 이것은 §1.5 헌법 조항이다.

### 11.2 Candidate Model 상태 머신

```
CANDIDATE → BACKTESTED → VALIDATED → OOS TESTED → PAPER TESTED
   → APPROVED → DEPLOYED
```

각 화살표는 **자동 전이가 아니다.** 각 단계는 명시적 검증 기준을
통과해야만 다음 단계로 전이하며, `APPROVED → DEPLOYED` 전이는 특히
사람의 명시적 승인을 요구한다 (§11.5).

### 11.3 Model Registry

모델마다 다음을 관리한다:

```
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
```

### 11.4 Model Rollback

현재 Live Model과 이전 Stable Model을 항상 구분한다:

```
ACTIVE / STABLE / CANDIDATE / RETIRED / FAILED
```

새 모델의 성능 이상 감지 시 **이전 STABLE 모델로 즉시 rollback**할 수
있어야 한다. Rollback 메커니즘은 Deployment 기능과 별개로, 항상 준비된
상태여야 한다 (Deployment가 고장나도 Rollback은 동작해야 함).

### 11.5 AI 자기 개선의 안전장치

AI는 다음을 **제안**할 수 있다: 새로운 feature, 새로운 모델, 새로운
reward, 새로운 strategy, 새로운 risk parameter, 새로운 regime model.

그러나 **제안과 적용은 반드시 분리**한다:

```
AI Proposal → Experiment → Validation → Approval → Deployment
```

- `Approval` 단계는 사람의 개입을 기본으로 한다 (§11.2, §11.5의 정신).
- 자동화된 배포 파이프라인을 만들더라도, `APPROVED` 상태로의 전이만은
  사람이 명시적으로 승인해야 한다. Claude Code나 AI가 스스로
  `APPROVED`를 부여하지 않는다.

### 11.6 Drift Detection

다음 drift를 지속적으로 감시한다:

- **Data Drift**: 입력 데이터 분포 변화
- **Feature Drift**: feature 분포 변화
- **Prediction Drift**: AI prediction 분포 변화
- **Performance Drift**: 실제 성능 저하
- **Regime Drift**: 시장 구조 변화

Drift가 감지되면 자동으로 모델을 교체하지 않고, Monitoring/Alerting을
거쳐 재검증 프로세스를 트리거한다.

---

## 12. Kill Switch & 장애/복구 규칙

### 12.1 Kill Switch 발동 조건

다음 상황에서는 신규 주문을 **자동으로 중단**할 수 있어야 한다:

```
critical data failure
broker failure
unexpected position
invalid model output
excessive drawdown
daily loss limit
abnormal order frequency
API failure
system integrity failure
```

**Kill switch는 AI가 해제할 수 없도록 설계하는 것을 우선 고려한다.**
해제는 사람의 명시적 조치를 요구하는 방향을 기본값으로 한다.

### 12.2 장애 발생 시 기본 원칙

시스템이 불확실한 상태가 되면 **"거래하지 않는 방향"이 기본값**이다
(§1.4 Fail-Closed와 동일 원칙의 재확인):

```
Data Unknown / Broker Unknown / Position Unknown / Model Unknown
   → 신규 주문 차단
```

### 12.3 복구 절차 원칙

- 장애 원인이 해소되었다고 자동으로 판단하지 않는다. 복구는 명시적
  헬스체크 통과 + (Live 환경의 경우) 사람의 확인을 거친다.
- Broker와의 연결이 끊긴 뒤 재연결되었을 때, 먼저 **포지션/현금/미체결
  주문 상태를 broker 측과 대조(reconciliation)**한 이후에만 신규 주문을
  재개한다.
- UNKNOWN 상태의 주문은 별도로 추적하며, 해당 주문의 실제 상태가
  확인되기 전까지 관련 종목/현금에 대한 신규 주문을 제한할 수 있다.
- 장애/kill switch 발동/rollback 이벤트는 반드시 audit log로 남긴다 (§15.1).

### 12.4 Monitoring

시스템은 다음을 지속적으로 모니터링한다:

```
portfolio_value / cash / positions / exposure / PnL / drawdown
orders / fills / API status / data status / model status
feature drift / prediction drift / performance
```

### 12.5 Alerting

Critical event 발생 시 기록 및 알림 가능한 구조를 만든다. Severity:

```
CRITICAL / WARNING / INFO
```

초기에는 logging 중심으로 구현하고, 이후 알림 provider(이메일, 메신저
등)를 추가할 수 있는 구조로 설계한다.

---

## 13. Backtesting & Validation — 상세 규칙

### 13.1 Backtest 구조 원칙

백테스트는 실제 거래와 최대한 동일한 core logic을 사용한다. 이상적인
구조:

```
Backtest Broker / Paper Broker / Live Broker
   → 모두 동일한 Broker Interface를 구현
```

### 13.2 거래비용(Transaction Cost) 반영

백테스트에서 거래비용을 반드시 고려한다. 가능한 항목:

```
commission / spread / slippage / market impact
```

실제 값은 데이터와 broker 조건을 바탕으로 설정하며, 임의로 낙관적인
값을 가정하지 않는다.

### 13.3 Backtest Integrity 체크리스트

백테스트는 다음 조건을 **모두** 만족해야 한다:

- [ ] 미래 데이터 없음
- [ ] 미래 가격 사용 없음
- [ ] 미래 구성종목 사용 없음 (survivorship bias 없음)
- [ ] 미래 corporate action 정보의 잘못된 사용 없음
- [ ] execution timing 왜곡 없음 (같은 봉의 종가로 그 봉에서 산 것처럼
      가정하지 않는 등)
- [ ] transaction cost 누락 없음

### 13.4 Validation Protocol (기본 검증 순서)

```
Training → Validation → Walk Forward → Purged Validation → Embargo
   → Out of Sample → Paper Trading
```

필요한 경우 여러 기간에 대해 반복한다.

### 13.5 Backtest Overfitting 방지

전략을 많이 시도하면 최고 전략이 우연히 좋은 것일 수 있다. 따라서
다음을 반드시 함께 기록한다:

```
Experiment Count + OOS Result + PBO(Probability of Backtest Overfitting)
   + Deflated Sharpe Ratio + Walk Forward 결과
```

과최적화를 유발하는 다음 패턴을 경계한다:

```
Parameter tuning → backtest → best result selection → repeat (무제한 반복 금지)
```

모든 실험 횟수를 기록하고 selection bias를 고려한다 (§13.8).

### 13.6 Benchmark & Baseline

**최소 benchmark:** S&P 500 Buy & Hold — 동일 기간, 동일 초기 자본,
가능한 한 동일한 비용 가정으로 비교한다.

**최소 baseline:** S&P 500 Buy & Hold, Simple Momentum, Simple ML.
복잡한 AI가 정말 가치가 있는지 확인하기 위한 것이다. AI 시스템이
baseline을 지속적으로 능가하지 못한다면, 복잡한 모델을 추가하는 대신
**원인을 분석**한다 (§13.6 Baseline 우선 원칙).

### 13.7 S&P 500 초과수익 판단 기준

다음 조건을 모두 고려하며, **단 한 번의 높은 수익률로 성공을 판정하지
않는다:**

```
Return / Risk / Drawdown / Consistency / Transaction Cost / Turnover
Out-of-Sample / Walk Forward / Benchmark 대비 결과
```

### 13.8 Experiment Tracking

모든 실험에 고유 ID(`EXP-000001`, `EXP-000002`, ...)를 부여하고 다음을
저장한다:

```
experiment_id / timestamp / code_version / data_version / feature_version
model_version / parameters / dataset / metrics / benchmark / result / notes
```

### 13.9 Reproducibility

가능한 경우 동일한 `data / code / config / seed / model / parameters`로
실험을 재현할 수 있어야 한다.

### 13.10 테스트 전략 (구축 순서)

```
Unit Test → Integration Test → Backtest Test → Data Leakage Test
   → Risk Test → Order Validation Test → Broker Adapter Test
   → AI Gateway Test → Quota Rotation Test → Failure Recovery Test
```

**높은 우선순위로 테스트할 금융 로직:** portfolio calculation, position
sizing, PnL, transaction cost, slippage, drawdown, benchmark calculation,
order quantity, exposure, risk limits.

**Broker 테스트 (mock/paper 환경, 실제 자금 사용 안 함):** buy, sell,
cancel, partial fill, failed order, timeout, unknown order state,
duplicate request.

### 13.11 Live 이전 조건 (Go-Live Gate)

Live Trading은 다음을 **모두** 통과해야 한다. 하나라도 만족하지 못하면
Live로 가지 않는다.

```
[ ] Data validation PASS
[ ] Backtest PASS
[ ] OOS PASS
[ ] Risk tests PASS
[ ] Leakage tests PASS
[ ] Paper trading PASS
[ ] Broker tests PASS
[ ] Kill switch PASS
[ ] Rollback PASS
[ ] Monitoring PASS
```

### 13.12 실전 자금 제한

초기 Live 단계에서는 전체 자본을 바로 투입하지 않는다. 구체적인 자본
비율은 향후 결정한다. 원칙:

```
Paper → Small Capital → Controlled Expansion
```

---

## 14. Configuration, Secrets, Environment

### 14.1 Configuration

코드에 실험값을 하드코딩하지 않는다:

```
configs/
├── development/
├── backtest/
├── paper/
└── live/
```

### 14.2 Secrets

API key를 절대 코드에 저장하지 않는다. 금지: `API_KEY = "xxxxx"` 같은
하드코딩. 대신 환경변수 또는 안전한 secret management를 사용한다.
`.env`는 Git에 커밋하지 않는다. `.env.example`에는 필요한 변수 **이름만**
기록한다.

### 14.3 Environment 분리

최소 `development / backtest / paper / live` 환경을 분리한다. 환경 간
API key와 configuration을 혼용하지 않는다.

### 14.4 Live Trading 안전 원칙

Live mode는 명시적으로 활성화되어야 한다. 기본값은:

```
LIVE_TRADING = false
```

개발/테스트 환경에서 실계좌 주문이 발생해서는 안 된다.

### 14.5 Security 최소 요구사항

- API key 보호
- 최소 권한(Principle of Least Privilege)
- broker credential 분리
- AI provider credential 분리
- secret rotation 고려
- audit logging
- dangerous operation confirmation
- production configuration 분리

---

## 15. Logging & Auditability

### 15.1 필수 Audit Log 대상

```
AI decision / order proposal / risk rejection / order submission
order fill / trade completion / model change / provider switch
quota exhaustion / kill switch / rollback
```

### 15.2 Auditability — 반드시 답할 수 있어야 하는 질문

- 왜 이 거래가 발생했는가?
- 당시 AI가 무엇을 알고 있었는가?
- 어떤 모델이 결정했는가?
- 어떤 risk rule을 통과했는가?
- 어떤 가격으로 주문했는가?
- 왜 모델이 변경되었는가?
- 누가/무엇이 모델 변경을 승인했는가?

---

## 16. AI 자율성의 단계적 확대

자율성은 다음처럼 단계적으로 증가시킨다. **처음부터 Level 4를 구현하지
않는다.**

```
Level 0  Research Assistant           (연구/분석 보조만)
Level 1  Backtest Agent               (백테스트 실행/분석)
Level 2  Paper Trading Agent          (모의투자 자동 실행)
Level 3  Restricted Live Agent        (제한된 실계좌, 소액)
Level 4  Autonomous Trading Agent     (완전 자율, 장기 목표)
```

---

## 17. 연구 기반 (Research Foundation)

### 17.1 초기 S급 연구

| 연구 | 저자 | 활용 |
|---|---|---|
| Empirical Asset Pricing via Machine Learning | Gu, Kelly & Xiu | ML, nonlinear prediction, feature interaction, momentum, liquidity, volatility |
| Time Series Momentum | Moskowitz, Ooi & Pedersen | momentum, trend, market state |
| The Probability of Backtest Overfitting | Bailey et al. | backtest overfitting, multiple testing, strategy selection |
| The Deflated Sharpe Ratio | Bailey & López de Prado | multiple testing, selection bias, Sharpe adjustment |
| Optimal Execution of Portfolio Transactions | Almgren & Chriss | execution, transaction cost, market impact |
| Financial Machine Learning Validation Methods | López de Prado 계열 | Purged K-Fold, Embargo, time-series validation |
| FinRL | — | DRL architecture, trading environment, portfolio management, backtesting |

### 17.2 논문 등급 시스템

- **S**: 프로젝트 핵심 설계에 직접 반영할 가치가 있는 연구
- **A**: 특정 기능/알고리즘에 중요한 연구
- **B**: 아이디어 참고
- **C 이하**: 구현 근거로 사용하지 않는 것을 원칙으로 함

최신 논문이라는 이유만으로 S급으로 분류하지 않는다.

### 17.3 추가 연구 규칙

새 논문이 필요할 때 무작정 추가하지 않는다. 먼저 **"어떤 설계 결정이
근거를 필요로 하는가?"**를 정의하고, 그 결정에 필요한 최소한의 연구만
수행한다. 컨텍스트와 프로젝트 복잡도를 불필요하게 늘리지 않는다.

---

## 18. Phase 순서 및 진행 규칙

### 18.1 Phase 목록

```
Phase 0   Foundation
Phase 1   Data Infrastructure
Phase 2   Backtesting
Phase 3   Trade Journal
Phase 4   Baseline Models
Phase 5   Market Regime
Phase 6   Prediction
Phase 7   Decision Agent
Phase 8   Position / Risk
Phase 9   Learning
Phase 10  Counterfactual / Attribution
Phase 11  Model Evolution
Phase 12  AI Gateway
Phase 13  Toss Securities Adapter
Phase 14  Monitoring / Drift / Safety
Phase 15  Paper Trading
Phase 16  Live Trading
```

### 18.2 Phase 진행 규칙

각 Phase마다 반드시 다음 순서를 수행한다:

```
Specification → Implementation → Unit Tests → Integration Tests
   → Validation → Documentation → Status Update
```

**Phase가 완료되기 전에 다음 Phase로 넘어가지 않는다.**

### 18.3 각 Phase에서 Claude Code가 해야 할 것

- 해당 Phase의 `docs/specifications/PHASE-N-*.md` 문서를 먼저 작성하거나
  확인한다.
- 이전 Phase까지 통과한 테스트를 깨뜨리지 않는지 확인한다 (회귀 방지).
- 구현 → 테스트 → 검증 → 문서화 → `docs/PROJECT_STATUS.md` 갱신까지
  완료해야 그 Phase의 해당 작업을 "완료"로 표시한다.
- Phase 경계를 넘는 설계 변경이 필요하면 ADR을 먼저 작성한다.
- 각 세션 종료 시 `docs/PROJECT_STATUS.md`를 반드시 최신 상태로 갱신한다.

### 18.4 각 Phase에서 Claude Code가 하면 안 되는 것

- 현재 Phase보다 앞선 Phase의 기능(특히 Phase 13 Toss Adapter의 실제
  API 연동, Phase 16 Live Trading)을 조기 구현하지 않는다.
- Phase 0~11 (Foundation ~ Model Evolution) 동안에는 실계좌 주문 코드나
  실제 AI API 호출 코드를 작성하지 않는다. (§5의 첫 세션 임무와 동일한
  정신이 전체 Foundation 단계에 적용된다 — 단, Phase 12 AI Gateway부터는
  AI API 연동이 Phase의 목적 자체이므로 그 시점부터는 허용되나, 여전히
  실제 API 키 없이도 안전하게 동작(mock/무료 한도 검증)함을 우선 확인한다.)
- 검증(Validation) 단계를 건너뛰고 다음 Phase로 넘어가지 않는다.
- 테스트가 실패한 상태로 "완료"라고 보고하지 않는다.
- Phase 순서를 사용자 승인 없이 임의로 재배치하지 않는다.
- §1.1(절대 금지 사항)에 해당하는 어떤 행동도 Phase와 무관하게 하지 않는다.

### 18.5 "완료"의 정의 (Definition of Done)

기능이 코드로 작성됐다는 이유만으로 완료로 판단하지 않는다. 기능마다
최소 다음이 모두 충족되어야 "완료"다:

- [ ] **구현** — 명세에 부합하는 코드
- [ ] **테스트** — 최소 unit test, 필요 시 integration test 존재 및 통과
- [ ] **에러 처리** — 예상 가능한 실패 경로에 대한 처리
- [ ] **logging** — 최소한의 audit/debug 로그
- [ ] **documentation** — `docs/specifications/` 또는 관련 문서 갱신
- [ ] **configuration** — 하드코딩 없이 환경별 설정 분리
- [ ] **validation** — 이 기능이 상위 검증 기준(해당되는 경우 §13)을
      만족하는지 확인

이 중 하나라도 빠지면 "부분 완료(In Progress)"로 `PROJECT_STATUS.md`에
기록하고, 완료로 보고하지 않는다.

---

## 19. 변경관리 (Change Management)

새로운 기능/설계 변경이 제안되었을 때 다음 순서를 따른다:

```
Requirement → Impact Analysis → Architecture Decision → ADR
   → Master Plan Update → Implementation
```

### 19.1 계획 변질 방지 규칙

향후 사용자와 Claude Code 사이에서 계획이 임의로 변질되지 않도록 다음을
지킨다:

1. **이 문서(PROJECT_MASTER_PLAN.md)가 항상 우선한다.** 대화 중의 임시
   지시가 이 문서의 §1(헌법)과 충돌하면, Claude Code는 그 충돌을
   명시적으로 지적하고 사용자에게 확인을 요청한다. 조용히 헌법을
   무시하고 지시를 따르지 않는다.
2. **작은 변경(파라미터 값, 버그 수정, 리팩터링)**은 ADR 없이 진행할 수
   있다.
3. **큰 변경(아키텍처, Phase 순서, 헌법 조항, 안전장치, 데이터 흐름)**은
   반드시 ADR을 작성하고 `PROJECT_MASTER_PLAN.md`를 갱신한 뒤 구현한다.
4. Claude Code는 프로젝트의 핵심 목적이나 안전 원칙(§1)을 **임의로
   변경하지 않는다.**
5. 개발자(사용자)의 판단이 필요한 문제가 생기면, 즉흥적으로 결정하지
   않고 다음 형식으로 보고한다:

```
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
```

6. 이 형식 없이 중요한 아키텍처를 바꾸지 않는다.
7. 계획과 실제 코드가 어긋난 것을 발견하면, 코드를 기준으로 계획을
   조용히 수정하지 않는다. 반드시 차이를 기록하고(가능하면 ADR로),
   원인을 분석한 뒤 어느 쪽을 따를지 명시적으로 정리한다.

### 19.2 ADR (Architecture Decision Record)

중요한 설계 변경은 반드시 ADR을 만든다. 예:

```
ADR-0001-master-architecture.md
ADR-0002-data-model.md
ADR-0003-backtest-validation.md
ADR-0004-ai-provider-gateway.md
ADR-0005-broker-adapter.md
```

---

## 20. 구현 우선순위

```
P0 — 반드시 필요
  Data integrity, Backtest, Benchmark, Trade Journal, Risk, Validation,
  Model versioning, AI Gateway, Broker abstraction, Safety

P1 — 핵심
  Regime, Prediction, Decision Agent, Learning, Counterfactual,
  Attribution, Drift

P2 — 확장
  additional data, advanced NLP, additional AI providers,
  advanced optimization, additional brokers
```

---

## 21. 최소 기능으로 시작 (Minimal Viable Research System)

초기 시스템은 모든 것을 한 번에 구현하지 않는다. 최초의 완전한 연구
가능한 시스템은 다음 정도면 된다:

```
Market Data → Data Validation → Simple Features → Baseline Strategy
   → Backtest → S&P500 Benchmark → Trade Journal → Metrics
```

이것이 안정화된 후 AI를 단계적으로 추가한다. **복잡한 AI를 만들기 전에
반드시 baseline을 만든다** — 복잡한 AI가 단순 전략보다 실제로 가치가
있는지 증명해야 하기 때문이다 (§13.6).

---

## 22. 시스템의 장기 기억 구성

```
Trade Journal / Experiment Registry / Model Registry / Feature Registry
Decision Snapshots / Post Trade Analysis / Architecture Decisions
Research Notes / Performance History
```

Claude Code의 대화 기억에 의존하지 않는다.

---

## 23. Claude Code의 역할과 한계

Claude Code는: 코드를 작성한다 / 테스트를 작성한다 / 시스템을 구현한다 /
문서를 유지한다 / 문제를 분석한다 / 구현상의 대안을 제시한다.

하지만: **프로젝트의 핵심 목적이나 안전 원칙을 임의로 변경하지 않는다.**

---

## 24. 가장 중요한 개념 재확인

- Trade Journal은 로그가 아니다. **경험 메모리**다.
- Model Registry는 파일 저장소가 아니다. **모델 진화 기록**이다.
- Experiment Tracking은 단순 결과 저장소가 아니다. **연구 기억**이다.
- Validation은 단순 테스트가 아니다. **실전 투입 자격 심사**다.
- AI Gateway는 API wrapper가 아니다. **AI 자원 관리 계층**이다.
- Risk Engine은 보조 기능이 아니다. **AI의 행동을 제한하는 안전 경계**다.

---

## 25. 최초 디렉터리 구조

```
/
├── PROJECT_MASTER_PLAN.md   (본 문서)
├── README.md
├── .gitignore
├── .env.example
│
├── docs/
│   ├── PROJECT_STATUS.md
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
│   ├── development/
│   ├── backtest/
│   ├── paper/
│   └── live/
├── data/
├── experiments/
└── logs/
```

---

## 26. 최종 요약

> 이 프로젝트는 **"AI에게 주식 매매를 시키는 프로그램"이 아니라, "AI가
> 시장을 관찰하고 판단하고 거래하고 그 결과를 기억하며 자신의
> 의사결정을 검증하고 개선하는 폐쇄형 투자 연구·학습·실행 시스템"**을
> 만드는 프로젝트다. 최종 목표는 **검증 가능한 방식으로 S&P 500을
> 장기적으로 초과하는 것**이다. 모든 설계와 구현은 이 목표에 기여해야
> 하며, §1(헌법)의 절대 우선순위(Capital Safety 최우선, Complexity
> 최하위)를 절대 위반하지 않는다.

**END OF PROJECT_MASTER_PLAN.md**
