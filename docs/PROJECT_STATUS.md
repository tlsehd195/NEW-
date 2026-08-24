# PROJECT STATUS

> 새 Claude Code 세션은 이 파일 하나만 읽어도 현재 프로젝트가 어디까지
> 진행되었는지 파악할 수 있어야 한다. 이 파일은 각 세션 종료 시 반드시
> 최신 상태로 갱신한다.

**Last Updated:** 2026-08-24
**Updated By:** Claude Code (Session 4 — Phase 3 Trade Journal)

---

## Current Phase

**Phase 3 — Trade Journal** (설계 및 참조 구현 완료)

## Current Subtask

Phase 3 Definition of Done 충족: 명세 + ADR-0009 + `src/trade_journal/`
전체(모델/저장소/분석/경험 변환/Phase 2 연동) 참조 구현 + 17개
카테고리(+Phase2 통합) 테스트 전부 통과. **DECISION REQUIRED 2건 추가
발생** (기존 벤치마크 return type 1건 + 이번 세션의 Phase 2 정밀도
관련 2건 — 아래 참조).

---

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

## In Progress

없음 (Phase 3 설계+참조구현 완료).

## Blocked

**DECISION REQUIRED 3건 누적 — 사용자 확인 필요:**
1. (Phase 2에서 이어짐) 벤치마크 return type (PRICE_RETURN vs
   TOTAL_RETURN)
2. (이번 세션 신규) `BacktestEngine`의 per-decision `data_version`
   미노출 — Trade Journal이 결정 단위 데이터 버전을 `None`으로 기록
3. (이번 세션 신규) `BacktestResult`의 per-step corporate action 이벤트
   미노출 — Trade Journal의 `portfolio_state` 재구성이 fill 재생 기반
   근사치이며 두 fill 사이에 발생한 corporate action을 반영하지 못함

모두 아래 "DECISION REQUIRED" 섹션에 상세 기록. Phase 3 코드/테스트
자체는 이 결정들과 무관하게 정상 동작하며 구현이 차단된 것은 아니다.

## DECISION REQUIRED — Phase 2 정밀도 개선 (신규, 미결)

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
(문서화된 한계, ADR-0009).

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
Option B는 Phase 2 아키텍처 변경이므로 Phase 2/3 세션 하나에서 임의로
결정하지 않는다.

Impact:
현재 Trade Journal에서 나온 Experience Record는 data_version 필드가
비어 있으므로(None) 재현성 검증 시 trade-level(Fill.data_version)
정밀도까지만 신뢰할 수 있다. corporate action이 포함된 백테스트의
portfolio_state 스냅샷은 근사치일 수 있다. 둘 다 성능/정확성 지표
자체(realized_pnl, execution_price 등)에는 영향이 없다 — 영향은
오직 "그 순간의 재현된 컨텍스트"의 정밀도에 국한된다.
```

## Design Decisions (이번 세션의 핵심 결정)

1. Phase 2의 `Order`/`Fill`/`PortfolioView`를 **직접 임베드**하여
   재사용 — 병렬 스키마를 만들지 않음 (ADR-0009).
2. 모든 Journal 레코드는 `frozen=True` dataclass — 불변성을 언어
   차원에서 강제.
3. 수정은 **원본 불변 + CorrectionRecord 추가** 방식만 허용 —
   `TradeJournalRepository`에는 `update_*`/`delete_*` 메서드 자체가
   없음.
4. Idempotency는 **natural key**(`experiment_id` + `order_id`/
   `fill.order_id`) 기반이며, id 할당은 저장소 내부에서만 수행(Phase
   1/2와 동일 패턴).
5. Post Trade Analysis/Counterfactual/Attribution은 **실제로 계산
   가능한 필드만 계산**(execution_error, post-hoc hold counterfactual,
   execution attribution)하고 나머지는 정직하게 `None` — 추정값을
   사실처럼 저장하지 않는다는 지시를 그대로 구현.
6. `backtest.enums.OrderStatus`에 `CANCELLED`를 additive하게 추가하여
   Phase 13+ 비동기 브로커를 위한 확장성을 미리 확보 (Phase 2 코드
   영향 없음, 기존 테스트 전부 통과 확인 후 진행).

## Known Risks / Limitations (의도적으로 남겨둔 항목)

- (Phase 1/2에서 이어짐) 실 저장소 백엔드 없음, 실 데이터 provider
  없음, 벤치마크 return type 미결.
- Phase 3의 `data_version`(per-decision) 및 `portfolio_state`(corporate
  action 반영) 정밀도 한계 — 위 DECISION REQUIRED 참조.
- `prediction_error`, `timing_error`, `risk_estimation_error`,
  `regime_error`, `signal_error`, `market`/`sector`/`factor`/
  `selection`/`timing` attribution — 전부 `None` (Phase 5/6/8 부재).
- 명시적 `NO_TRADE` 의사결정 로깅 없음 — Phase 2 Strategy가 주문 의도를
  생성한 경우만 기록됨 (Phase 7 Decision Agent가 생기면 확장).
- Experience Record의 `reward`는 단순 `realized_return` 매핑 — 실제
  reward function 설계는 Phase 9 과제.
- 영속 저장소 없음 (`InMemoryTradeJournalRepository`만 존재).

## Recent Experiments

없음 (실제 데이터 기반 실험 없음). Phase 3는 새로운 실험을 만들지
않고 Phase 2의 `ExperimentRecord`를 참조만 한다.

## Current Model / Current Benchmark

Phase 2와 동일 (변화 없음).

## Last Validation

`python3 -m pytest tests/ -q` — **202 passed**
(Phase 1: 57, Phase 2: 82, Phase 3: 63). Phase 3의 63개 테스트는
지시된 17개 카테고리(trade creation, decision snapshot integrity,
immutable snapshot, order/fill linkage, partial fill, rejected order,
cancelled order, duplicate event/idempotency, realized PnL, holding
period, provenance, version lineage, point-in-time snapshot, audit
trail, historical/paper/live separation, experience conversion,
correction/audit record) + Phase 2 통합 테스트를 전부 포함한다.

---

## Not Yet Implemented

- AI trading decision / LLM API 호출 / Toss Securities / Live Trading
- 실제 외부 데이터 provider, DuckDB/Parquet 영속 백엔드 (Phase 1부터)
- Limit order, Purged K-Fold/Embargo, 5종 corporate action 처리 (Phase
  2부터)
- Feature Engine, Market Regime Detection, Prediction Engine, 완전한
  Decision Agent, Position Sizing/Portfolio Risk Engine (Phase 5-8)
- 실제 Post Trade Analysis 알고리즘(prediction/timing/risk/regime/
  signal error), 실제 Performance Attribution(market/sector/factor/
  selection/timing), 모델 기반 Counterfactual — 전부 구조만 준비됨
- Trade Journal 영속 저장소
- Paper/Live 브로커 어댑터 (Trade Journal의 `PAPER_TRADING`/
  `LIVE_TRADING` provenance를 실제로 생산할 producer 없음)
- Model Registry / "왜 모델이 변경되었는가" 감사 질문 (Phase 11)

---

## Next Recommended Task

1. **DECISION REQUIRED 3건 확인**: 벤치마크 return type, per-decision
   data_version, corporate-action-aware portfolio_state 재구성.
2. **Phase 4 — Baseline Models** 착수 검토, 또는 **Phase 5 — Market
   Regime** 착수: `PROJECT_MASTER_PLAN.md` §61의 Phase 순서를 따를 것.
   Phase 4/5 중 무엇을 먼저 할지는 마스터플랜 순서(Phase 4가 먼저)를
   기본으로 하되, 사용자 지시가 있으면 그에 따른다.
3. Phase 9(Learning Engine) 착수 시점에 위 DECISION REQUIRED 2건(데이터
   버전/corporate action lineage)을 재평가.

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
