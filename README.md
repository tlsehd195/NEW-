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

**Phase 4 — Baseline Models + Persistent Storage** (설계 및 참조 구현 완료).
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
  Backtest Engine에서 실행하고 벤치마크와 비교하는 리포트 —
  `DECISION REQUIRED` 3건 여전히 미결(벤치마크 return type,
  per-decision data version, corporate-action-aware portfolio state
  재구성) — `docs/PROJECT_STATUS.md` 참조

전체 테스트: **253 passed** (Phase 1+2+3+4 합산).

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

## 개발 원칙

- Live 모드는 기본값이 `false`이며 명시적으로 활성화해야 한다.
- API key 등 secret은 코드에 저장하지 않는다. `.env`는 커밋하지 않으며
  `.env.example`에는 변수 이름만 기록한다.
- Phase 순서를 임의로 건너뛰지 않는다 (`PROJECT_MASTER_PLAN.md` §18 참조).
