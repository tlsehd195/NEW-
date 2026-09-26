---
type: entity
title: data_infra
tags:
  - module
  - phase-1
  - data
created: '2026-09-24T10:16:32.783Z'
---
## 역할
Phase 1 — 데이터 인프라. 시세/펀더멘털 등 원천 데이터의 point-in-time 안전성, 유니버스 정의, survivorship-aware 심볼 관리를 담당.

## Phase / 관련 ADR
Phase 1. ADR-0002(데이터 저장), ADR-0003(데이터 모델), ADR-0004(point-in-time 데이터), ADR-0005(데이터 프로바이더 전략), ADR-0033(실데이터 소스 결정 트리), ADR-0037(S&P500 point-in-time membership), ADR-0104(13F 기관 보유 집계), ADR-0117(US_EQUITY_NYSE 규칙기반 캘린더), ADR-0151(exchange_calendars/purgedcv/skfolio 도입 승인), ADR-0194(13F 특정 filer 추적 registry, guru_consensus_score), ADR-0207(exchange_calendars 실제 배선).

## 핵심 인터페이스/클래스
- `DatasetVersion`, `SymbolMetadata`, `UniverseDefinition`, `SurvivorshipAudit`
- `TradingCalendar`(Protocol) / `SimpleTradingCalendar` — `US_EQUITY`/`KR_EQUITY`(Phase-1 스코프 hand-picked 샘플, 프로덕션 부정확 자인정)/`US_EQUITY_NYSE`(규칙기반, 2000-2035, ADR-0117)
- `data_infra.exchange_calendars_adapter.ExchangeCalendarsTradingCalendar`(ADR-0207) — `exchange_calendars` 라이브러리 실배선. `build_xnys_calendar()`/`build_xkrx_calendar()`가 실제 한국 음력 연휴(설날/추석)·미국 연방 휴일·ad-hoc 휴장을 반영(2006-09-25~2027-09-24 지원 범위, 이 창이 좁아지면 향후 세션이 pin을 올려야 함). `scripts/run_paper_trading_cycle.py` 등 5개 실 스크립트가 `US_EQUITY_NYSE` 대신 이걸 주입하도록 교체됨 — `data_infra.calendar` 자체는 여전히 의존성 없음(이 어댑터 파일 하나만 `exchange_calendars` import).
- `TickerMembershipInterval`, `PriceDataCoverageReport`
- `TwelveDataRateLimiter` (외부 데이터 프로바이더 레이트리밋)
- `InstitutionalHoldingRecord`(13F 전체 filer 집계) / `InstitutionalFilerHoldingRecord`(13F 개별 filer, ADR-0194)
- `tracked_institutional_filers.TrackedFiler`/`TRACKED_FILERS`/`active_tracked_filers` — point-in-time-aware "guru investor" registry(ADR-0194). `tracked_from`/`tracked_until`로 특정 filer의 은퇴/펀드 청산을 과거 backtest 결과에 영향 없이 반영 (실제 사례: Scion Asset Management, 2025-11-10 SEC 등록 취소).

## 경계
다른 모든 Phase가 의존하는 기반 계층 — 여기서 point-in-time 위반(미래 데이터 누출)이 생기면 이후 전체 백테스트/학습 결과가 무효화됨.



## Macro time series (ADR-0217, 2026-09-26)

`data_infra/macro_models.py` defines `MacroObservationRecord` (one ALFRED vintage of one FRED observation) and `MACRO_SERIES_CATALOG` (rates, BAA10Y credit spread, broad dollar, payrolls/unemployment/claims, CPI, PCE, VIX, NFCI). `FredMacroProvider.fetch_series_vintages` fetches every vintage. `available_time = realtime_start + 1 day 06:00 UTC`, never the observation date, so release lags and later revisions cannot leak into backtests. Stored in `macro_observation_vintages` via `storage.macro_repository.DuckDBMacroRepository`. Nothing reads it yet; it feeds the planned portfolio-level macro filter.
