---
type: entity
title: broker
tags:
  - module
  - phase-13
  - broker
created: '2026-09-24T10:17:13.844Z'
---
## 역할
Phase 13 — 브로커 어댑터. PROJECT_MASTER_PLAN.md 9.3절: "core system은 Toss API에 직접 의존하지 않는다" — `broker.protocol.BrokerAdapter`가 모든 브로커 구현체(Toss, 향후 KIS 등)가 따라야 할 중립 인터페이스.

## Phase / 관련 ADR
Phase 13. ADR-0019(Toss 증권 어댑터), ADR-0027(Toss 브로커 어댑터 완성), ADR-0195(외부 감사 P1 수정 — broker→Decision/Risk 직접 호출 금지 경계 실제 강제 확인).

## 핵심 인터페이스/클래스
- `BrokerAdapter`(Protocol) — `TossBrokerAdapter`
- `TossAuthClient`, `TossHttpTransport`
- `BrokerError`/`BrokerAuthError`/`BrokerTimeoutError`/`BrokerRateLimitError`/`BrokerProviderError`
- `broker.paper.us_longterm_runner.RiskCheckCallback` — broker 계층이 `risk.engine`/`decision.*`를 직접 import하지 않고도 실제 리스크 평가 결과를 받기 위한 콜백 타입(ADR-0195). 실제 콜백 구현은 `orchestration.paper_runner.build_buy_and_hold_risk_check`에 있음(broker가 아님).

## 경계
core 시스템은 이 Protocol에만 의존 — 브로커별 세부사항(Toss API 등)은 어댑터 내부에 캡슐화. **KIS 모의투자 어댑터는 사용자 액션(API 키 발급) 대기 중** — CLAUDE.md "사용자 액션 대기 항목" 참고.

**`broker/`는 `decision.agent`/`risk.sizing`/`risk.engine`/`predict.predictor`/`ai_gateway.gateway`를 절대 직접 import하지 않는다** — `tests/broker/test_broker_boundary.py`가 AST 스캔으로 실제 강제함. ADR-0195(외부 감사 P1-3)에서 `broker.paper.us_longterm_runner`가 이 경계를 위반하며 `risk.engine.PortfolioRiskEngine.assess`를 직접 호출하려던 최초 수정 시도가 이 테스트에 즉시 걸려서 잡힘 — 올바른 수정은 콜백 주입 패턴(`RiskCheckCallback`)으로 실제 리스크 평가 로직을 `orchestration` 계층으로 이동시키는 것이었음.
