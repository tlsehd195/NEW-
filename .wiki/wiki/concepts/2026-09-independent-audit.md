---
type: concept
title: 2026-09 Independent Audit 배치 시리즈
tags:
  - architecture
  - audit
  - safety
  - batch
created: '2026-09-24T10:26:14.339Z'
---
## 정의
2026-09월, 외부 독립 감사(independent audit) 보고서가 지적한 문제들을 순서대로 수정한 ADR 묶음. P1(최우선) 발견사항부터 시작해 배치(batch) A~N까지 이어짐. "fail-open"(안전장치가 조용히 무력화된 채로 프로덕션에 배선되지 않은) 패턴이 반복적으로 발견된 것이 핵심 교훈.

## 계보

### 1) 독립 P1 수정 (배치 이전)
- ADR-0177: 페이퍼 트레이딩 사이클 내 누적 gross exposure 미집행(P1-3) — 루프 중 포트폴리오 스냅샷이 한 번만 계산되고 갱신 안 됨.

### 2) 배치 A~I — 원본 독립 감사 P1/P2/P3 전항목 종료
- ADR-0178 (A): 데이터 인그레스천 매니페스트 정직성(`src/data_infra/`) — "future_dated" 관련 문서-코드 불일치.
- ADR-0179 (B): 백테스트 무결성 정직성(`src/backtest/`, `src/strategy_research/`).
- ADR-0180 (C): 브로커 라이브 fail-open 엣지(`src/broker/`, `src/broker/live/`) — 6개 관련 항목.
- ADR-0181 (D): 페이퍼 트레이딩 oversell + 재시작 amnesia 버그(`src/broker/paper/`) — 실제 재현된 버그 2건.
- ADR-0182 (E): kill-switch auto-engage 배선 — "engage 기계·트리거는 완전 구축됐지만 프로덕션에 배선 안 됨" 발견.
- ADR-0183 (F): 모니터링 프로덕션 배선 — "코드 자체는 결정론적·fail-closed·PIT-클린이지만 실험실 수준" 발견.
- ADR-0184 (G): GitHub Actions 워크플로에 `concurrency` 그룹/타임아웃 미선언.
- ADR-0185 (H): 문서-코드 불일치 18건(§6).
- ADR-0186 (I): trade journal 동일 체결시각 fill 손실(§8 회귀 테스트 목록).

### 3) 배치 J — 감사 후 추가 검토
- ADR-0187: Batch A-I가 원본 감사의 모든 P1/P2/P3 항목을 닫은 뒤, 계정 소유자가 업로드한 2차 재검토(R2/R3) 보고서의 추가 발견사항.

### 4) 배치 K~N — EXTERNAL_REPO_APPLICABILITY_REPORT.md 기반 채택
`EXTERNAL_REPO_APPLICABILITY_REPORT.md`는 이 프로젝트에는 커밋되어 있지 않은 외부 분석 문서(계정 소유자가 세션에 업로드) — 외부 GitHub 저장소 4개(llmwiki 포함)를 이 프로젝트 아키텍처 대비 분석한 리드온리 리포트.
- ADR-0188 (K): Stage-0 채택 항목들(llmwiki MCP 포함).
- ADR-0189 (L): colibri의 "Brio" 모드 — 닫힌 선택지 집합에서 확률을 읽는 엔트로피 게이트 패턴.
- ADR-0190 (M): Vibe-Trading의 alpha101 팩터 존(Kakushadze 2015) 중 10~20개 재구현.
- ADR-0191 (N): Vibe-Trading의 grounding gate 포팅(이 프로젝트의 "단일 구조적 약점"에 대한 해법으로 추천됨) — 범위 보정 + derived-value 체크.

## 왜 중요한가
이 시리즈는 "코드는 테스트를 통과하지만 프로덕션에 실제로 배선되지 않은 안전장치"라는 반복 패턴을 드러냄 — 새로운 안전 관련 기능을 추가할 때 반드시 "구현됨"과 "프로덕션에 배선됨"을 구분해서 검증해야 한다는 선례.

## 관련 엔티티
[storage](../entities/storage.md), [monitoring](../entities/monitoring.md), [broker](../entities/broker.md), [orchestration](../entities/orchestration.md), [trade_journal](../entities/trade-journal.md), [strategy_research](../entities/strategy-research.md), [ai_gateway](../entities/ai-gateway.md), [decision](../entities/decision.md)

## 관련 개념
[프로덕션 안전 및 Kill Switch](kill-switch.md)
