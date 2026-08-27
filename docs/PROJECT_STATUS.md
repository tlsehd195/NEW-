# PROJECT STATUS

> 새 Claude Code 세션은 이 파일 하나만 읽어도 현재 프로젝트가 어디까지
> 진행되었는지 파악할 수 있어야 한다. 이 파일은 각 세션 종료 시 반드시
> 최신 상태로 갱신한다.

**Last Updated:** 2026-08-27
**Updated By:** Claude Code (Session 21 — Phase 20 Real Market Data Foundation & Documentation Sync)

---

## Current Phase

**Phase 16 — Live Trading**는 `PROJECT_MASTER_PLAN.md`에 정의된 원래
마지막 공식 Phase다. **Phase 17/18/19/20은 Master Plan의 정식 Phase가
아니라, Phase 16 완료 후 실제 Live 전환 전에 발견된 안전성·검증 문제를
보완하고 실 시장 데이터 기반을 놓기 위한 사후 검증/기반 구축 작업**이며,
이 문서의 "Phase 20" 표기는 세션 추적 편의를 위한 라벨일 뿐 Master
Plan의 Phase 목록을 확장하는 것이 아니다. Phase 19가 남긴 "Phase
20/21/22 같은 후속 번호를 임의로 새로 만들지 않는다"는 원칙은 **AI가
스스로 새 Phase를 발명하지 말라**는 뜻이었다 — 이번 "Phase 20"은 사용자
본인이 직접 "PHASE 20 — REAL MARKET DATA FOUNDATION & PROJECT
DOCUMENTATION SYNC"라는 이름으로 명시적으로 지시한 작업이며, 그 원칙을
어긴 것이 아니라 정확히 그 원칙이 예외로 허용하는 경우(사람의 명시적
지시)에 해당한다. 이후 Phase 21 이상도 동일하게 사용자의 명시적 지시
없이는 스스로 만들지 않는다.

**Phase 20 — Real Market Data Foundation & Documentation Sync** (Live
Trading은 여전히 구조적으로 비활성 — Toss capability가 UNKNOWN인 한
활성화 불가, `docs/operations/PRODUCTION-READINESS-MATRIX.md` 참조)

### Completed (Session 21 — Phase 20)

- **Git/Branch Integrity 선행 확인 + Phase 19 → main fast-forward**:
  Phase 19 HEAD(`1d0003f12ad39e2807a18991bf82ab9acc7ef77d`)를
  `git rev-parse`/`git log`로 직접 재확인, baseline **1399/1399 테스트
  통과** 확인 후 `git merge --ff-only`로만 `origin/main`을 fast-forward
  (merge commit 0개, `c3abad0..1d0003f`), 이후 `claude/
  phase-20-market-data-foundation` 브랜치를 새 main HEAD에서 생성.
- **Market Data Provider 선정(ADR-0025)**: Tiingo/Alpha Vantage/Stooq/
  Financial Modeling Prep 4개 후보를 17개 기준으로 비교. 이 세션에서
  모든 후보 도메인(`api.tiingo.com` 포함)이 Toss와 동일하게
  `EGRESS_BLOCKED`임을 확인 — 모든 free-tier 사실은 Tier 2(2차 출처)로
  명시. **1순위: Tiingo**(분할/배당이 별도 필드로 분리되어 있어
  `PriceBar`/`CorporateAction` 구조와 정확히 맞음). **2순위(미구현):
  Stooq**.
- **Pilot Universe 설계**: 15개 대형주 + SPY = 16개 종목, 각각 유동성/
  장기 데이터 보유/corporate action 다양성/섹터 분산 근거 명시
  (`docs/operations/MARKET-DATA-PROVIDER.md`). GE는 실제 reverse
  split 사례가 있어 의도적으로 포함.
- **`TiingoDataProvider` 구현**(`src/data_infra/providers/`,
  `data_infra.provider.DataProvider` Protocol의 실제(비-mock)
  구현체): `fetch`/`validate`/`normalize`/`metadata` 4-메서드 정확히
  구현(`normalize`는 `IngestionRunner`가 실제로 호출하는 2-인자
  시그니처와 정확히 일치 — 최초 구현에서 키워드 인자로 잘못 만들었다가
  실제 `IngestionRunner` 호출부를 재확인해 수정). `_fetched_as_of`를
  raw record에 stamping해 `datetime.now()` 없이 point-in-time 준수.
  전용 credential 파일 `tiingo_auth.py`(AST 스캔으로 `os.environ`/
  `os.getenv` 사용을 이 파일 하나로 제한, `broker/toss/auth.py`와
  나란히 허용). `TiingoHttpTransport`(stdlib `urllib.request`,
  5xx/429→Transient, 401/403/404→Permanent 매핑) — 모든 테스트는
  stub/monkeypatch만 사용, 실제 네트워크 호출 없음(25개 테스트).
  `fetch_corporate_actions`/`normalize_corporate_actions`은
  `DataProvider` Protocol을 확장하지 않고 별도 메서드로 추가(다른
  구현체/`MockDataProvider`에 영향 없음).
- **point-in-time regression test**(`tests/integration/
  test_market_data_point_in_time.py`, 실제 `DuckDBDataRepository` +
  재시작 검증): 과거 raw bar를 저장한 뒤 나중에(effective date보다
  훨씬 이후) 발견된 분할/배당 이벤트를 등록해도 이미 저장된 raw
  close/open/volume/adjusted_close가 절대 바뀌지 않음을 증명.
  **이 테스트를 작성하며 실제 버그를 발견**: `normalize_corporate_
  actions`가 `available_time`을 이벤트의 발효일(effective_time)로
  역산해 설정하고 있었음 — "나중에 알게 된 사실이 그 발효일 시점부터
  이미 조회 가능했던 것처럼" 보이는 point-in-time 유출이었다.
  `available_time`의 스펙 정의(`PHASE-1-data-infrastructure.md` §7:
  "when OUR system could have known about it")에 따라
  `ingestion_time`으로 수정.
- **`DataQualityFramework` 확장**(`src/data_infra/quality.py`, 기존
  동작 100% 불변 — 전부 opt-in 파라미터): `ingestion_precedes_
  availability`(방금 발견한 버그와 동일 클래스를 잡는 체크,
  `PriceBar`/`CorporateAction` 양쪽에 적용) / `missing_timestamp_
  gaps`(주말 초과 gap 경고, 시장 휴장일 캘린더 없음을 명시) /
  `split_consistency`/`dividend_consistency`(등록된 corporate action을
  실제 가격 시계열과 교차검증) / `insufficient_coverage`(opt-in
  `min_expected_bars`로 데이터 부족을 조용히 PASS 처리하지 않고 명시적
  경고) — 13개 신규 테스트.
- **S&P 500 벤치마크 DECISION REQUIRED 해소(ADR-0026)**: Phase 2부터
  미결이던 PRICE_RETURN vs TOTAL_RETURN을 **TOTAL_RETURN**으로 결정
  (장기 투자 목표상 배당이 총수익의 상당 부분이므로 PRICE_RETURN만 쓰면
  벤치마크를 구조적으로 과소평가하게 됨). S&P 500 자체 데이터가 없어
  **SPY를 proxy로 채택**하되 expense ratio/tracking difference/ETF
  구조/배당 타이밍 차이를 명시적으로 문서화(무조건 "S&P 500=SPY"로
  단순화하지 않음). `backtest.total_return.build_total_return_
  benchmark_points`로 배당재투자+분할조정 지수를 실제 구현 —
  `available_time`을 시작부터 해당 시점까지의 누적 최대값으로 전파해
  "나중에 발견된 배당이 이후 모든 지수값의 available_time을 뒤로
  미룬다"는 point-in-time 보장을 새로 증명(8개 테스트). `BenchmarkEngine`
  자체는 무수정(이미 `return_type`을 그대로 읽어 보고하도록 설계되어
  있었음). **실 SPY 데이터는 여전히 없음 — 실제 벤치마크는 계속
  BENCHMARK_UNAVAILABLE.**
- **KRW/USD FX reference placeholder**(`docs/operations/
  MARKET-DATA-FX-REFERENCE.md`): 실제 환율 값은 기록하지 않음 — 이
  세션에서 모든 FX 데이터 소스가 접근 불가였고, 검증 안 된 값을
  "실시간 환율인 척" 적는 것은 지침이 명시적으로 금지하는 행위이므로
  값 없이 어떻게 채워야 하는지(source/date/value 형식)만 문서화.
  코드에서 이 값을 사용하는 곳 없음.
- **Paper Trading 실 데이터 연결 end-to-end 테스트**(`tests/
  integration/test_paper_trading_real_market_data.py`):
  `TiingoDataProvider` → `IngestionRunner` → 실제 `DuckDBDataRepository`
  → `get_bars(as_of_time=...)` → `InMemoryPaperMarketDataSource`(저장소
  조회 결과로 직접 생성, fixture 아님) → `PaperTradingSession`/
  `PaperBrokerAdapter` → `DuckDBTradeJournalRepository` →
  `monitoring.collectors.collect_broker` →
  `compute_paper_performance_report` 전체 경로가 구조적으로 연결됨을
  증명. 이 체인의 `TiingoDataProvider` 이후 모든 모듈은 완전히
  무수정(Phase 3/4/14/15/18 그대로). 상시 polling loop는 지침이 이번
  Phase의 요구사항이 아니라고 명시했으므로 구현하지 않음.
- **Risk Policy 제안값 문서화**(`docs/operations/LIVE-RISK-POLICY.md`
  확장, 결정 아님 — 제안): `max_daily_loss`는 최종 자본금의 2%(자본금
  자체는 Toss 확인 전까지 미정이므로 절대값은 아직 계산 불가),
  `max_turnover`는 3.0(`PortfolioAccounting.turnover()`가 누적 지표임을
  명시하고 주기적 재검토를 권고), `max_order_frequency_per_hour`는
  30(16종목 pilot universe 전체 리밸런싱이 실제로 최대 몇 건을
  만들어낼 수 있는지에 근거, "한 자릿수"라는 기존의 막연한 권고보다
  구체화). 세 필드의 `None` 의미론(체크 미실행, 0도 아니고 fail-closed도
  아님)을 코드 재확인을 통해 명시적으로 재서술(변경 아님). **DECISION
  REQUIRED로 유지 — 사용자 최종 승인 대기.**
- **Walk-Forward/PBO/DSR trigger 조건 문서화**(`docs/research/
  walk-forward-pbo-deflated-sharpe.md` §9 추가): 어떤 조건이 되면 DEFER를
  끝내야 하는지(스킬을 주장하는 첫 trainer 등장/복수 후보 비교/Live
  자본 대상 APPROVED 직전), 그 모델이 무엇일지(아직 존재하지 않음 — 현재
  두 trainer 모두 명시적 null-hypothesis baseline), Live 활성화 게이팅과
  어떻게 연결될지(자동 게이트가 아니라 사람의 APPROVED 결정에 첨부되는
  증거로 제안) 구체화. **분류는 Phase 19와 동일하게 DEFER 유지** — 어느
  trigger 조건도 아직 발생하지 않음.
- **Toss 공식 OpenAPI 스펙 반영(세션 중간 이벤트)**: 사용자가 대화
  도중 Toss Securities Open API OpenAPI 3.1.0 전체 스펙(JSON)을 직접
  제공. Tier 1(공식 1차 출처) 근거로 `TOSS-API-GAP-ANALYSIS.md`에 전면
  반영 — ACCOUNT_BALANCE(`GET /api/v1/accounts` +
  `GET /api/v1/buying-power`), POSITIONS, ORDER_STATUS, CANCEL_ORDER
  (`POST /api/v1/orders/{orderId}/cancel`, 응답 `orderId`가 원 주문과
  다른 신규 ID임을 확인) 4개 capability의 엔드포인트/스키마를 전부
  문서화, OAuth2 토큰 TTL을 Phase 17의 Tier 2 추정치(3600초)에서 공식
  스펙 기준 86400초로 정정. **어댑터 코드(`TossBrokerAdapter`/
  `endpoints.py`/`BrokerOrderStatus`)는 이번 Phase에서 의도적으로
  변경하지 않음** — Phase 19/20 지침이 이미 "공식 문서가 오면 분석은
  하되 구현은 별도 Phase로 제안"을 요구했기 때문. 다음 권장 Phase로
  명시.
- 기존 1399개 테스트 전부 삭제/약화 없이 유지. 신규 테스트 49개 추가
  (Tiingo transport 13 + auth 3 + provider 9 + point-in-time 2 +
  quality 13 + total_return 8 + paper-trading e2e 1 = 49) — 최종
  **1448 passed**(정확한 최종 숫자는 이 Phase 마지막 전체 실행 결과로
  재확인).

### In Progress (Session 21 — Phase 20)

README.md/PROJECT_STATUS.md/PRODUCTION-READINESS-MATRIX.md/
LIVE-TRADING-RUNBOOK.md 문서 동기화 마무리, 최종 security/leakage/
reproducibility 재검증, 최종 커밋/푸시, 최종 리포트 작성.

### Blocked (Session 21 — Phase 20)

- Live Trading 활성화 — 변경 없음, Toss capability gap이 여전히 유일한
  독립 차단 사유.
- 실 Tiingo 데이터 수집 — 이 환경에서 `api.tiingo.com` 접근 자체가
  차단되어 있어 실제 시세를 단 하나도 수집하지 못함. 이번 Phase의 모든
  `TiingoDataProvider` 테스트는 stub transport 기반.
- 실 SPY 벤치마크 데이터 — 위와 동일한 이유로 여전히 없음.

### Decision Required (Session 21 — Phase 20)

1. (Phase 17/18/19에서 이어짐) Risk policy `None` 값이 Live를 구조적으로
   차단해야 하는지 여부 — 여전히 사람의 위험 허용도 판단 필요.
2. (Phase 17에서 이어짐, 이번 Phase에서 제안값 추가) daily loss limit/
   turnover limit/order frequency 숫자값 — 이번 Phase가 근거를 갖춘
   제안값(2%/3.0/30)을 제시했으나 최종 승인은 사용자 몫.
3. (Phase 16에서 이어짐) cancel-on-shutdown 자동화 여부.
4. (Phase 18/19에서 이어짐, 채택 여부만) Walk-Forward/PBO/Deflated
   Sharpe Ratio를 향후 모델 신뢰 기준으로 채택할지 여부 — trigger
   조건은 이번 Phase에서 구체화했으나 채택 자체는 여전히 미결.
5. (신규) Toss 어댑터를 공식 스펙 기준으로 실제 구현하는 별도 Phase를
   언제 착수할지.

### Known Issues (Session 21 — Phase 20)

- 이 환경에서 시장 데이터 provider 도메인이 전부 차단되어 있어
  `TiingoDataProvider`가 실제 응답 스키마에 대해 검증되지 않았다(Tier 2
  문서 기반 구현). 실 API 키/네트워크 접근이 확보되면 최우선 재검증
  대상.
- Paper Trading 상시 실행 loop는 이번 Phase에서도 요구되지 않았으므로
  여전히 없음(DEFER, Phase 19와 동일).
- 그 외 Phase 18까지의 Known Issues 전부 유지.

### Architecture Changes (Session 21 — Phase 20)

`src/data_infra/providers/`(신규 서브패키지), `src/backtest/
total_return.py`(신규 모듈) 추가 — 둘 다 기존 모듈을 전혀 수정하지
않는 순수 추가. `DataQualityFramework.run()`에 opt-in 파라미터 2개
(`corporate_actions`, `min_expected_bars`) 추가 — 기존 호출부 동작
불변.

### Paper Trading Status (Session 21 — Phase 20)

Phase 18 PASS 유지 + 실 데이터 연결 경로가 구조적으로 연결됨을 신규
end-to-end 테스트로 증명. 상시 실행 loop는 여전히 DEFER.

### Learning Status (Session 21 — Phase 20)

변경 없음.

### Live Trading Status (Session 21 — Phase 20)

변경 없음 — 구조적으로 비활성. Toss capability gap이 유일하지만 확실한
차단 사유.

### Toss API Status (Session 21 — Phase 20)

CONFIRMED(Tier 1, 공식 OpenAPI 스펙): `POST /oauth2/token`,
`POST /api/v1/orders`(Phase 13부터), 그리고 이번 Phase에서 신규로
문서화된 ACCOUNT_BALANCE/POSITIONS/ORDER_STATUS/CANCEL_ORDER 4개
capability의 엔드포인트/스키마(`TOSS-API-GAP-ANALYSIS.md` Phase 20
addendum). **`CapabilityStatus`는 코드상 여전히 UNKNOWN — 문서화만
했고 구현은 하지 않음**(의도적, 다음 Phase로 제안).

### Last Validation (Session 21 — Phase 20)

`python -m pytest tests/ -q` — baseline **1399 passed** → 최종
**1448 passed, 0 failed, 0 skipped**(정확한 최종 숫자는 이 Phase의
마지막 전체 테스트 실행으로 재확인). 기존 테스트 전부 삭제/약화 없이
유지.

### Next Task (Session 21 — Phase 20)

1. Toss 어댑터를 공식 스펙(Tier 1, 이번 Phase에서 문서화 완료) 기준으로
   실제 구현하는 전용 Phase — README/PROJECT_STATUS 모두 이를 "다음
   권장 Phase"로 명시.
2. 실 Tiingo API 키/네트워크 접근이 확보되면: 실제 응답 스키마 검증,
   pilot universe 16종목 실제 수집, 실 SPY 데이터로 total-return
   벤치마크 실제 생성.
3. 위 Decision Required 5건에 대한 사람의 판단.

## Previous Subtask (Session 20 — Phase 19)

**Phase 19 — Production Blocker Resolution** (Live Trading은 여전히
구조적으로 비활성 — Toss capability가 UNKNOWN인 한 활성화 불가,
`docs/operations/PRODUCTION-READINESS-MATRIX.md` 참조)

### Completed (Session 20 — Phase 19)

- **Git/Branch Integrity Check 선행 수행**: Phase 18 검증된 HEAD
  (`9c2ccdd209fcd134630a6d136d0cc9fc1ad51f98`, parent
  `c1d738e843398ad62fe2ceaa5ebf90846e6428d6`)에서 직접
  `claude/phase-19-production-blocker-resolution` 브랜치 생성. 사용자가
  제시한 커밋 해시를 그대로 신뢰하지 않고 `git log`/`git rev-parse`로
  직접 재확인 — 정확히 일치함을 확인. 착수 전 **1399/1399 테스트
  통과(baseline)** 확인(추측하지 않고 실제 실행).
- **BLOCKER A (Toss API) 재조사**: 이번 세션에서 4개의 서로 다른
  `tossinvest.com` 서브도메인에 대해 직접 접근을 시도 —
  `openapi.tossinvest.com`, `developers.tossinvest.com`(Phase 13/17과
  동일하게 재확인), 그리고 이번에 새로 시도한
  `home.tossinvest.com`/`corp.tossinvest.com`(공식 회사/마케팅
  페이지) — **전부 `EGRESS_BLOCKED`**. 도메인 전체가 차단되어 있음을
  확인(특정 경로만의 문제가 아님). 웹 검색으로도 새로운 공식 출처는
  발견되지 않음(기존에 알려진 3rd-party 미러만 재등장, 승격하지 않음).
  **결론: CASE C(BLOCKED, 외부 의존성) — capability 4종
  (`ACCOUNT_BALANCE`/`POSITIONS`/`ORDER_STATUS`/`CANCEL_ORDER`) 전부
  UNKNOWN 유지, 코드 변경 없음.**
- **Risk Policy 재분석**: `max_daily_loss`/`max_turnover`/
  `max_order_frequency_per_hour`가 `None`일 때 "미집행"으로 둘지
  ("Option A") Live를 구조적으로 차단할지("Option B") 양쪽 근거를
  구체적으로 전개(`docs/operations/LIVE-RISK-POLICY.md` Phase 19
  분석 섹션). 두 옵션 모두 내적으로 일관되며 이는 위험 허용도에 대한
  정책 판단이지 정오답이 있는 기술 문제가 아님을 확인 — 여전히
  DECISION REQUIRED로 유지, 임의 결정하지 않음. 어느 쪽이든 현재는
  Toss capability gap이 독립적으로 Live를 차단하고 있어 실질적 영향
  없음도 확인.
- **Walk-Forward/PBO/Deflated Sharpe 판정**: Live Safety Gate에 반드시
  필요한지(아니오 — gate는 실행 안전성 문제, 이것은 모델 신뢰도 문제),
  기존 backtest/validation 아키텍처와 충돌하는지(아니오), 현재
  적용 대상이 있는지(없음 — 모든 trainer는 명시적으로 null-hypothesis
  baseline) 분석 후 **DEFER**로 판정(구현 불필요/시급하지 않음,
  IMPLEMENT NOW 아님, 채택 여부 자체는 이미 별도 DECISION REQUIRED로
  기록되어 있어 중복 상향하지 않음). 코드 변경 없음.
  (`docs/research/walk-forward-pbo-deflated-sharpe.md` §8)
- **Paper Trading 상시 실행 loop 조사**: `PaperMarketDataSource`의
  유일한 구현체가 `InMemoryPaperMarketDataSource`(테스트 fixture,
  수동 `register()`만 가능)뿐이며 실제 실시간/지연 시세를 공급하는
  provider가 전혀 없음을 확인 — 이는 ADR-0005가 이미 미해결로 남긴
  "실제 외부 데이터 provider 없음" 문제와 **동일한 외부 의존성 gap**임을
  발견. 즉 상시 loop를 지금 구현해도 무엇을 대상으로 advance()를
  호출할지가 없다 — 단순 `while True` + `datetime.now()` 루프는
  point-in-time 원칙(§13) 위반이므로 만들지 않음. **DEFER**로 판정,
  코드 변경 없음.
- **Benchmark 재확인**: ADR-0005 원문 재확인 — 실 데이터 provider
  선정은 여전히 전용 후속 ADR(예: ADR-0006-data-provider-selection)로
  미뤄져 있으며 라이선스/point-in-time/historical coverage 등 기준만
  정의되어 있고 실제 provider는 선정되지 않음. 가짜 벤치마크 데이터
  생성 없음, `yfinance` 등 외부 라이브러리 하드코딩 없음. 여전히
  `BENCHMARK_UNAVAILABLE` 유지 — CASE C(BLOCKED, 외부 의존성).
- **Model Safety 재확인**: 저장소 전체 AST 스캔(Phase 17/18에서 이미
  구축된 테스트) 재실행 — `CandidateModelStatus.APPROVED`/`.DEPLOYED`
  생성 경로 여전히 전무 확인(17개 테스트 통과).
- **Security 재확인**: repo-wide secret scan 재실행 — `os.environ`/
  `os.getenv` 사용이 여전히 `broker/toss/auth.py` 단 한 곳으로 제한됨
  확인. `broker/toss/auth.py`의 secret 접근 구조 확장 없음.
- **Lineage 재확인**: `decision_id`/`sizing_id`/`risk_assessment_id`가
  `ValidatedOrder.__post_init__`에서 여전히 비어있음을 구조적으로
  거부함을 확인 — 체인 끊김 없음.
- **버그**: 발견된 것 없음. 이번 세션은 실제 코드 변경을 하지 않음
  (CASE C/D 판정 — 외부 의존성 또는 사용자 정책 결정 필요, 강제로
  고칠 대상이 없음).
- 기존 1399개 테스트 전부 그대로 유지, 삭제/약화 없음. 신규 테스트
  없음(신규 코드가 없으므로).

### In Progress (Session 20 — Phase 19)

없음 — 이번 세션 작업 완료.

### Blocked (Session 20 — Phase 19)

Live Trading 활성화 — Toss `ACCOUNT_BALANCE`/`POSITIONS`/
`ORDER_STATUS`/`CANCEL_ORDER` 4개 capability가 UNKNOWN인 한 구조적으로
불가(변경 없음). 이번 세션은 4개 서브도메인에 대한 직접 접근을 재시도해
전부 `EGRESS_BLOCKED`임을 재확인했다 — 이는 이 세션이 통제할 수 없는
외부(네트워크 환경) 제약이다.

### Decision Required (Session 20 — Phase 19)

1. (Phase 18에서 이어짐) Risk policy(`max_daily_loss`/`max_turnover`/
   `max_order_frequency_per_hour`)가 `None`일 때 Live를 구조적으로
   차단할지 여부 — 이번 세션에서 양쪽 옵션을 구체적으로 분석했으나
   여전히 사람의 위험 허용도 판단이 필요(`docs/operations/
   LIVE-RISK-POLICY.md` Phase 19 분석 섹션).
2. (Phase 17에서 이어짐) daily loss limit/turnover limit/order
   frequency 숫자값 자체.
3. (Phase 16에서 이어짐) cancel-on-shutdown 자동화 여부.
4. (Phase 18에서 이어짐, 채택 여부만 — 시기는 이번 세션에서 DEFER로
   판정) Walk-Forward/PBO/Deflated Sharpe Ratio를 향후 모델 신뢰
   기준으로 채택할지 여부.

### Known Issues (Session 20 — Phase 19)

- Paper Trading 상시 실행 loop가 ADR-0005의 실 데이터 provider
  미해결 문제와 동일한 외부 의존성으로 인해 구현 불가능함을 이번
  세션에서 명확히 함(이전에는 "아직 안 만듦"으로만 기록되어 있었음).
- 변경 없음(Phase 18의 나머지 Known Issues 전부 유지).

### Architecture Changes (Session 20 — Phase 19)

없음 — 이번 세션은 코드를 전혀 수정하지 않음(순수 조사 + 문서 갱신).

### Paper Trading Status (Session 20 — Phase 19)

변경 없음(Phase 18 PASS 유지). 상시 실행 loop는 DEFER — 실 시세
provider가 없어 지금 구현해도 무엇을 대상으로 동작할지가 없음.

### Learning Status (Session 20 — Phase 19)

변경 없음 — 저장소 전체 AST 스캔 재실행으로 PASS 재확인.

### Live Trading Status (Session 20 — Phase 19)

변경 없음 — 구조적으로 비활성(`LIVE_TRADING_ENABLED=false`, 이번
세션에서 전혀 건드리지 않음). Toss capability gap이 유일하지만
확실한 차단 사유이며 이번 세션이 통제할 수 없는 외부 제약임을 재확인.

### Toss API Status (Session 20 — Phase 19)

여전히 UNKNOWN(4개 capability). 이번 세션에서 공식 도메인 4곳에 대한
직접 접근을 재시도해 전부 차단됨을 재확인(도메인 전체 차단, 경로별
문제 아님) — `docs/operations/TOSS-API-GAP-ANALYSIS.md` Phase 19
addendum 참조.

### Last Validation (Session 20 — Phase 19)

`python -m pytest tests/ -q` — baseline **1399 passed** → 최종
**1399 passed, 0 failed, 0 skipped**(코드 변경이 없었으므로 테스트
개수도 변경 없음). 기존 테스트 전부 삭제/약화 없이 유지.

### Next Task (Session 20 — Phase 19)

1. 위 Decision Required 4건에 대한 사람의 판단.
2. Toss 공식 문서에 대한 실제 네트워크 접근이 가능한 환경이 확보되면
   4개 capability 재조사 — 이것이 Live 활성화의 유일한 독립 차단
   사유다.
3. 실 데이터 provider 선정(ADR-0005 기준 후속 ADR) — 확보되면 실
   벤치마크 데이터와 Paper Trading 상시 실행 loop 둘 다 가능해진다.

## Previous Subtask (Session 19 — Phase 18)

**Phase 18 — Production Safety Follow-up + Paper Trading Validation**
(Phase 17 Production Safety Review에서 확인된 BLOCKED/PARTIAL 항목의
후속 조치)

### Completed (Session 19 — Phase 18)

- **Paper Trading Performance Report** 신규 구현
  (`src/broker/paper/performance.py`): total_return/CAGR/volatility/
  Sharpe/Sortino/Calmar/max_drawdown/turnover/transaction_cost/
  slippage/num_trades/win_rate/avg_trade_return/realized_pnl 계산.
  모든 계산 불가 상황(데이터 부족/zero variance/zero downside
  deviation/zero drawdown)을 `0.0`으로 임의 대체하지 않고 명시적
  reason 문자열(`insufficient_data`/`zero_volatility`/
  `zero_downside_deviation`/`zero_drawdown`/`not_supplied`)로 기록.
  `backtest.metrics`는 수정하지 않고(기존 Phase 2/4 동작 보존) 완전히
  새로운 병렬 모듈로 구현 (`docs/decisions/ADR-0024` 결정 1).
- **중복 accounting 시스템을 만들지 않음**: `PaperBrokerAdapter`가 이미
  내부적으로 사용 중이던 `backtest.portfolio.PortfolioAccounting`
  인스턴스를 읽기 전용 property(`adapter.accounting`, 신규 1줄
  추가)로 노출해 재사용 — 기존 동작 변화 없음, 전체 기존 Paper Trading
  테스트 그대로 통과 확인.
- **Trade Journal을 거래 경제성의 단일 권위 소스로 사용**:
  거래 건수/승률/평균 수익/실현 손익/거래비용/슬리피지는 모두
  `TradeRecord`(Phase 3, Trade Journal)에서 집계 — `PortfolioAccounting.
  closed_trades`(별도의 경쟁하는 거래 목록)는 사용하지 않음.
- **벤치마크**: `backtest.benchmark.BenchmarkEngine`을 그대로 재사용.
  이 저장소에는 실제 S&P 500(또는 어떤) 벤치마크 가격 데이터도 전혀
  없음을 재확인(ADR-0005 미해결) — 데이터가 없으면 `BenchmarkComparison.
  status="BENCHMARK_UNAVAILABLE"`을 구조적으로 반환하도록 설계, 가짜
  데이터를 생성하지 않음.
- **영속화**: `paper_performance_reports` 신규 DuckDB 테이블 + 저장소
  (`storage/paper_performance_repository.py`) — Phase 16
  `live_repository.py`와 동일한 natural-key idempotency 패턴, schema는
  순수 additive.
- **Phase 17 버그 수정 재검증**: partial fill 자연키 수정을 Live
  journal 경로(`broker.live.journal`)로도 직접 재검증(같은
  client_order_id, 다른 execution_time인 두 `BrokerOrderResponse`가
  모두 Trade Journal에 보존됨). Toss 5xx→UNKNOWN 수정을 실제
  `TossBrokerAdapter`+`LiveTradingSession` 전체 파이프라인으로
  재검증(정확히 1회 transport 호출, blind retry 없음, 2차 제출은
  세션 레벨에서 차단).
- **Live Safety Gate 9개 차원 재검증**: account/positions/order
  status/broker capability/reconciliation/model status/risk status/
  data health/monitoring health 9개 전부가 실제로 신규 주문을
  차단하는지 확인. `evaluate_safety_gate`의 실제 production 호출
  지점이 정확히 2곳(`run_startup_checks`, `LiveTradingSession.submit`)
  뿐이며 둘 다 이미 reconciliation 상태를 독립적으로 확인하고 있음을
  확인 — `SafetyGateContext`/`KillSwitchTriggerContext`에 중복 필드를
  추가하지 않고, 9개 차원 각각의 실제 집행 경로를 증명하는 regression
  test만 추가 (`docs/decisions/ADR-0024` 결정 6).
- **Paper Trading 8개 시나리오(A-H) 실제 pipeline 검증**: BUY→FILLED→
  SELL→CLOSED, partial→full fill→SELL, 현금 부족→REJECTED, 포지션
  부족→REJECTED, 중복 client_order_id→중복 없음, 브로커 장애→UNKNOWN,
  거래비용+슬리피지 반영, drawdown 발생 — 전부 Order→Fill→Journal→
  Accounting→Performance lineage 유지 확인.
- **Walk-Forward/PBO/Deflated Sharpe 연구** (구현 아님):
  `docs/research/walk-forward-pbo-deflated-sharpe.md` — 원 논문
  인용(Bailey/Borwein/López de Prado/Zhu 2015 — PBO; Bailey/López de
  Prado 2014 — Deflated Sharpe Ratio; López de Prado의 purging/embargo
  기법)과 함께 각 기법을 정의하고 현재 아키텍처 적용 지점을 문서화,
  DECISION REQUIRED로 마무리(구현 여부는 결정하지 않음).
- **신규 DECISION REQUIRED 2건**: (1) risk policy가 `None`일 때 Live를
  구조적으로 차단할지 여부(현재는 "미설정=미집행", Phase 16의 의도된
  설계) — 임의로 변경하지 않음. (2) Walk-Forward/PBO/Deflated Sharpe를
  향후 모델 신뢰 기준으로 채택할지 여부.
- 신규 테스트 다수 (성과 지표/영속화/시나리오 A-H/Live 부분체결+5xx
  회귀/Safety Gate 9차원/Monitoring 연결/boundary) — 정확한 최종
  개수는 아래 Last Validation 항목 참조.
- 기존 1345개 테스트 전부 그대로 유지, 삭제/약화 없음.

### In Progress (Session 19 — Phase 18)

없음 — 이번 세션 작업 완료.

### Blocked (Session 19 — Phase 18)

Live Trading 활성화 — Toss `ACCOUNT_BALANCE`/`POSITIONS`/
`ORDER_STATUS`/`CANCEL_ORDER` 4개 capability가 UNKNOWN인 한 구조적으로
불가 (변경 없음, Phase 13부터 지속).

### Decision Required (Session 19 — Phase 18)

1. Risk policy(`max_daily_loss`/`max_turnover`/
   `max_order_frequency_per_hour`)가 `None`일 때 Live를 구조적으로
   차단할지 여부 — `docs/operations/LIVE-RISK-POLICY.md` 참조.
2. Walk-Forward/PBO/Deflated Sharpe Ratio를 향후 모델 신뢰/Live 진입
   기준으로 채택할지 여부 — `docs/research/walk-forward-pbo-deflated-sharpe.md`
   참조.
3. (Phase 17에서 이어짐, 미해결) daily loss limit/turnover limit/order
   frequency 숫자값 자체.
4. (Phase 16에서 이어짐, 미해결) cancel-on-shutdown 자동화 여부.

### Known Issues (Session 19 — Phase 18)

- `backtest.metrics`(Phase 2, zero-fallback)와 `broker.paper.
  performance`(Phase 18, Optional+reason) 두 가지 Sharpe/Sortino/Calmar
  계산 방식이 공존 — 의도된 비대칭(ADR-0024 결정 1), 통합하지 않음.
- 실제 S&P 500 데이터가 없어 모든 Paper Performance Report의 benchmark
  상태는 당분간 `BENCHMARK_UNAVAILABLE`로 유지됨.
- `MockBrokerAdapter`의 `"account_unavailable"` 모드는 `get_positions()`에서
  빈 튜플을 반환 — "포지션 없음"과 "포지션 조회 불가"가 구분되지 않는
  기존 한계, 이번 phase에서도 수정하지 않음(Phase 17에서 이미 기록).

### Architecture Changes (Session 19 — Phase 18)

`src/broker/paper/adapter.py`(읽기 전용 property 1개 추가),
`src/storage/schema.py`/`src/storage/serialization.py`(additive),
신규 `src/broker/paper/performance.py`,
`src/storage/paper_performance_repository.py`. `backtest.metrics`/
`backtest.benchmark`/`backtest.portfolio`/`broker.live.safety_gate`/
`broker.live.kill_switch`/`broker.live.config`/`risk.config`/
`broker.toss.adapter`의 capability 보고는 전혀 수정하지 않음.

### Paper Trading Status (Session 19 — Phase 18)

주문 생애주기/Trade Journal/Experience Dataset 연결은 PASS(Phase 17).
Phase 18에서 자체 성과 리포트(Sharpe/Sortino/Calmar/drawdown/turnover/
비용/슬리피지/승률/벤치마크)를 신규 구현하고 8개 시나리오로 실제
pipeline 검증 완료 — PASS.

### Learning Status (Session 19 — Phase 18)

변경 없음 (Phase 17에서 PASS 확인, 이번 phase의 신규 코드는 learning/
evolution 패키지를 전혀 import하지 않음을 boundary test로 재확인).

### Live Trading Status (Session 19 — Phase 18)

변경 없음 — 구조적으로 비활성(`LIVE_TRADING_ENABLED=false`).
Kill switch/Reconciliation/Idempotency/환경 격리 전부 재검증 PASS(9개
차원 전부). Toss capability gap이 유일하지만 확실한 차단 사유.

### Toss API Status (Session 19 — Phase 18)

변경 없음 — 이번 phase는 신규 Toss API 조사를 시도하지 않음(공식 문서
접근 여전히 차단, 추측 구현 금지 원칙 유지). 5xx→UNKNOWN 처리(Phase
17 수정)만 전체 파이프라인으로 재검증.

### Last Validation (Session 19 — Phase 18)

`python -m pytest tests/ -q` — baseline **1345 passed** → 최종
**1399 passed, 0 failed, 0 skipped** (신규 테스트 54개). 기존 Phase
0-17 테스트는 삭제/약화 없이 전부 그대로 유지.

### Next Task (Session 19 — Phase 18)

1. 위 Decision Required 4건에 대한 사람의 판단.
2. Toss 공식 문서 실제 네트워크 접근 확보 후 4개 capability 재조사.
3. 실 벤치마크 데이터 확보(ADR-0005) 후 Paper Performance Report의
   실제 벤치마크 비교 가능하게 함.
4. Paper Trading을 실제로 운영하는 상시 실행 루프 구축.
5. Walk-Forward 검증(가장 실현 가능성 높은 첫 단계)을 향후 phase에서
   구현할지 결정.

## Previous Subtask (Session 18 — Phase 17)

**Phase 17 — Production Safety Review** (신규 기능 개발이 아닌 검증
단계. Live Trading은 여전히 구조적으로 비활성 — Toss capability가
UNKNOWN인 한 활성화 불가, `docs/operations/PRODUCTION-READINESS-MATRIX.md`
참조)

### Completed (Session 18 — Phase 17)

- 10개 검토 영역 전부 PASS/FAIL/BLOCKED/UNKNOWN/PARTIAL로 판정, 근거
  파일 명시 (`docs/specifications/PHASE-17-production-safety-review.md`
  §3).
- **실제 버그 발견 및 수정**: `TradeRecord` 자연키가 `fill.order_id`만
  사용해, 한 주문의 두 번째 이후 partial fill이 Trade Journal에서
  조용히 소실되는 문제(Phase 3부터 존재, Paper/Live 공통) — `fill.
  execution_time`을 자연키에 추가해 수정, in-memory/DuckDB 양쪽 회귀
  테스트 추가.
- Toss 5xx 응답이 `REJECTED`로 오분류되던 문제 수정 — 신규
  `BrokerProviderError`로 분리, `LiveTradingSession`은 기존 코드
  변경 없이 UNKNOWN/RECONCILIATION_REQUIRED로 정확히 처리.
- Kill Switch에 `data_health` 트리거 추가 (Phase 14의 data quality
  health가 지금까지 kill switch에 연결되어 있지 않았음).
- Phase 15/ADR-0021이 미해결로 남겨둔 `paper_account_equity`/
  `paper_pnl`/`paper_drawdown` → MonitoringEvent 연결을 완료
  (`MonitoringComponent.ACCOUNT`, additive, 신규 ADR-0023).
- Toss API 재조사 — 공식 문서 접근 여전히 차단됨을 재확인, 3rd-party
  OpenAPI 미러(`BEOKS/tossinvest-skill`)에서 `/api/v1/accounts`/
  `/api/v1/holdings`/`/api/v1/orders` 후보 endpoint 발견(Tier 2 증거,
  공식 아님 — capability는 UNKNOWN 유지).
- `docs/operations/LIVE-RISK-POLICY.md`(13개 정책 항목 분류, DECISION
  REQUIRED 3건), `docs/operations/TOSS-API-GAP-ANALYSIS.md`,
  `docs/operations/PRODUCTION-READINESS-MATRIX.md`, ADR-0023 신규 작성.
- Paper→Journal→Experience→Learning 5개 시나리오(A-E)를 실제 코드로
  추적(import 존재 확인이 아님), provenance 안전성(PAPER_TRADING→
  LIVE_TRADING 전환 불가)을 filter-bypass 방식으로도 재확인.
- Candidate→APPROVED/DEPLOYED 자동 전이 경로 없음을 `evolution`
  패키지 한정이 아닌 **저장소 전체(`src/`)** AST 스캔으로 재확인.
- 신규 테스트 81개 (Toss contract, risk policy completeness, paper
  lineage A-E, candidate boundary repo-wide, kill switch data_health,
  monitoring account, cross-cutting reconciliation/idempotency/
  failure-recovery/environment-isolation/secret-safety/runbook).
- 전체 테스트: 1264 (baseline) → **1345 passed, 0 failed**.

### In Progress

없음 — 이번 세션 작업 완료.

### Blocked

Live Trading 활성화 — Toss `ACCOUNT_BALANCE`/`POSITIONS`/
`ORDER_STATUS`/`CANCEL_ORDER` 4개 capability가 UNKNOWN인 한 구조적으로
불가 (`evaluate_safety_gate`가 실제로 차단, 추측이 아님).

### Decision Required

1. Live daily loss limit 숫자 (`LiveTradingConfig.max_daily_loss`) —
   `docs/operations/LIVE-RISK-POLICY.md` DECISION REQUIRED #1.
2. Turnover limit 숫자 (`RiskConfig.max_turnover`, 강제 로직은 이미
   존재) — 동 문서 DECISION REQUIRED #2.
3. Order frequency limit 숫자 (`LiveTradingConfig.
   max_order_frequency_per_hour`) — 동 문서 DECISION REQUIRED #3.
4. Cancel-on-shutdown 자동화 여부 (Phase 16부터 의도적으로 미결,
   ADR-0022 §8) — 이번 세션에서 재논의하지 않음, 여전히 사람 판단 대기.
5. Walk-Forward/PBO/Deflated Sharpe 검증을 향후 도입할지 여부(Phase 9
   §13/ADR-0017 §3부터 의도적 이연) — Live 활성화의 하드 세이프티
   조건은 아니나 모델 신뢰도 판단에 필요.

### Known Issues

- Paper Trading에 `backtest.metrics.PerformanceReport` 상당의 자체
  성과 리포트(Sharpe/Sortino/Calmar/변동성/turnover/benchmark 비교)가
  전혀 없음 — "Paper 수익률 > benchmark"만으로 Live 자격을 판단할 수
  없다는 원칙을 지키기 위해 반드시 필요하나 이번 세션에서 신규 구축은
  범위 밖으로 판단(향후 Phase).
- `MockBrokerAdapter`의 `"account_unavailable"` 모드에서 `get_positions()`가
  빈 튜플 `()`을 반환 — "포지션 없음(flat)"과 "포지션 조회 불가(unknown)"가
  구분되지 않는 정직하지만 불완전한 설계 (수정하지 않고 기록만 함).
- PROJECT_STATUS.md 하단의 `## In Progress`/`## Blocked`/`## Last
  Validation`/`## Not Yet Implemented`/`## Next Recommended Task`
  섹션이 Phase 9~10 시점 이후 갱신되지 않아 실제 상태와 불일치함을
  발견 — 전면 재작성은 이번 세션 범위 밖(문서 히스토리 대규모 리팩터링
  금지 원칙)으로 판단, 발견 사실만 기록.

### Architecture Changes

`src/trade_journal/repository.py`, `src/storage/trade_journal_repository.py`
(자연키 수정), `src/broker/errors.py`, `src/broker/toss/mapping.py`
(5xx 처리), `src/broker/live/kill_switch.py`(`data_health` 필드),
`src/monitoring/enums.py`/`metrics.py`/`health.py`/`collectors.py`
(`MonitoringComponent.ACCOUNT`) — 전부 additive 또는 최소 정정, 기존
Phase 0-16 동작 변경 없음(ADR-0023 상세).

### Paper Trading Status

주문 생애주기/Trade Journal/Experience Dataset 연결은 실제 코드
추적으로 PASS. 자체 성과 리포트(Sharpe 등)는 미구현 — 위 Known Issues
참조.

### Learning Status

Provenance 안전성 재확인 PASS(필터 우회 시나리오까지 포함). Candidate
model이 APPROVED/DEPLOYED로 자동 전이하는 경로 없음을 저장소 전체
스캔으로 재확인 PASS.

### Live Trading Status

구조적으로 비활성(`LIVE_TRADING_ENABLED=false` 기본값 유지, 세션 내내
변경 안 함). Kill switch/Reconciliation/Idempotency/환경 격리 전부
재검증 PASS. Toss capability gap이 유일하지만 확실한 차단 사유.

### Toss API Status

`/oauth2/token`, `POST /api/v1/orders`만 확인됨(Tier 2 증거). 계좌/
포지션/주문상태/취소는 여전히 UNKNOWN — 이번 세션 조사로 3rd-party
OpenAPI 미러에서 후보 endpoint 발견했으나 공식 문서 기준에 미달해
승격하지 않음. 상세: `docs/operations/TOSS-API-GAP-ANALYSIS.md`.

### Last Validation

`python -m pytest tests/ -q` — baseline 1264 passed → 최종 **1345
passed, 0 failed, 0 skipped**. 기존 Phase 0-16 테스트는 삭제/약화 없이
전부 그대로 유지.

### Next Task

1. 위 Decision Required 5건에 대한 사람의 판단.
2. Toss 공식 문서에 대한 실제 네트워크 접근 확보 후 Gap Analysis
   4개 capability 재조사.
3. Paper Trading 자체 성과 리포트(Sharpe/Sortino/Calmar/turnover/
   benchmark 비교) 구축 — 별도 Phase로 진행 권장.

## Previous Subtask (Session 17 — Phase 16)

Phase 16 착수 전 **Git/Branch Integrity Check를 먼저 수행**(사용자
지시) — 이번 세션은 이전 세션이 남긴 상태(`claude/phase-15-paper-trading`,
HEAD `eae021270f409b30fb36791e5518545876fa1d48` "Phase 15: Paper
Trading", working tree clean)에서 시작. `git log --oneline --graph
--decorate --all`로 단일 선형 히스토리(병합 커밋 0개) 확인,
`git merge-base HEAD origin/main`이 `origin/main` 자신의 HEAD
(`c3abad0eb9b2ba1ed4dda5ee158b448606a87d59`)를 그대로 반환(발산 없음).
Phase 16용 원격 브랜치가 아직 없어 검증된 현재 HEAD에서
`claude/phase-16-live-trading` 브랜치를 새로 생성. 착수 전 **1127/1127
테스트 통과(baseline)** 확인. 상세:
`docs/specifications/PHASE-16-live-trading.md` §0.

Master Plan §9.4(Live Trading)/§1.5(kill switch는 AI가 해제 불가)/
§12(Kill Switch & 장애/복구 규칙)/§14.4(LIVE_TRADING=false 기본값)를
재확인한 뒤 Definition of Done 충족: 명세
(`docs/specifications/PHASE-16-live-trading.md`) + ADR-0022 +
`docs/operations/LIVE-TRADING-RUNBOOK.md` + `src/broker/live/`(신규
서브패키지, Phase 0~15 소스 전혀 수정 없이 완전히 독립적인 안전 계층으로
추가) + `src/storage/live_repository.py`(신규 DuckDB 저장소 2종 — 나머지
order status/request-response 감사 기록은 Phase 13의 기존 테이블을
변경 없이 그대로 재사용) + 신규 137개 테스트 전부 통과.

**중요 발견**: `evaluate_safety_gate`가 11개 조건을 독립적으로 검사하는데,
그중 broker capability 검증 조건이 `TossBrokerAdapter.get_capabilities()`
(Phase 13이 이미 정직하게 `ACCOUNT_BALANCE`/`POSITIONS`/`ORDER_STATUS`/
`CANCEL_ORDER`를 `UNKNOWN`으로 보고하도록 구현해 둔 것)와 결합되어,
다른 모든 조건이 충족되어도 실제 Toss 계좌에 대한 Live Trading이
구조적으로 활성화될 수 없음을 실제 코드 실행으로 직접 확인함(추측이 아닌
`tests/broker/live/test_live_safety_gate.py::
TestRealTossCapabilitiesStructurallyBlockLiveTrading`과
`tests/integration/test_live_trading_lineage.py::
test_toss_real_capabilities_block_the_gate_end_to_end`로 검증). 이는
새로운 제약이 아니라 Phase 13이 이미 내린 정직한 설계 결정의 자연스러운
결과이며, ADR-0022 §2/Known Limitations에 명시.

Kill switch는 `engage_kill_switch`(deterministic 코드가 자동 호출 가능)와
`release_kill_switch`(`LiveActivationApproval` — 사람 신원/타임스탬프/
확인 문구/체크리스트 완료를 전부 요구하며 `approved_by`가 "AI"/"SYSTEM"/
"CLAUDE"이면 구조적으로 거부)로 비대칭 설계되어, `release_kill_switch`의
실제 호출 지점이 저장소 전체에서 자기 자신의 테스트 외에는 없음을 AST
스캔으로 검증(`test_live_boundary.py`). Reconciliation은 계좌/포지션/
주문상태 3종 순수 비교 함수로 구현되어 불일치·불명 상태를 절대
MATCHED로 강제 변환하지 않으며, 불일치 시 세션 전체의 신규 주문을 차단.
제출 중 예외(timeout/connection lost)는 절대 재시도하지 않고 UNKNOWN으로
기록 후 reconciliation을 요구.

## Completed (Session 17 — Phase 16)

- [x] **Git/Branch Integrity Check 선행 수행** — 위 "Current Subtask
      (Session 17 — Phase 16)" 참조. 단일 선형 lineage, 병합 커밋 0개,
      `origin/main`이 HEAD의 조상, working tree clean, Phase 16용
      원격 브랜치가 없어 검증된 HEAD에서 새로 생성 → **PASS 판정 후
      Phase 16 진행**
- [x] `PROJECT_MASTER_PLAN.md` §9.4/§1.5/§12/§13.11-13.12/§14, ADR-0001
      ~0022, Phase 8(risk.config)/Phase 13(broker, ADR-0019)/Phase
      14(monitoring)/Phase 15(paper trading) 전체 재조사.
      `TossBrokerAdapter.get_capabilities()`를 실제로 호출해
      `ACCOUNT_BALANCE`/`POSITIONS`/`ORDER_STATUS`/`CANCEL_ORDER`가
      여전히 `UNKNOWN`임을 코드로 직접 재확인(Phase 13이 남긴 미해결
      항목, 이번 Phase가 그대로 물려받음)
- [x] `docs/specifications/PHASE-16-live-trading.md` 작성(Git Integrity
      Check 결과를 §0에 포함, Activation Model/Safety Gate/Kill
      Switch/Reconciliation/Idempotency/Trade Journal/Monitoring/
      Persistence/Fail-Closed/Known Limitations 등 20개 섹션)
- [x] `docs/decisions/ADR-0022-live-trading.md` 작성(10개 결정 사항 +
      alternatives considered + consequences)
- [x] `docs/operations/LIVE-TRADING-RUNBOOK.md` 작성(prerequisites/
      startup/shutdown/reconciliation/emergency halt/kill switch/broker
      outage/unknown order/account mismatch/recovery/audit review —
      실제 secret 값은 전혀 포함하지 않음)
- [x] `src/broker/live/` 서브패키지 구현: `config.py`(LiveTradingConfig
      — `environment`가 구조적으로 `"live"` 값만 허용,
      `live_trading_enabled` 기본값 `False`), `approval.py`
      (LiveActivationApproval — `approved_by`가 "AI"/"SYSTEM"/"CLAUDE"
      이면 구조적으로 거부, 고정 confirmation phrase 요구),
      `safety_gate.py`(evaluate_safety_gate — 11개 조건 독립 검사,
      순수 함수), `kill_switch.py`(engage_kill_switch — deterministic
      코드가 자동 호출 가능/release_kill_switch — LiveActivationApproval
      필수, append-only 이력), `reconciliation.py`(compare_account/
      compare_positions/compare_order_status — 3종 순수 비교 함수,
      불일치·불명 상태를 절대 MATCHED로 강제 변환하지 않음),
      `session.py`(LiveTradingSession — gate 평가 → 제출 → 예외 시
      UNKNOWN 기록 후 재시도 없이 세션 전체 신규 주문 차단,
      run_startup_checks/run_shutdown_checks), `journal.py`
      (build_trade_record — Phase 3 TradeRecord 재사용,
      provenance=LIVE_TRADING 고정, reference_price=price로 측정
      불가능한 slippage를 정직하게 문서화), `guard.py`
      (assert_live_environment_broker_safe — Paper Trading의 guard와
      대칭, `TossBrokerAdapter` isinstance 전용 참조가 패키지 전체에서
      유일)
- [x] `src/storage/live_repository.py`(2종 DuckDB Repository) +
      `schema.py`/`serialization.py`에 `kill_switch_events`/
      `reconciliation_events`(둘 다 append-only, Phase 5/11/12/14/15
      패턴) 테이블 + 2개 시퀀스 신규 추가 — 기존 테이블 스키마 변경
      없음. Live는 Phase 15의 `paper_orders`/`paper_fills`와 달리
      자체 order/fill ledger가 불필요함(실제 broker가 항상 authoritative
      이므로 replay가 아닌 reconciliation으로 재시작 안전성 확보 —
      ADR-0022 §7)
- [x] Phase 1~15 소스코드 변경 없음 — `schema.py`/`serialization.py`에
      대한 순수 추가만 있으며(`git diff src/storage/schema.py
      src/storage/serialization.py | grep '^-'` 결과 두 파일 모두
      삭제/변경 없음으로 확인), 그 외 Phase 1~15 코드 전혀 수정하지
      않음
- [x] `tests/broker/live/`(128: config 11 + safety_gate 18 +
      kill_switch 18 + reconciliation 14 + session 16 + approval 12 +
      journal 7 + boundary 14 + leakage 10 + reproducibility 3 +
      repository_inmemory 5) + `tests/storage/test_live_repository.py`
      (7) + `tests/integration/test_live_trading_lineage.py`(2) — 신규
      137개 테스트 작성 및 전부 통과(`test_live_*` prefix로 명명해 기존
      트리 전체와 basename 충돌 없음을 사전 확인). MockBrokerAdapter만
      사용, `TossHttpTransport`는 자기 자신의 Phase 13 단위 테스트
      외에는 어디에서도 참조되지 않음(기존 Phase 13 안전망 테스트로
      재확인)
- [x] **전체 테스트 스위트 1264개 전부 통과**(Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57 + Phase6 39 + Phase7 40 + Phase8
      94 + Phase9 70 + Phase10 54 + Phase11 62 + Phase12 99 + Phase13
      133 + Phase14 135 + Phase15 91 + Phase16 137) — Phase 1~15 기존
      테스트 무손상 확인
- [x] **핵심 발견 (구조적 결과, 새 제약 아님)**: `evaluate_safety_gate`가
      broker capability 조건을 `TossBrokerAdapter.get_capabilities()`의
      실제 반환값(Phase 13이 이미 정직하게 `UNKNOWN`으로 보고하도록
      구현)과 대조하도록 설계했더니, 다른 모든 조건이 충족되어도 실제
      Toss 계좌에 대한 Live Trading이 구조적으로 활성화 불가능함을 직접
      코드 실행으로 확인(`test_live_safety_gate.py::
      TestRealTossCapabilitiesStructurallyBlockLiveTrading`,
      `test_live_trading_lineage.py::
      test_toss_real_capabilities_block_the_gate_end_to_end`). ADR-0022
      §2/Known Limitations에 명시 — Phase 13의 미해결 endpoint 확인이
      선행되어야 실제 활성화가 가능함
- [x] Boundary 검증 — `broker.live.*` 어디에도 `ai_gateway.gateway`/
      `decision.agent`/`risk.sizing`/`risk.engine`/`risk.config`/
      `data_infra.repository`/`backtest.asof`/네트워크 모듈/
      `os.environ`/`os.getenv` import가 없음을(단 `guard.py`의
      `TossBrokerAdapter` isinstance 참조는 예외) AST 스캔으로 검증,
      `LiveActivationApproval`이 `broker.live.approval` 밖 어디에서도
      생성되지 않음을 저장소 전체 AST 스캔으로 검증,
      `release_kill_switch`의 실제 호출 지점이 자기 자신의 테스트 외에는
      없음을 확인(`test_live_boundary.py`)
- [x] Fail-Closed 검증 — 11개 안전 게이트 조건 각각이 독립적으로 제출을
      차단함을 개별 테스트로 확인, kill switch 자동 트리거(broker/risk/
      monitoring health UNAVAILABLE·UNKNOWN, account/position 상태
      불명, daily loss/order frequency 설정 시에만 적용) 검증,
      reconciliation UNKNOWN·MISMATCH가 절대 MATCHED로 강제 변환되지
      않음을 확인(`test_live_safety_gate.py`, `test_live_kill_switch.py`,
      `test_live_reconciliation.py`)
- [x] Idempotency/UNKNOWN 검증 — 동일 client_order_id 재제출이 중복
      체결을 만들지 않음, 제출 중 broker 예외(timeout/connection lost)
      발생 시 재시도 없이 UNKNOWN으로 기록되고 세션 전체의 이후 제출이
      reconciliation 완료 전까지 차단됨을 확인(`test_live_session.py`)
- [x] Point-in-time/Leakage 검증 — 모든 timestamp-민감 함수(gate/kill
      switch/reconciliation/session)가 기본값 없는 필수 파라미터임을
      `inspect.signature`로 검증, `datetime.now()`/`datetime.utcnow()`
      호출이 패키지 어디에도 없음을 AST 스캔으로 확인
      (`test_live_leakage.py`)
- [x] Reproducibility 검증 — `random` import가 패키지 어디에도 없음을
      AST 스캔으로 확인, 동일 context → 동일 gate/kill-switch 판정 결과
      확인(`test_live_reproducibility.py`)
- [x] Restart Safety 검증 — kill switch 이력/reconciliation 이력이 실제
      DuckDB 카탈로그 재시작 후에도 완전히 동일하게 복구됨을 확인
      (`test_live_repository.py`)
- [x] Trade Journal/Monitoring 통합 검증 — `build_trade_record`가
      provenance=LIVE_TRADING을 항상 사용함을 확인, Phase 14의
      `collect_broker`가 `monitoring/*.py` 수정 없이 Live의
      `broker_requests`/`broker_responses`를 그대로 관찰함을 확인
      (`test_live_journal.py`, `test_live_trading_lineage.py`)
- [x] SQL join으로 lineage 증명: `risk_assessments`⋈`broker_requests`
      ⋈`trades`(3-way join, 한 DuckDB 카탈로그) + 프로세스 재시작 후
      동일 결과 확인(`test_live_trading_lineage.py`)
- [x] Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
      않다고 판단, 계속 이연
- [x] Phase 8/9/10/11/12/13/14/15 Known Issue 재검토 — Live Trading과
      무관, 변경 불필요
- [x] daily loss limit/drawdown 구체적 숫자, 자본 배분 정책, 상시 실행
      스케줄러, Toss cancel/status/account/positions endpoint 확인,
      shutdown 시 미체결 주문 자동 취소 정책, `APPROVED`/`DEPLOYED` 자동
      전이는 이번 Phase 범위에서 명시적으로 제외 — 실제 실계좌 주문은
      여전히 발생하지 않음(코드상 어떤 경로도 이를 자동으로 활성화할 수
      없음)

## Completed (Session 16 — Phase 15)

- [x] **Git/Branch Integrity Check 선행 수행** — 위 "Current Subtask
      (Session 16 — Phase 15)" 참조. 단일 선형 lineage, 병합 커밋 0개,
      `origin/main`이 HEAD의 조상, working tree clean, Phase 15용
      원격 브랜치가 없어 검증된 HEAD에서 새로 생성 → **PASS 판정 후
      Phase 15 진행**
- [x] `PROJECT_MASTER_PLAN.md` §9.4(Paper Trading), ADR-0001~0021,
      Phase 2(backtest.costs/fills/portfolio)/Phase 3(trade_journal)/
      Phase 8(risk)/Phase 13(broker)/Phase 14(monitoring) 전체 재조사.
      `backtest.fills.FillSimulator`/`backtest.costs.
      TransactionCostModel`/`SlippageModel`/`backtest.portfolio.
      PortfolioAccounting`이 이미 원하는 실행/비용/회계 로직을 정확히
      제공함을 확인해 재사용 결정(신규 병렬 로직 없음)
- [x] `docs/specifications/PHASE-15-paper-trading.md` 작성(Git Integrity
      Check 결과를 §0에 포함, Order State Machine/Execution Model/
      Slippage & Cost/Account Model/Fail-Closed/Safety Boundary/
      Idempotency & Restart/Trade Journal/Monitoring/Persistence 각
      설계, Known Limitations 포함 17개 섹션)
- [x] `docs/decisions/ADR-0021-paper-trading.md` 작성(8개 결정 사항 +
      alternatives considered + consequences)
- [x] `src/broker/paper/` 서브패키지 구현: `config.py`(PaperTradingConfig
      — `environment`가 구조적으로 `"paper"` 값만 허용), `market_data.py`
      (PaperMarketDataSource Protocol + InMemory 구현 — `available_time
      <= as_of` 필터링으로 미래 데이터 유출을 구조적으로 차단),
      `models.py`(PaperOrderRecord/PaperFillRecord — `broker.models.
      ValidatedOrder`/`backtest.fills.Fill`을 그대로 감싸는 얇은
      wrapper), `execution.py`(simulate_fill — Phase 2 FillSimulator와
      동일한 spread→slippage 수식 재사용), `adapter.py`
      (PaperBrokerAdapter — `broker.protocol.BrokerAdapter` 구현,
      `backtest.portfolio.PortfolioAccounting` 재사용, 부분 체결이
      여러 `advance_simulation` 호출에 걸쳐 누적, idempotent 재제출,
      7종 failure_mode), `repository.py`(2종 Repository Protocol +
      InMemory 구현 — order status 이력은 Phase 13의 기존
      `order_status_events`를 변경 없이 재사용), `session.py`
      (PaperTradingSession — submit/advance/cancel/capture + restore를
      통한 재시작 복구), `journal.py`(build_trade_record —
      `trade_journal.models.TradeRecord`를 그대로 재사용,
      provenance=PAPER_TRADING 고정), `guard.py`
      (assert_paper_environment_safe — `TossBrokerAdapter`에 대한
      isinstance 전용 참조가 패키지 전체에서 유일하게 존재하는 지점)
- [x] `src/storage/paper_repository.py`(2종 DuckDB Repository) +
      `schema.py`/`serialization.py`에 `paper_orders`(caller-assigned
      client_order_id 신뢰 패턴)/`paper_fills`(append-only, Phase
      5/11/12/14 패턴) 테이블 + `paper_fill_seq` 시퀀스 신규 추가 —
      기존 테이블 스키마 변경 없음. `ValidatedOrder`/`Fill` 직렬화
      함수도 이번에 신규 작성(이전 Phase는 둘 다 영속화하지 않았음)
- [x] Phase 1~14 소스코드 변경 없음 — `schema.py`/`serialization.py`에
      대한 순수 추가만 있으며(`git diff src/storage/schema.py
      src/storage/serialization.py | grep '^-'` 결과 두 파일 모두
      삭제/변경 없음으로 확인), 그 외 Phase 1~14 코드 전혀 수정하지
      않음
- [x] `tests/broker/paper/`(91: adapter 17 + accounting_invariants 12 +
      execution 8 + config 12 + boundary 10 + leakage 9 +
      reproducibility 3 + session 6 + journal 3 + repository_inmemory
      4) + `tests/storage/test_paper_repository.py`(5) +
      `tests/integration/test_paper_trading_lineage.py`(2) — 신규
      91개 테스트 작성 및 전부 통과(`test_paper_*` prefix로 명명해
      기존 트리 전체와 basename 충돌 없음을 사전 확인, `paper_helpers.py`
      는 `tests/broker/broker_helpers.py`와 나란히 위치시켜 conftest의
      sys.path 규칙을 그대로 활용)
- [x] **전체 테스트 스위트 1127개 전부 통과**(Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57 + Phase6 39 + Phase7 40 + Phase8
      94 + Phase9 70 + Phase10 54 + Phase11 62 + Phase12 99 + Phase13
      133 + Phase14 135 + Phase15 91) — Phase 1~14 기존 테스트 무손상
      확인
- [x] Boundary 검증 — `broker.paper.*` 어디에도 `broker.toss.*`/
      `decision.agent`/`risk.sizing`/`risk.engine`/`ai_gateway.gateway`/
      `data_infra.repository`/`backtest.asof` import가 없음을(단
      `guard.py`의 `TossBrokerAdapter` isinstance 참조는 예외) AST
      스캔으로 검증, `os.environ`/`os.getenv`/네트워크 모듈 import가
      패키지 어디에도 없음을 확인, `PaperTradingConfig.environment`가
      구조적으로 `"paper"`만 허용함을 확인, `assert_paper_environment_safe`
      가 `TossBrokerAdapter` 조합을 거부하고 `MockBrokerAdapter`는
      허용함을 확인(`test_paper_boundary.py`)
- [x] Fail-Closed/Accounting Invariant 검증 — 현금 부족 시 REJECTED(음수
      cash 발생 안 함), 보유 없이 매도 시 REJECTED(allow_short=False),
      max quantity/notional 초과 시 REJECTED, malformed 응답은 예외 없이
      UNKNOWN 반환, unknown_status 모드에서 실제 체결 후에도 상태 조회는
      UNKNOWN(UNKNOWN ≠ FILLED 확인), 취소/체결 완료 주문은 추가 체결
      불가, commission/spread/slippage 전부 음수 불가, slippage 방향이
      매수/매도에 일관됨을 전부 전용 테스트로 검증
      (`test_paper_adapter.py`, `test_paper_accounting_invariants.py`)
- [x] Point-in-time/Leakage 검증 — `InMemoryPaperMarketDataSource`가
      `available_time <= as_of`인 bar만 반환함을 확인, 미래 bar 등록
      이후에도 과거 시점 체결 결과가 완전히 동일함을 확인,
      `submit_order`/`advance_simulation`/`get_order_status`/
      `get_reference_bar` 전부 기본값 없는 필수 timestamp 파라미터임을
      `inspect.signature`로 검증, `datetime.now()`/`datetime.utcnow()`
      호출이 패키지 어디에도 없음을 AST 스캔으로 확인
      (`test_paper_leakage.py`)
- [x] Reproducibility 검증 — `random` import가 패키지 어디에도 없음을
      AST 스캔으로 확인, 동일 input+config → 동일 order/fill/cash/
      position 결과 확인(`test_paper_reproducibility.py`)
- [x] Restart Safety 검증 — in-memory와 실제 DuckDB 카탈로그 양쪽에서
      order submit → partial fill → advance → 재시작 →
      `PaperTradingSession.restore`로 재구성한 현금/포지션/주문 상태가
      재시작 전과 완전히 동일함을 확인, 재시작 후 동일 주문 재제출도
      중복 체결을 만들지 않음을 확인(`test_paper_session.py`,
      `test_paper_repository.py`)
- [x] Trade Journal 통합 검증 — `build_trade_record`가
      `trade_journal.models.TradeRecord`를 그대로 생성하고 provenance가
      항상 PAPER_TRADING임을 확인, `DuckDBTradeJournalRepository.
      record_trade`가 Paper fill을 변경 없이 그대로 받아들임을 확인
      (`test_paper_journal.py`, `test_paper_trading_lineage.py`)
- [x] Monitoring 통합 검증 — Phase 14의 `monitoring.collectors.
      collect_broker`/`compute_broker_metrics`가 `src/monitoring/*.py`
      수정 없이 Paper Trading의 `broker_requests`/`broker_responses`를
      그대로 관찰함을 확인. `paper_account_equity`/`paper_pnl`/
      `paper_drawdown`은 `PaperTradingSession.account_summary()`로
      값 자체는 제공하되 `MonitoringEvent`로의 실제 연결은 이번 Phase
      범위에서 의도적으로 보류(ADR-0021 §8, spec §16 Known Limitations
      에 명시 — Phase 14의 닫힌 enum을 확장할지 여부는 임의로 결정하지
      않음)
- [x] SQL join으로 lineage 증명: `risk_assessments`⋈`broker_requests`
      ⋈`paper_fills`(3-way join, 한 DuckDB 카탈로그) + 프로세스 재시작
      후 동일 결과 확인, `broker.paper.*`가 `final_target_quantity`나
      `DecisionAction`을 스스로 재생성하지 않고 Phase 8/13 산출물을
      그대로 이어받기만 함을 확인(`test_paper_trading_lineage.py`)
- [x] Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
      않다고 판단, 계속 이연
- [x] Phase 8/9/10/11/12/13/14 Known Issue 재검토 — Paper Trading과
      무관, 변경 불필요(Phase 2 §8.1의 average-cost 컨벤션을 그대로
      재사용했을 뿐, Phase 8의 average_cost proxy Known Issue는 별개의
      포트폴리오 risk-limit 계층 이슈로 영향 없음을 확인)
- [x] Live Trading(Phase 16)/실제 실계좌 주문/자동 model 승인·배포·
      재학습/상시 실행되는 Trading Engine 스케줄러/실제 alert 발송
      채널/LIMIT 주문/기본 short selling은 이번 Phase 범위에서 명시적으로
      제외 — `execution_mode=LIVE`로 가는 어떤 코드 경로도 `broker/
      paper/*.py`에 없음

## Completed (Session 15 — Phase 14)

- [x] **Git/Branch Integrity Check 선행 수행** — 위 "Current Subtask
      (Session 15 — Phase 14)" 참조. 단일 선형 lineage, 병합 커밋 0개,
      `origin/main`이 HEAD의 조상, working tree clean, Phase 14용
      원격 브랜치가 없어 검증된 HEAD에서 새로 생성 → **PASS 판정 후
      Phase 14 진행**
- [x] `PROJECT_MASTER_PLAN.md` §12(Kill Switch & 장애/복구 규칙)/§11.6
      (Drift Detection), ADR-0001~0020, Phase 1~13 전체 모델/spec, 현재
      src·tests 재조사. `RiskCheckedPosition.as_of_time`/
      `PredictionOutput.as_of_time`/`BrokerResponseRecord.responded_at`
      등 각 Phase의 point-in-time 필드를 코드로 직접 확인해
      collector별 필터링 키로 재사용
- [x] `docs/specifications/PHASE-14-monitoring.md` 작성(Git Integrity
      Check 결과를 §0에 포함, Event Model/Health Evaluation/Drift
      Detection/Alerting/Collectors/Pipeline/Persistence/Lineage/
      Point-in-Time/Reproducibility 각 설계, 15개 섹션)
- [x] `docs/decisions/ADR-0020-monitoring.md` 작성(handoff가 제안한
      번호는 ADR-0019였으나 Phase 13이 이미 사용 중이어서 ADR-0020으로
      재번호 부여 — 7개 결정 사항 + alternatives considered +
      consequences)
- [x] `src/monitoring/` 패키지 구현: `enums.py`(MonitoringComponent/
      ComponentHealthStatus/AlertSeverity/DriftStatus),
      `config.py`(MonitoringConfig — 모든 threshold 명시적 검증),
      `models.py`(MonitoringEvent/ComponentHealth/DriftResult/Alert —
      order/broker/risk-shaped 필드 없음), `metrics.py`(9개 컴포넌트별
      순수 metric 계산 함수 — 빈 입력은 항상 `None`/`0.0`, 조작된 값
      없음), `health.py`(failure-rate 기반/existence 기반/data 전용/
      pipeline aggregation 4종 evaluator — `UNKNOWN`은 어디서도
      `HEALTHY`로 강제 변환되지 않음), `drift.py`(mean shift/variance
      shift/distribution shift 3종 deterministic 검출기 —
      `min_drift_sample_count` 미만이면 항상 `UNKNOWN`), `alerts.py`
      (event/health/drift → Alert 순수 매핑, `INFO`는 alert를 발생시키지
      않음, drift 관찰은 `WARNING`만 발생 — `CRITICAL` 아님), `collectors.py`
      (컴포넌트별 9종 collector — `as_of_time` 이후 레코드를 명시적으로
      필터링한 뒤에만 metrics.py 호출, 기본값 없는 필수 파라미터),
      `pipeline.py`(assemble_pipeline_observation — worst-of aggregation
      + alert 조립), `repository.py`(4종 Repository Protocol + InMemory
      구현)
- [x] `src/storage/monitoring_repository.py`(4종 DuckDB Repository) +
      `schema.py`/`serialization.py`에 `monitoring_events`/`alerts`
      (caller-assigned id 신뢰 패턴)/`component_health_states`/
      `drift_results`(append-only, Phase 5/11/12 패턴) 테이블 + 2개
      시퀀스 신규 추가 — 기존 테이블 스키마 변경 없음. `MonitoringEvent.
      metrics`에 담기는 유일한 datetime 값(`latest_available_time`)을
      정확히 왕복 직렬화하는 `_deserialize_metrics` 헬퍼 추가
- [x] Phase 1~13 소스코드 변경 없음 — `schema.py`/`serialization.py`에
      대한 순수 추가만 있으며(`git diff src/storage/schema.py
      src/storage/serialization.py | grep '^-'` 결과 두 파일 모두
      삭제/변경 없음으로 확인), 그 외 Phase 1~13 코드 전혀 수정하지
      않음
- [x] `tests/monitoring/`(119: metrics 24 + health 20 + drift 14 +
      alerts 10 + leakage 8 + boundary 17 + reproducibility 5 +
      collectors 10 + pipeline 3 + repository_inmemory 8) +
      `tests/storage/test_monitoring_repository.py`(14) +
      `tests/integration/test_monitoring_lineage.py`(2) — 신규 135개
      테스트 작성 및 전부 통과(`test_monitoring_*` prefix로 명명해 기존
      트리 전체와 basename 충돌 없음을 사전 확인 —
      `test_monitoring_repository.py`가 `tests/monitoring/`과
      `tests/storage/`에 동시에 필요해 in-memory 버전을
      `test_monitoring_repository_inmemory.py`로 명명해 충돌 회피)
- [x] **전체 테스트 스위트 1036개 전부 통과**(Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57 + Phase6 39 + Phase7 40 + Phase8
      94 + Phase9 70 + Phase10 54 + Phase11 62 + Phase12 99 + Phase13
      133 + Phase14 135) — Phase 1~13 기존 테스트 무손상 확인
- [x] Boundary 검증 — `monitoring.*` 어디에도 `decision.agent`/
      `risk.sizing`/`risk.engine`/`ai_gateway.gateway`/`broker.pipeline`/
      `broker.validation`/`broker.protocol` import가 없음을 AST
      스캔으로 검증, `.APPROVED`/`.DEPLOYED` attribute 참조가 패키지
      어디에도 없음을 AST 스캔으로 검증(단, `learning.enums.
      CandidateModelStatus`를 읽기 전용으로 카운팅하는 것은 허용 —
      "절대 쓰지 않는다"가 경계이지 "절대 읽지 않는다"가 아님),
      `MonitoringEvent`/`ComponentHealth`/`DriftResult`/`Alert` 4종
      dataclass 모두 order/risk-shaped 필드가 없고 `frozen=True`임을
      reflection으로 검증(`test_monitoring_boundary.py`)
- [x] Fail-Closed 검증 — 빈 입력/샘플 부족/non-finite 값/degenerate
      baseline 전부 `UNKNOWN` 반환, pipeline aggregation에서 `UNKNOWN`이
      `DEGRADED`보다 우선순위가 높아 다수의 `HEALTHY`에 의해 묻히지
      않음을 확인(`test_monitoring_health.py`)
- [x] Point-in-time/Leakage 검증 — 9개 collector 전부 `as_of_time`이
      기본값 없는 필수 파라미터임을 `inspect.signature`로 검증, 미래
      레코드를 추가해도 과거 시점 collector 결과(`metrics`/`health.
      status`)가 완전히 동일함을 확인, `datetime.now()`/`datetime.
      utcnow()` 호출이 패키지 어디에도 없음을 AST 스캔으로 확인
      (`test_monitoring_leakage.py`)
- [x] Reproducibility 검증 — `random` import가 패키지 어디에도 없음을
      AST 스캔으로 확인, 동일 input+config+as_of_time → 동일 health/
      drift/event 결과 확인(`test_monitoring_reproducibility.py`)
- [x] SQL join으로 lineage 증명: `risk_assessments`⋈`monitoring_events`
      (DuckDB `json_extract`로 `source_record_ids` 배열 내 `risk_id`
      존재 여부 join) + 프로세스 재시작 후 동일 결과 확인, 여러 컴포넌트가
      하나의 `assemble_pipeline_observation` 호출로 합쳐져 mixed
      health(Risk=HEALTHY, Broker=UNAVAILABLE → pipeline=UNAVAILABLE)를
      정확히 반영함을 확인(`test_monitoring_lineage.py`)
- [x] Persistence 검증 — 4개 테이블 모두 저장→재조회 round-trip, 동일
      id 재기록 시 idempotent, 프로세스 재시작 후 데이터 보존 확인
      (`test_monitoring_repository.py`)
- [x] Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
      않다고 판단, 계속 이연
- [x] Phase 8/9/10/11/12/13 Known Issue 재검토 — Monitoring과 무관,
      변경 불필요
- [x] Paper Trading(Phase 15)/Live Trading(Phase 16)/실제 trading
      execution/자동 model 승인·배포·재학습/실제 alert 발송 채널
      (email/Slack 등)/Alert 승인·해제(acknowledgement/resolution)
      워크플로우는 이번 Phase 범위에서 명시적으로 제외 — 어떤 주문도
      생성/제출되지 않고, 어떤 model도 자동으로 APPROVED/DEPLOYED되지
      않음

## Completed (Session 14 — Phase 13)

- [x] **Git/Branch Integrity Check 선행 수행** — 위 "Previous Subtask
      (Session 14 — Phase 13)" 참조. 단일 선형 lineage, 병합 커밋 0개,
      HEAD가 정확히 Phase 12 커밋임을 확인, working tree clean, Phase
      13용 원격 브랜치가 없어 검증된 HEAD에서 새로 생성 → **PASS 판정
      후 Phase 13 진행**
- [x] `PROJECT_MASTER_PLAN.md` §9(Order System & Broker Layer),
      ADR-0001~0019, Phase 7/8 spec(Decision/Position Sizing/Risk),
      `.env.example`, 현재 src·tests 재조사. 특히 `risk.models.
      RiskCheckedPosition.final_target_quantity`가 절대 목표치(delta
      아님)임을 코드로 직접 확인 — Broker Adapter 계층이 현재 포지션과
      비교해 실제 매매 수량/방향을 계산하는 유일한 지점이 되어야 함을
      확인
- [x] 실제 Toss증권 Open API 리서치 수행(WebSearch/WebFetch) —
      `developers.tossinvest.com`/`openapi.tossinvest.com`이 이 환경의
      network egress proxy에 차단되어 OpenAPI spec을 직접 읽지 못함,
      대신 공식 GA 발표(2026-08-13)와 제3자 기술 문서로 간접 확인:
      base URL(`https://openapi.tossinvest.com`), OAuth2 Client
      Credentials 인증(`POST /oauth2/token`), 주문 생성
      (`POST /api/v1/orders`, 확인된 request 필드:
      clientOrderId/symbol/side/orderType/quantity/price), 주문 상태
      값(PENDING/PARTIAL_FILLED/PENDING_CANCEL/PENDING_REPLACE 및
      FILLED/CANCELED/REJECTED/REPLACED), 에러 코드 예시
      (expired-token/insufficient-buying-power/order-hours-closed/
      price-out-of-range), **공개 sandbox 환경 없음**(실계좌 1주로
      테스트 권장). 취소/상태조회/계좌조회 엔드포인트의 정확한 경로는
      확인하지 못해 추측하지 않고 `CapabilityStatus.UNKNOWN`/
      `BrokerCapabilityError`로 처리(상세: spec §8 "Toss API
      Verification")
- [x] `docs/specifications/PHASE-13-toss-securities-adapter.md` 작성
      (Git Integrity Check 결과를 §0에 포함, Order Validation/Capability
      Model/Live Execution Safety/Fail-Closed/Toss API
      Verification/Secrets/Persistence/Lineage/Point-in-Time 각 설계,
      out-of-scope 항목과 근거, 16개 섹션)
- [x] `docs/decisions/ADR-0019-toss-securities-adapter.md` 작성 (8개
      결정 사항 + alternatives considered + consequences)
- [x] `src/broker/` 패키지 구현: `enums.py`(BrokerExecutionMode —
      OFFLINE 기본값/BrokerOrderStatus — Toss 실제 상태값만 사용,
      placeholder 목록 아님/OrderValidationStatus/BrokerCapability/
      CapabilityStatus), `config.py`(BrokerConfig — credential은 참조
      이름만, LIVE 전환에 `live_opt_in=True` 별도 필수), `errors.py`
      (BrokerError 계층, ai_gateway.provider와 동일 패턴),
      `models.py`(ValidatedOrder — 유일한 권위 있는 주문 의도,
      client_order_id는 결정적/BrokerOrderResponse — UNKNOWN 상태
      구조적 지원/BrokerAccountSnapshot·BrokerPosition — available=False
      시 값 필드 보유 금지를 `__post_init__`이 강제), `capabilities.py`
      (build_capabilities — 선언 안 된 capability는 항상 UNKNOWN),
      `validation.py`(build_validated_order — RiskCheckedPosition의
      절대 목표치와 현재 수량 차이로 side/quantity 계산하는 유일한
      지점, compute_client_order_id — 결정적 idempotency key),
      `transport.py`(BrokerTransport Protocol + MockTransport),
      `protocol.py`(BrokerAdapter Protocol), `mock.py`
      (MockBrokerAdapter — 유일하게 이 저장소 코드가 실제로 호출하는
      adapter, accepted/rejected/partial_fill/filled/cancelled/
      unavailable/account_unavailable/status_unknown 전부 결정적
      시뮬레이션), `repository.py`(3종 Repository Protocol + InMemory
      구현), `pipeline.py`(submit_validated_order — 모든 operation의
      일관된 audit log 기록), `auth.py`(ResolvedCredentials 타입만,
      해석 로직 없음)
- [x] `src/broker/toss/` 서브패키지: `endpoints.py`(CONFIRMED/
      UNCONFIRMED 명시적 구분, 확인 못한 경로는 `None`), `auth.py`
      (TossAuthClient — 이 패키지에서 `os.environ`/`os.getenv`를
      사용하는 유일한 파일), `mapping.py`(map_order_status — 인식 못한
      문자열은 항상 UNKNOWN, parse_order_response — 401/429/malformed/
      unrecognized 전부 안전 처리), `transport.py`(TossHttpTransport —
      stdlib `urllib`만 사용, 신규 의존성 없음, 응답 헤더를 안전한
      allowlist로만 필터링), `adapter.py`(TossBrokerAdapter — 생성자가
      execution_mode==LIVE 강제, submit_order만 확인된 엔드포인트로
      실제 구현, 나머지는 BrokerCapabilityError)
- [x] `src/storage/broker_repository.py`(3종 DuckDB Repository) +
      `schema.py`/`serialization.py`에 `broker_requests`(decision_id/
      sizing_id/risk_assessment_id를 실제 컬럼으로 노출, SQL join
      가능)/`broker_responses`(Phase 5~8/12의 caller-assigned id 신뢰
      패턴)/`order_status_events`(append-only, Phase 5/12 패턴) 테이블
      + `order_status_event_seq` 시퀀스 신규 추가 — 기존 테이블 스키마
      변경 없음
- [x] Phase 1~12 소스코드 변경 없음 — `schema.py`/`serialization.py`에
      대한 순수 추가만 있으며(`git diff src/storage/schema.py
      src/storage/serialization.py | grep '^-'` 결과 두 파일 모두
      삭제/변경 없음으로 확인), 그 외 Phase 1~12 코드 전혀 수정하지
      않음. `.env.example`은 이미 예약되어 있던 TOSS_API_KEY/
      TOSS_API_SECRET/TOSS_ACCOUNT_ID 주석을 리서치 결과로 보강만 함
      (변수명 자체는 변경 없음)
- [x] `tests/broker/`(125: models 16 + validation 19 + mock 15 +
      boundary 12 + secret_safety 5 + reproducibility 3 + point_in_time
      4 + backtest_integration 8 + toss/mapping 19 + toss/transport 7 +
      toss/auth 8 + toss/adapter 9) + `tests/storage/
      test_broker_repository.py`(6) + `tests/integration/
      test_broker_lineage.py`(2) — 신규 133개 테스트 작성 및 전부 통과
      (`test_broker_*`/`test_toss_*` prefix로 명명해 기존 트리 전체와
      basename 충돌 없음을 사전 확인)
- [x] **전체 테스트 스위트 901개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57 + Phase6 39 + Phase7 40 + Phase8
      94 + Phase9 70 + Phase10 54 + Phase11 62 + Phase12 99 + Phase13
      133) — Phase 1~12 기존 테스트 무손상 확인
- [x] Order/Broker 경계 검증 — `broker.*` 어디에도 `decision.agent`/
      `risk.sizing`/`risk.engine`/`predict.predictor`/`ai_gateway.
      gateway`/`learning.enums` import가 없음을 AST 스캔으로 검증,
      `ValidatedOrder`가 `broker/validation.py` 밖에서 직접 생성되지
      않음을 AST 스캔으로 검증, BrokerAdapter Protocol에 decide/
      size_position/approve/deploy 등 금지 메서드 없음을 reflection으로
      검증(`test_broker_boundary.py`)
- [x] Live Execution Safety 검증 — `BrokerConfig` 기본값 OFFLINE,
      `execution_mode=LIVE`만으로는 생성 실패(ValueError), `live_opt_in`
      이 패키지 어디서도 동적으로 계산되지 않고 항상 리터럴 값으로만
      전달됨을 AST 스캔으로 검증, `TossBrokerAdapter` 생성자가
      execution_mode==LIVE를 강제함을 검증
      (`test_broker_boundary.py::TestExecutionModeGuard`,
      `test_toss_adapter.py::TestConstructionRequiresLiveMode`)
- [x] Secret 안전성 검증 — `os.environ`/`os.getenv`가
      `broker/toss/auth.py` 단 한 곳에서만 존재함을 패키지 전체 AST
      스캔으로 검증, 주문 제출 후 영속화된 request/response payload
      어디에도 실제 secret 문자열이나 `Bearer ` 헤더가 없음을 확인,
      `BrokerAuthError` 예외 메시지가 credential 값을 echo하지 않음을
      확인(`test_broker_secret_safety.py`)
- [x] Fail-Closed 검증 — broker unavailable/timeout/auth 실패/rate
      limit/malformed response/인식 못한 order status 문자열/미검증
      capability/무효 주문/중복 client_order_id/계좌·포지션 조회
      불가(0원·포지션 없음으로 추정하지 않고 available=False 보존) 전부
      전용 테스트로 검증
- [x] Point-in-time — `submit_order`/`get_order_status`가 `requested_at`
      /`as_of`를 기본값 없는 필수 인자로 요구, `data_infra.repository`/
      `backtest.asof` import가 `broker/*.py` 어디에도 없음(AST 스캔),
      `ValidatedOrder.as_of_time`이 `RiskCheckedPosition.as_of_time`을
      그대로 복사(wall-clock 호출 없음)함을 확인
      (`test_broker_point_in_time.py`)
- [x] Backtest 연동 — `src/backtest/`가 `broker.*`를 전혀 import하지
      않음을 AST 스캔으로 확인, `MockBrokerAdapter`가 accepted/
      rejected/partially filled/filled/cancelled/timeout(unavailable)
      전부를 결정적으로 시뮬레이션함을 확인, 이 저장소의 어떤 테스트
      파일도 `TossHttpTransport`(실제 네트워크 가능한 유일한
      구현체)를 자기 자신의 전용 테스트 외에는 참조하지 않음을 확인
      (`test_broker_backtest_integration.py`)
- [x] Reproducibility — `random` import/`datetime.now()`/`datetime.
      utcnow()` 호출이 `src/broker/**/*.py` 어디에도 없음을 AST
      스캔으로 확인, 동일 RiskCheckedPosition+current_quantity →
      동일 client_order_id+동일 MockBroker 응답 검증
      (`test_broker_reproducibility.py`)
- [x] SQL join으로 lineage 증명: `decision_outputs`⋈`risk_assessments`
      ⋈`broker_requests`⋈`broker_responses`⋈`order_status_events`
      (5-way join, 한 DuckDB 카탈로그) + 프로세스 재시작 후 동일 결과
      확인, `broker.*`가 DecisionAction이나 target quantity를 스스로
      재생성하지 않고 Phase 7/8 산출물을 그대로 이어받기만 함을 확인
      (`test_broker_lineage.py`)
- [x] Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
      않다고 판단, 계속 이연
- [x] Phase 8/9/10/11/12 Known Issue 재검토 — Broker Adapter와 무관,
      변경 불필요
- [x] Paper Trading(Phase 15)/Live Trading(Phase 16)/Monitoring(Phase
      14)/AI 기반 실행/Learning Engine 변경/Model Registry 완성/Model
      APPROVED·DEPLOYED 자동 전이/Portfolio optimizer/새 prediction
      model·decision strategy/risk limit 재설계/broker의 직접 position
      sizing·risk 판단은 이번 Phase 범위에서 명시적으로 제외 — 실제
      실계좌 주문도 여전히 발생하지 않음(코드상 가능하더라도 이 저장소
      자체는 절대 호출하지 않음)

## Completed (Session 13 — Phase 12)

- [x] **Git/Branch Integrity Check 선행 수행** — 위 "Current Subtask
      (Session 13 — Phase 12)" 참조. 단일 선형 lineage, 병합 커밋 0개,
      두 참조 커밋 모두 조상 확인, working tree clean, Phase 12용
      원격 브랜치가 없어 검증된 HEAD에서 새로 생성 → **PASS 판정 후
      Phase 12 진행**
- [x] `PROJECT_MASTER_PLAN.md` §5/§6/§18.4, ADR-0001~0018, Phase
      1~11 spec, 현재 src·tests 재조사. 특히 `.env.example`이 Phase
      0에서 이미 `AI_PROVIDER_A_API_KEY`/`AI_PROVIDER_B_API_KEY`/
      `AI_PROVIDER_C_API_KEY`(값 없이 이름만, 주석 처리)를 예약해
      두었음을 확인하고 `ProviderConfig.api_key_reference`가 그 예약된
      이름 관례를 그대로 따르도록 설계
- [x] `docs/specifications/PHASE-12-ai-gateway.md` 작성 (Git Integrity
      Check 결과를 §0에 포함, Pipeline/Data Model/Fail-Closed
      Behavior/Provider Versioning/Point-in-Time/Secrets/Persistence/
      Reproducibility/Lineage 각 설계, out-of-scope 항목과 근거, 13개
      섹션)
- [x] `docs/decisions/ADR-0018-ai-gateway.md` 작성 (7개 결정 사항 +
      alternatives considered + consequences)
- [x] `src/ai_gateway/` 패키지 구현: `enums.py`(TaskTier/
      ProviderHealthStatus/BillingStatus/RequestStatus — UNKNOWN
      health·billing은 UNAVAILABLE·PAID_DETECTED와 동일하게 보수적
      처리), `config.py`(ProviderConfig — `api_key_reference`는 env var
      이름만, 실제 값 아님/GatewayConfig — provider별 priority·
      supported_tiers에서 tier별 후보 목록을 직접 파생, 별도 유지되는
      2차 라우팅 테이블 없음), `models.py`(AIRequest — payload는 caller가
      이미 조립한 opaque 문자열, 이 모듈이 데이터를 직접 조회하지
      않음/AIResponse — SUCCESS↔content 있음, 그 외 상태↔error_reason
      있음을 `__post_init__`이 구조적으로 강제/ProviderQuotaState —
      Phase 5 RegimeObservation과 동일한 append-only 관측 기록 패턴),
      `provider.py`(AIProviderAdapter Protocol + `MockProviderAdapter`
      — 유일한 구현체, 결정적·오프라인, `failure_mode`로 §6.5의 모든
      시나리오를 시뮬레이션), `validation.py`(schema/JSON/missing-field/
      invalid-value 검증), `task_router.py`(tier별 provider 후보 목록),
      `quota_manager.py`(QuotaManager — is_available이 모든 라우팅
      결정의 단일 fail-closed 게이트, 모든 상태 변화는 append-only
      관측), `provider_selector.py`(TaskRouter+QuotaManager를 결합해
      "지금 실제로 쓸 수 있는" 후보만 필터), `gateway.py`(AIGateway —
      단일 진입점, provider rotation/failover/retry/검증/실패 매핑
      오케스트레이션), `repository.py`(3종 Repository Protocol +
      InMemory 구현)
- [x] `src/storage/ai_gateway_repository.py`(3종 DuckDB Repository) +
      `schema.py`/`serialization.py`에 `ai_requests`/`ai_responses`
      (caller-assigned id 신뢰, Phase 5~8의 decisions/predictions
      패턴)/`provider_quota_states`(append-only, Phase 5/10/11 패턴)
      테이블 + `provider_quota_state_seq` 시퀀스 신규 추가 — 기존 테이블
      스키마 변경 없음
- [x] Phase 1~11 소스코드 변경 없음 — `schema.py`/`serialization.py`에
      대한 순수 추가만 있으며(`git diff src/storage/schema.py
      src/storage/serialization.py | grep '^-'` 결과 두 파일 모두
      삭제/변경 없음으로 확인), 그 외 Phase 1~11 코드 전혀 수정하지 않음
- [x] `tests/ai_gateway/`(87: provider 15 + validation 9 + quota_manager
      15 + task_router 6 + provider_selector 4 + gateway 13 + boundary
      14 + reproducibility 3 + point_in_time 3 + secret_safety 5) +
      `tests/storage/test_ai_gateway_repository.py`(10) +
      `tests/integration/test_ai_gateway_lineage.py`(2) — 신규 99개
      테스트 작성 및 전부 통과 (처음부터 `test_ai_gateway_*` prefix로
      명명해 기존 트리 전체와 basename 충돌 없음을 사전 확인)
- [x] **전체 테스트 스위트 768개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57 + Phase6 39 + Phase7 40 + Phase8
      94 + Phase9 70 + Phase10 54 + Phase11 62 + Phase12 99) — Phase
      1~11 기존 테스트 무손상 확인
- [x] Master Plan §6.5가 요구하는 5개 시나리오(Provider A 정상 성공;
      A quota exhausted → B로 자동 전환; A/B/C 모두 실패 → NO AI
      CALL/안전한 실패; A quota reset → 우선순위 A로 복귀; billing
      감지 → 해당 provider disabled)를 각각 전용 테스트로 검증
      (`test_ai_gateway_gateway.py::TestFailoverRotation`)
- [x] 구조적 경계 검증 — `ai_gateway/*.py` 어디에도 order/broker/risk
      필드 없음, `trade_journal.enums.DecisionAction`/`learning.enums.
      CandidateModelStatus` import 자체가 없음(reflection + AST 스캔,
      `test_ai_gateway_boundary.py`), `AIGateway.generate` 시그니처에
      broker/risk/data_repository 파라미터 없음
- [x] Fail-closed 검증 — provider 미초기화/disabled/UNKNOWN health·
      billing은 항상 unavailable, quota 소진은 명시적 reset_time 도래
      전까지 계속 unavailable, billing PAID_DETECTED는 quota reset과
      무관하게 계속 unavailable(`test_ai_gateway_quota_manager.py`)
- [x] Secret 안전성 검증 — `api_key_reference`가 실제 키가 아닌 env var
      이름임(Phase 0의 `.env.example` 예약 이름과 일치), `os.environ`/
      `os.getenv` 호출이 패키지 어디에도 없음, 영속화된 request/
      response/quota-state payload 어디에도 비밀처럼 보이는 문자열이
      없음을 검증(`test_ai_gateway_secret_safety.py`)
- [x] Point-in-time — `AIGateway.generate`가 `as_of`를 기본값 없는
      필수 키워드 인자로 요구, `data_infra.repository`/`backtest.asof`
      import가 패키지 어디에도 없음(AST 스캔), `AIRequest.payload`가
      단순 opaque 문자열이라 이 모듈이 직접 데이터를 조회할 방법이
      구조적으로 없음(`test_ai_gateway_point_in_time.py`)
- [x] Reproducibility — `random` import/`datetime.now()`/`datetime.
      utcnow()` 호출이 `src/ai_gateway/*.py` 어디에도 없음을 AST
      스캔으로 확인, 동일 request+동일 as_of → 동일 응답 검증
      (`test_ai_gateway_reproducibility.py`)
- [x] SQL join으로 lineage 증명: `ai_requests`⋈`ai_responses` +
      `provider_quota_states`(provider_id로 상관) 한 DuckDB 카탈로그,
      전부 실패한(all-exhausted) 안전한 실패 응답도 정상적으로
      영속화·재조회됨을 확인, 프로세스 재시작 후 동일 결과 확인
      (`test_ai_gateway_lineage.py`)
- [x] `stream()`은 Master Plan §5.1이 명시한 인터페이스 완전성을 위해
      `MockProviderAdapter`에 구현했으나 `AIGateway`는 호출하지 않음
      (스트리밍 소비자가 이번 Phase에 없음, ADR-0018 §6)
- [x] `ai_requests`/`ai_responses`는 Phase 9/11과 달리 storage-level
      id 재발급을 하지 않고 caller-assigned id를 그대로 신뢰(Phase
      5~8의 decisions/predictions 패턴과 동일) — request/response
      로그는 content-addressed artifact가 아니므로 Phase 9/11의 dedup
      수정이 그대로 적용되지 않는다고 판단(ADR-0018 §4, Known Issue로
      명시)
- [x] Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
      않다고 판단, 계속 이연
- [x] Phase 8/9/10/11 Known Issue 재검토 — AI Gateway와 무관, 변경 불필요
- [x] Toss Securities Adapter(Phase 13)/Monitoring(Phase 14)/Paper
      Trading(Phase 15)/Live Trading(Phase 16)은 이번 Phase 범위에서
      명시적으로 제외 — 실제 브로커/주문/실거래도 여전히 구현하지 않음,
      Model Evolution의 APPROVED/DEPLOYED 자동 전이 경로도 여전히 없음

## Completed (Session 12 — Phase 11)

- [x] **Git/Branch Integrity Check 선행 수행** — 위 "Current Subtask
      (Session 12 — Phase 11)" 참조. 지정 작업 브랜치가 실제 Phase 0~10
      lineage를 갖고 있지 않음을 발견하고, 손실 없이 올바른 lineage로
      브랜치 포인터를 재설정 → **PASS 판정 후 Phase 11 진행**
- [x] `PROJECT_MASTER_PLAN.md`/ADR-0001~0016/Phase 1~10 spec/현재
      src·tests 재조사. 특히 `learning.enums.CandidateModelStatus`가
      `BACKTESTED`/`VALIDATED`/`OOS_TESTED`/`PAPER_TESTED`/`APPROVED`/
      `DEPLOYED`를 이미 예약해 두었지만 Phase 9는 `CANDIDATE`만 생산했고
      Phase 10도 이 상태들을 전혀 다루지 않았음을 코드로 직접 확인,
      Phase 3의 `AlternativeOutcome`/`CounterfactualRecord.alternatives`가
      임의 길이 tuple로 이미 설계돼 있어 candidate 기반 alternative를
      추가하는 데 스키마 변경이 필요 없음을 확인
- [x] `docs/specifications/PHASE-11-model-evolution.md` 작성 (Git
      Integrity Check 결과를 §0에 포함, Candidate Generation/Comparison/
      Status Transition/Lineage/Counterfactual/Persistence/Point-in-Time/
      Reproducibility 각 설계, out-of-scope 항목과 근거, 13개 섹션)
- [x] `docs/decisions/ADR-0017-model-evolution.md` 작성 (8개 결정 사항 +
      alternatives considered + consequences, 자체 발견 버그 1건의 근본
      원인과 수정 근거 상세 기록)
- [x] `src/evolution/` 패키지 구현: `config.py`(`PromotionConfig` —
      모든 threshold configuration으로 분리), `models.py`
      (`ModelStatusTransition` — append-only 감사 기록,
      `ModelLineageRecord` — generation은 항상 parent로부터 파생,
      `CandidateComparison` — winner/is_better/champion 필드 없음),
      `criteria.py`(`next_status`/`evaluate_transition` — CANDIDATE→
      BACKTESTED→VALIDATED→OOS_TESTED만 매핑된 닫힌 dict, APPROVED/
      DEPLOYED로의 전이 경로 구조적으로 없음, 실패한 전이도 항상
      auditable record로 반환), `lineage.py`(`derive_lineage` —
      generation을 parent에서만 파생), `comparison.py`
      (`compare_candidates` — 동일 dataset만 비교 허용, 단일 명시적
      metric으로 ranking만 제공), `trainer.py`
      (`TrailingWindowMeanTrainer` — Phase 9 `CandidateTrainer` Protocol을
      구조적으로 구현하는 두 번째 candidate 생성기, ML 의존성 없음),
      `counterfactual.py`(`compute_candidate_decision_alternative` —
      decision_time에 고정된 `AsOfDataView`로 실제 Predictor+
      DecisionAgent를 실행해 대안 결정을 얻고, Phase 3/10의 hold/cash
      counterfactual 계산을 그대로 재사용해 수익률로 변환;
      `append_candidate_alternatives` — 기존 CounterfactualRecord에
      추가만 함), `repository.py`(2종 Repository Protocol + InMemory
      구현), `pipeline.py`(`generate_candidate_batch`/
      `evaluate_candidate_batch` — 여러 candidate 생성/평가 오케스트레이션)
- [x] `src/storage/evolution_repository.py`(`DuckDBModelStatusTransitionRepository`/
      `DuckDBModelLineageRepository`) + `schema.py`/`serialization.py`에
      `model_status_transitions`(append-only)/`model_lineage`
      (candidate_id PK) 테이블 + `model_status_transition_seq` 시퀀스
      신규 추가 — 기존 테이블 스키마 변경 없음
- [x] Phase 1~10 소스코드 변경 없음 — `schema.py`/`serialization.py`에
      대한 순수 추가만 있으며(`git diff src/storage/schema.py
      src/storage/serialization.py | grep '^-'` 결과 두 파일 모두
      삭제/변경 없음으로 확인), 그 외 Phase 1~10 코드 전혀 수정하지 않음
- [x] `tests/evolution/`(54: trainer 7 + comparison 7 + criteria 12 +
      lineage 9 + counterfactual 5 + point_in_time 2 + boundary 7 +
      reproducibility 3 — 합 52, 아래 storage/integration 별도) +
      `tests/storage/test_evolution_repository.py`(8) +
      `tests/integration/test_evolution_lineage.py`(2) — 신규 62개
      테스트 작성 및 전부 통과 (파일명 충돌 방지를 위해 처음부터
      `test_evolution_*`/`test_model_lineage.py`로 명명, 기존 트리 전체와
      basename 충돌 없음을 사전 확인)
- [x] **전체 테스트 스위트 669개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57 + Phase6 39 + Phase7 40 + Phase8
      94 + Phase9 70 + Phase10 54 + Phase11 62) — Phase 1~10 기존 테스트
      무손상 확인
- [x] `next_status`가 `APPROVED`/`DEPLOYED`로 매핑되는 경로가 구조적으로
      전혀 없음을 dict 리터럴 직접 검사 + `evolution/*.py` 전체 AST
      스캔(`.APPROVED`/`.DEPLOYED` attribute reference 탐지)으로 검증
      (`test_evolution_boundary.py`), Position Sizing/Risk/Order/Broker
      관련 필드·메서드가 `evolution.*` 어디에도 없음을 reflection으로
      검증
- [x] 미래 데이터 유출 방지 — `evaluate_transition`/`compare_candidates`/
      `derive_lineage`는 `DataRepository` 호출을 아예 하지 않음(새로운
      leakage surface 없음), `compute_candidate_decision_alternative`는
      `AsOfDataView`의 clock을 `decision_time`에 고정(코드 소스 자체를
      검사해 `evaluation_time`으로 고정되지 않았음을 확인)하고, 이후
      `decision_time` 이후 대량의 미래 bar를 추가해도 동일한 가상 결정이
      나옴을 회귀 테스트로 검증(`test_evolution_point_in_time.py`)
- [x] Reproducibility — `random` import/`datetime.now()`/`datetime.
      utcnow()` 호출이 `src/evolution/*.py` 어디에도 없음을 AST 스캔으로
      확인, generate→evaluate→compare→validate→lineage 전체 체인을 동일
      입력으로 두 번 실행해 완전히 동일한 결과를 얻음을 검증
      (`test_evolution_reproducibility.py`)
- [x] **자체 발견 및 수정한 버그 1건**: `ModelLineageRecord`를 서로 다른
      `CandidateTrainer` 인스턴스(각자 독립적인 in-process id
      allocator를 가짐, "CAND-000001"부터 매 인스턴스 재시작)로 만든
      candidate들로 구성할 때, 두 candidate가 우연히 같은 candidate_id를
      가지면 child lineage가 자기 자신을 부모로 참조하는
      self-referential 레코드가 조용히 만들어질 수 있는 문제 발견 (Phase
      9가 ADR-0015 §6에서 storage 계층에 대해 이미 고친 것과 동일한
      클래스의 버그가 in-memory 계층에서도 재현됨) — `ModelLineageRecord.
      __post_init__`에 `candidate_id != parent_candidate_id` 구조적
      검증을 추가해 수정, `test_model_lineage.py::
      TestModelLineageRecordValidation::test_self_referential_parent_rejected`가
      전용 regression test (ADR-0017 §7)
- [x] SQL join으로 lineage 증명: `candidate_models`⋈`training_datasets`⋈
      `evaluation_results`⋈`model_lineage`⋈`model_status_transitions`
      (5-way join, 한 DuckDB 카탈로그) + 프로세스 재시작 후 동일 결과
      확인(`test_evolution_lineage.py::TestModelEvolutionLineageEndToEnd`)
- [x] `alternative_action_1`/`alternative_action_2`(Phase 3가 Phase
      11로 이연, ADR-0016 §7이 재확인) 구현: 실제 Predictor+
      DecisionAgent를 decision_time에 실행해 얻은 가상 결정을 Phase
      3/10의 기존 hold/cash 수익률 계산을 그대로 재사용해
      `AlternativeOutcome`으로 변환하고, `append_candidate_alternatives`로
      Phase 10의 `(HOLD, CASH)` 레코드에 추가만 함(Phase 3/10 소스 수정
      없음). 확장된 레코드가 `trade_journal.experience.
      build_experience_records`를 통해 Learning Engine Experience
      Dataset으로 코드 변경 없이 그대로 연결됨을 통합 테스트로 확인
      (`test_evolution_lineage.py::TestCandidateAlternativeComposesWithPhase10Counterfactual`)
- [x] PBO/Deflated Sharpe/Walk-Forward validation은 계속 미구현 —
      검증되지 않은 방식으로 과최적화 강건성을 주장하는 위험을 피하기
      위해 Phase 9(§13)에 이어 이번 Phase에서도 명시적으로 이연
      (ADR-0017 §3)
- [x] Model Registry는 "Phase 12+ 별도 서비스/UI"가 아니라 Phase 9가 이미
      "Model Registry completion (Phase 11)"로 범위를 지정한 persisted
      lineage/version/status 데이터(`ModelLineageRecord`+
      `ModelStatusTransition`+기존 `CandidateModelArtifact`/
      `EvaluationResult`)로 해석하여 구현 (ADR-0017 §5, DECISION REQUIRED
      아님 — 근거를 문서로 남김)
- [x] Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
      않다고 판단, 계속 이연
- [x] Phase 8/9/10 Known Issue 재검토 — Model Evolution과 무관, 변경
      불필요
- [x] AI Gateway(Phase 12)/Toss Securities Adapter(Phase 13)/
      Monitoring(Phase 14)/Paper Trading(Phase 15)/Live Trading(Phase
      16)은 이번 Phase 범위에서 명시적으로 제외 — 실제 AI API 호출,
      주문/브로커/실제 매매도 여전히 구현하지 않음, candidate가 자동으로
      APPROVED/DEPLOYED되는 경로도 여전히 없음

## Completed (Session 11 — Phase 10)

- [x] **Git/Branch Integrity Check 선행 수행 — 이전 세션 PASS를 재사용
      하지 않고 처음부터 재검증**(사용자 지시) — 위 "Current Subtask"
      참조. 지정 작업 브랜치가 실제 Phase 0~9 lineage를 갖고 있지 않음을
      발견하고, 손실 없이(지정 브랜치의 유일한 커밋이 실제 lineage의
      조상이었음을 확인 후) 올바른 lineage로 브랜치 포인터를 재설정 →
      **PASS 판정 후 Phase 10 진행**
- [x] Master Plan §33(Counterfactual Analysis)/§34(Performance
      Attribution)/ADR-0001~0015/Phase 1~9 spec/현재 src·tests 재조사.
      특히 Phase 3가 이미 `AlternativeOutcome`/`CounterfactualRecord`/
      `AttributionResult`를 "미래 Phase가 채울 예약 필드" 형태로 정의해
      두었고, `compute_hold_counterfactual`/`compute_execution_attribution`
      두 함수만 실제로 값을 계산했으며, `TradeJournalRepository`가 이미
      `CounterfactualRecord`(HOLD 하나만 담은 상태로) 영속화를 완전히
      지원하지만 `AttributionResult`는 어떤 저장소도 가진 적이 없음을
      코드로 직접 확인
- [x] `docs/specifications/PHASE-10-counterfactual-attribution.md` 작성
      (Git Integrity Check 결과를 §0에 포함, Counterfactual/Attribution
      각 설계, out-of-scope 항목과 그 근거, point-in-time/provenance/
      reproducibility/구조적 경계/lineage/persistence, 12개 섹션)
- [x] `docs/decisions/ADR-0016-counterfactual-attribution.md` 작성 (8개
      결정 사항 + alternatives considered + consequences)
- [x] `src/counterfactual/` 패키지 구현: `counterfactual.py`
      (`compute_cash_counterfactual` — 시스템 전역에 이미 존재하는
      risk_free_rate=0.0 관행을 그대로 따름, `build_counterfactual_record`
      — Phase 3의 HOLD + 신규 CASH를 `trade_journal.models.
      CounterfactualRecord`(수정 없이 재사용)로 조립, `compute_
      counterfactual_advantage` — 선택한 행동과 대안의 실현 수익률 차이),
      `attribution.py`(`compute_market_attribution` — Phase 2
      `BenchmarkResult`/`PerformanceReport`의 기존 필드를 그대로 읽음,
      `compute_selection_attribution` — `cumulative_return - market -
      execution` 정확한 residual, `build_attribution_result` — 세
      요소가 `market + selection + execution == cumulative_return`을
      항상 정확히 만족하도록 구성, `sector`/`factor`/`timing`은 계속
      예약), `repository.py`(`AttributionRepository` Protocol +
      `InMemoryAttributionRepository` — Phase 3의 `PostTradeAnalysis`/
      `CounterfactualRecord`와 동일한 append/latest-wins 규율),
      `pipeline.py`(`run_counterfactual_analysis`/
      `run_counterfactual_analysis_for_provenance` — Trade Journal을
      읽어 조립만 하고 저장은 호출자 책임, Learning Engine의 `pipeline.py`
      설계를 그대로 따름)
- [x] `src/storage/counterfactual_repository.py`
      (`DuckDBAttributionRepository`) + `schema.py`/`serialization.py`에
      `attribution_results` 테이블(Phase 3의 기존 `post_trade_analyses`/
      `counterfactuals`와 동일한 append-history 구조) + `attribution_seq`
      시퀀스 신규 추가 — 기존 테이블 스키마 변경 없음.
      `CounterfactualRecord`용 신규 테이블은 만들지 않음(Phase 3의
      `counterfactuals` 테이블이 이미 임의 길이의 `alternatives` tuple을
      완전히 round-trip함을 기존 코드 확인으로 검증한 뒤 그대로 재사용)
- [x] Phase 1~9 소스코드 변경 없음 — `schema.py`/`serialization.py`에
      대한 순수 추가만 있으며(`git diff src/storage/schema.py
      src/storage/serialization.py | grep '^-'` 결과 두 파일 모두
      삭제/변경 없음으로 확인), 그 외 Phase 1~9 코드 전혀 수정하지 않음
- [x] `tests/counterfactual/`(46: cash counterfactual 7 + counterfactual
      record/advantage 7 + attribution 11 + attribution repository 6 +
      point-in-time 5 + provenance 2 + reproducibility 4 + boundary 4)
      + `tests/storage/test_attribution_repository.py`(6) +
      `tests/integration/`(2: counterfactual pipeline + attribution
      lineage) — 신규 54개 테스트 작성 및 전부 통과 (파일명 충돌 4건
      발견 및 즉시 수정 — `test_reproducibility.py`→
      `test_counterfactual_reproducibility.py`(tests/learning/와 충돌),
      `test_boundary.py`→`test_counterfactual_boundary.py`
      (tests/predict/와 충돌), `test_point_in_time.py`→
      `test_counterfactual_point_in_time.py`(tests/regime/와 충돌),
      `test_provenance.py`→`test_counterfactual_provenance.py`
      (tests/trade_journal/와 충돌); 자체 파일명 충돌 1건도 함께 수정
      — `tests/counterfactual/test_attribution_repository.py`→
      `test_counterfactual_attribution_repository.py`
      (tests/storage/test_attribution_repository.py와 충돌))
- [x] **전체 테스트 스위트 607개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57 + Phase6 39 + Phase7 40 + Phase8
      94 + Phase9 70 + Phase10 54) — Phase 1~9 기존 테스트 무손상 확인
- [x] `market + selection + execution == cumulative_return` reconciliation
      항등식을 hand-built fixture(`test_attribution.py::
      TestAttributionReconciles`)와 실제 `BacktestEngine` 실행 결과
      (`test_attribution_lineage.py`) 양쪽에서 직접 검증
- [x] `CounterfactualRecord`가 Phase 3의 기존 `build_experience_records`
      (수정 없음)를 통해 Learning Engine Experience Dataset으로 자동
      연결됨을 실제 baseline backtest 통합 테스트로 확인
      (`test_counterfactual_pipeline.py` — counterfactual 기록 전에는
      `counterfactual_results`가 전부 `None`, HOLD+CASH 기록 후에는
      자동으로 2개 alternative를 담음)
- [x] 미래 데이터 유출 방지 — CASH counterfactual은 `DataRepository`
      호출을 아예 하지 않음(AST 스캔으로 검증), HOLD counterfactual은
      Phase 3의 기존 `as_of_time` guard를 변경 없이 재사용, `build_
      attribution_result`는 이미 계산된 `ExperimentRecord` 필드만 읽고
      어떤 데이터 저장소도 호출하지 않음 — Phase 10은 새로운
      `AsOfDataView`/`DataRepository` 호출 지점을 하나도 추가하지 않음
      (`test_counterfactual_point_in_time.py`)
- [x] Reproducibility — `random` import/`datetime.now()`/`datetime.
      utcnow()` 호출이 `src/counterfactual/*.py` 어디에도 없음을 AST
      스캔으로 확인, 동일 입력 → 동일 출력 검증
      (`test_counterfactual_reproducibility.py`)
- [x] 구조적 경계 — `CounterfactualRecord`/`AttributionResult` 어디에도
      order/broker/risk-shaped 필드가 없고(Phase 3 원본 타입 그대로),
      `src/counterfactual/*.py` 어디서도 `Order`/`RiskCheckedPosition`/
      `PositionSizingResult`를 생성하거나 `CandidateModelStatus.
      APPROVED`/`DEPLOYED`를 참조하지 않음을 AST 스캔 + reflection으로
      검증(`test_counterfactual_boundary.py`)
- [x] Provenance — 서로 다른 `TradeProvenance`의 거래를 함께 처리해도
      한 거래의 counterfactual이 다른 거래의 데이터를 빌려오지 않음을
      확인(`test_counterfactual_provenance.py`)
- [x] `alternative_action_1`/`alternative_action_2`(다른 모델/전략의
      가상 의사결정과 비교)는 Phase 3가 이미 "그 대안이 실제로 존재하고
      실행 가능해야 한다"는 이유로 Phase 11(Model Evolution)로 지정해둔
      것을 재검토 후 그대로 유지 — Phase 6~9로 여러 Predictor 구현체와
      작동하는 DecisionAgent가 생겼지만, 대안 모델의 전체 의사결정
      파이프라인을 별도로 실행/등록/추적하는 것은 Model Evolution의
      고유 범위라고 판단해 구현하지 않음(ADR-0016 §7)
- [x] `timing`/`sector`/`factor` attribution은 계속 `None`으로 예약 —
      `sector`/`factor`는 Phase 8부터 이어지는 데이터 소스 부재(변경
      없음), `timing`은 Brinson-Fachler류 가중치 기반 분해가 필요한데
      검증되지 않은 모델로 그럴듯하지만 틀릴 수 있는 숫자를 만드는 위험이
      "정확한 값을 계산할 수 없으면 추정값을 사실처럼 저장하지 않는다"는
      프로젝트 원칙에 어긋난다고 판단해 이연(ADR-0016 §5-6)
- [x] `PostTradeAnalysis`의 나머지 예약 필드(`prediction_error`,
      `timing_error`, `risk_estimation_error`, `regime_error`,
      `signal_error` — Master Plan §32)는 Counterfactual(§33)/
      Attribution(§34)과는 별개의 master plan 섹션이라고 판단해 이번
      Phase 범위에서 명시적으로 제외
- [x] Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
      않다고 판단, 계속 이연
- [x] Phase 8/9 Known Issue 재검토 — Counterfactual/Attribution과 무관,
      변경 불필요
- [x] Model Evolution 완성(Phase 11)/AI Gateway(Phase 12)/Toss
      Securities Adapter(Phase 13)/Monitoring(Phase 14)/Paper
      Trading(Phase 15)/Live Trading(Phase 16)은 이번 Phase 범위에서
      명시적으로 제외 — 실제 AI API 호출, 주문/브로커/실제 매매도 여전히
      구현하지 않음

## Completed (Session 10 — Phase 9)

- [x] **Git/Branch Integrity Check 선행 수행 — 이전 세션 PASS를 재사용
      하지 않고 현재 HEAD(`05ac338`, Phase 8)부터 처음부터 재검증**
      (사용자 지시) — Phase 0~8 커밋 10개를 `merge-base --is-ancestor`로
      개별 조상 확인, 병합 커밋 0개, `origin/main` 대비 main에만 있는
      커밋 0개/현재 branch에만 있는 커밋 10개, `wvscwe` 대비 wvscwe에만
      있는 커밋 0개/현재 branch에만 있는 커밋 5개, working tree clean,
      483/483 테스트 통과 확인 → **PASS 판정 후 Phase 9 착수**
- [x] Master Plan/ADR-0001~0014/Phase 1~8 spec/현재 src·tests 재조사
      (충돌 없음 확인, DECISION REQUIRED 신규 발생 없음). 특히 Phase 3
      `ExperienceRecord`/`build_experience_records`, Phase 4
      `ExperienceRepository`/`ExperimentRepository`, Phase 5~8의
      `attach_*_context` 비침습적 lineage 패턴을 실제 코드로 재확인
- [x] `docs/specifications/PHASE-9-learning-engine.md` 작성 (Git
      Integrity Check 결과를 §0에 포함, Data Cleaning 규칙 표, Labeling/
      Dataset/Training/Evaluation 각 섹션, fail-closed 원칙, lineage,
      persistence, 25개 섹션)
- [x] `docs/decisions/ADR-0015-learning-engine.md` 작성 (8개 결정 사항 +
      alternatives considered + consequences, 자체 발견 버그 2건의 근본
      원인과 수정 근거 상세 기록)
- [x] `src/learning/` 패키지 구현: `enums.py`(SampleStatus/SplitName/
      CandidateModelStatus — 7개 상태 전부 예약하되 이번 Phase는
      CANDIDATE만 실제 생산), `config.py`(DataCleaningConfig/LabelConfig/
      SplitConfig/SamplingConfig/TrainingDatasetConfig — 모든 threshold를
      configuration으로 분리), `models.py`(CleaningResult/LabeledSample/
      TrainingDataset/CandidateModelArtifact/EvaluationResult/
      LearningExperimentRecord — order/broker/risk-mutation 필드
      구조적으로 없음), `cleaning.py`(DataCleaner — provenance mismatch/
      duplicate/NaN·Inf/missing decision/no realized outcome을 모두
      개별 상태로 기록, 절대 조용히 제거하지 않음), `labeling.py`
      (Labeler — TradeRecord.realized_return만 label 소스로 사용, feature
      cutoff와 label start를 별도 필드로 유지), `dataset.py`
      (build_training_dataset — as_of_cutoff로 미래 experience를 cleaning
      이전에 배제, 시간순 non-shuffled 3-way split, 실제 sample 내용을
      해싱하는 content-hash dataset_version), `trainer.py`
      (CandidateTrainer Protocol + MeanRewardBaselineTrainer — TRAIN
      split 평균만 사용, VALIDATION/TEST 접근 안 함, 항상
      CandidateModelStatus.CANDIDATE만 생산), `evaluation.py`
      (Evaluator — MAE/MSE + baseline 비교, candidate_is_better 필드
      없음), `experiment.py`(LearningExperimentTracker), `repository.py`
      (4종 Repository Protocol + InMemory 구현), `pipeline.py`
      (run_learning_pipeline — 전체 체인 오케스트레이션, 저장은 호출자
      책임으로 분리)
- [x] `src/storage/learning_repository.py`(4종 DuckDB Repository) +
      `schema.py`/`serialization.py`에 `training_datasets`/
      `candidate_models`/`evaluation_results`/`learning_experiments`
      테이블 + 4개 시퀀스 신규 추가 — 기존 테이블 스키마 변경 없음
- [x] Phase 1~8 소스코드 변경 없음(Phase 9는 `schema.py`/
      `serialization.py`에 대한 순수 추가만 있으며 — `git diff | grep
      '^-'` 결과 두 파일 모두 삭제/변경 없음으로 확인 — 그 외
      Phase 1~8 코드 전혀 수정하지 않음)
- [x] `tests/learning/`(58: cleaning 11 + labeling 5 + dataset 8 +
      trainer 6 + evaluation 5 + leakage 7 + provenance 4 + boundary 7 +
      reproducibility 5) + `tests/storage/test_learning_repository.py`(8)
      + `tests/integration/test_learning_pipeline.py`(4) — 신규 70개
      테스트 작성 및 전부 통과 (파일명 충돌 발견 및 즉시 수정 —
      `test_provenance.py` → `test_learning_provenance.py`,
      `tests/trade_journal/test_provenance.py`와 충돌)
- [x] **자체 발견 및 수정한 버그 2건**: (1) `TrainingDataset.dataset_version`이
      `source_experience_ids` 목록만 해싱해 서로 다른 두 journal(예:
      두 개의 독립적 백테스트 실행)이 우연히 동일한 trade_id/experience_id
      시퀀스("TRD-000001" 등, journal마다 로컬로 재시작)를 갖게 되면
      실제 내용이 다른데도 동일한 dataset_version이 나오는 문제 — 실제
      sample content((trade_id, label_value, sample_as_of_time) 튜플)를
      해싱하도록 수정, `data_infra.versioning.compute_data_version`의
      진짜 content-hash 계약을 충족(ADR-0015 §5). (2) 위와 동일한 원인으로
      `TrainingDataset.dataset_id`/`CandidateModelArtifact.candidate_id`
      등이 in-process allocator("...-000001"부터 매 호출 재시작)에서
      나와 독립적인 두 pipeline 실행이 저장소 PRIMARY KEY에서 충돌하는
      문제 — Phase 4가 `experience_id_seq`로 이미 확립한 동일 해결
      패턴(자연키로 dedup 확인 후 storage-level 시퀀스로 새 id 발급)을
      4개 Learning 저장소 모두에 적용(ADR-0015 §6).
      `tests/integration/test_learning_pipeline.py::
      test_two_independent_pipeline_runs_do_not_collide_in_storage`가
      전용 regression test
- [x] Data Cleaning이 샘플을 절대 조용히 버리지 않음을 개별 테스트로
      검증(`test_cleaning.py::TestNeverSilentlyDrops`), Labeling이
      feature_cutoff_time/label_start_time을 구조적으로 분리 유지함을
      검증
- [x] 미래 데이터 유출 방지 회귀 테스트 신규 작성 — 동일한 as_of_cutoff로
      재구축한 dataset이 이후 journal에 미래 experience가 추가되어도
      dataset_version/splits/label 값 전부 동일함을 확인
      (`test_learning_point_in_time.py`)
- [x] Provenance 분리를 `build_training_dataset`의 `provenance` 파라미터에
      기본값을 두지 않는 구조로 강제(`inspect.signature`로 검증) —
      HISTORICAL_SIMULATION/PAPER_TRADING/LIVE_TRADING이 절대 섞이지
      않음을 확인(`test_learning_provenance.py`)
- [x] Learning Engine이 order/broker/risk-limit mutation을 만들지 않고,
      CandidateModelStatus.APPROVED/DEPLOYED를 생성하는 코드 경로가
      전혀 없음을 reflection + AST 스캔으로 검증(`test_learning_boundary.py`)
- [x] Reproducibility 검증 — 동일 dataset/config/seed → 동일 결과, 그리고
      `learning/*.py` 어디에도 `random` 모듈을 import하지 않음을 AST로
      확인(`test_reproducibility.py`)
- [x] **전체 테스트 스위트 553개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57 + Phase6 39 + Phase7 40 + Phase8
      94 + Phase9 70) — Phase 1~8 기존 테스트 무손상 확인
- [x] `LearningExperimentRecord`는 `backtest.experiment.ExperimentRecord`를
      재사용하지 않고 새 타입으로 설계(재사용 시도했으나 backtest-특화
      필드(PerformanceReport, transaction_cost_config 등)가 training
      run과 맞지 않아 기각, ADR-0015 §1) — 대신 저장 패턴(단일 DuckDB
      카탈로그, id-allocating tracker, natural-key idempotency)은 그대로
      재사용, 중복된 새 Experiment 시스템을 만들지 않음
- [x] Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
      않다고 판단, 계속 이연 (임의 결정하지 않음)
- [x] Phase 8의 Known Issue 3건(average_cost proxy/sector-factor 데이터
      부재/turnover 호출자 의존) 재검토 — Learning Engine과 무관, 변경
      불필요
- [x] Counterfactual Analysis/Performance Attribution(Phase 10)/Model
      Evolution/Model Registry 완성(Phase 11)/AI Gateway(Phase 12)/Toss
      Securities Adapter(Phase 13)/Monitoring(Phase 14)/Paper
      Trading(Phase 15)/Live Trading(Phase 16)은 이번 Phase 범위에서
      명시적으로 제외 (지시대로) — 실제 AI API 호출, 학습 결과의 자동
      Live 적용도 여전히 구현하지 않음

## Completed (Session 9 — Phase 8)

- [x] **Git/Branch Integrity Check 선행 수행 — 이전 세션 PASS를 재사용
      하지 않고 현재 HEAD(`6a1c937`, Phase 7)부터 처음부터 재검증**
      (사용자 지시) — Phase 0~7 커밋 10개를 `merge-base --is-ancestor`로
      개별 조상 확인, 병합 커밋 0개, `origin/main` 대비 main에만 있는
      커밋 0개/현재 branch에만 있는 커밋 9개, `wvscwe` 대비 wvscwe에만
      있는 커밋 0개/현재 branch에만 있는 커밋 4개, working tree clean,
      389/389 테스트 통과 확인 → **PASS 판정 후 Phase 8 착수**
- [x] Master Plan/ADR-0001~0013/Phase 1~7 spec/현재 src·tests 재조사
      (충돌 없음 확인, DECISION REQUIRED 신규 발생 없음)
- [x] `docs/specifications/PHASE-8-position-sizing-and-risk.md` 작성
      (Git Integrity Check 결과를 §0에 포함, Position Sizing/Risk Engine
      규칙 표, 구조적 경계, fail-closed 원칙, lineage, persistence,
      21개 섹션)
- [x] `docs/decisions/ADR-0014-position-sizing-and-risk-engine.md` 작성
      (12개 결정 사항 + alternatives considered + consequences)
- [x] `src/risk/` 패키지 구현: `enums.py`(RiskCheckStatus — PASS/REDUCE/
      REJECT/UNKNOWN, Position Sizing과 Risk Engine이 공유하는 단일
      vocabulary), `config.py`(PositionSizingConfig/RiskConfig — 모든
      threshold configuration으로 분리, 잘못된 값은 `__post_init__`에서
      즉시 raise), `models.py`(PositionSizingResult/PortfolioRiskState/
      RiskCheckedPosition — order_id/broker_order/execution_price 등
      order-shaped 필드 구조적으로 없음, target_weight/target_quantity는
      이 계층의 권한 있는 출력), `sizing.py`(PositionSizer Protocol +
      DeterministicPositionSizer — confidence/volatility/liquidity/cash/
      risk_budget을 반영한 14단계 순차 fail-closed 규칙, decision의
      target_weight_hint는 어디서도 읽지 않음), `engine.py`
      (PortfolioRiskEngine Protocol + DeterministicPortfolioRiskEngine —
      cash_minimum→single_position_limit→gross_exposure→concentration→
      drawdown→portfolio_volatility→turnover→liquidity 순서로 재검사하는
      최종 권한자, "설정 안 됨(None)"과 "설정됐지만 데이터 없음(fail-closed
      REJECT)"을 명확히 구분), `repository.py`(PositionSizingRepository/
      RiskRepository Protocol + InMemory 구현, natural-key idempotency,
      as_of 조회)
- [x] `src/storage/risk_repository.py`(DuckDBPositionSizingRepository/
      DuckDBRiskRepository) + `schema.py`/`serialization.py`에
      `position_sizing_results`/`risk_assessments` 테이블(risk_state는
      별도 테이블 없이 payload_json에 내장)/직렬화 추가 — 기존 테이블
      스키마 변경 없음
- [x] Phase 1~7 소스코드 변경 없음(Phase 8은 `schema.py`/
      `serialization.py`에 대한 순수 추가만 있으며 — `git diff | grep
      '^-'` 결과 두 파일 모두 삭제/변경 없음으로 확인 — 그 외
      Phase 1~7 코드 전혀 수정하지 않음)
- [x] `tests/risk/`(85: sizing 36 + engine 31 + boundary 11 + leakage 3 +
      backtest-integration 4) + `tests/storage/test_risk_repository.py`(6)
      + `tests/integration/test_risk_lineage.py`(3) — 신규 94개 테스트
      작성 및 전부 통과 (파일명 충돌 없음 — 처음부터 phase-prefixed
      이름으로 작성)
- [x] **전체 테스트 스위트 483개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57 + Phase6 39 + Phase7 40 +
      Phase8 94) — Phase 1~7 기존 테스트 무손상 확인
- [x] Position Sizing/Risk Engine이 주문/브로커/execution_price를 만들지
      않음을 구조적으로 검증 (`test_risk_boundary.py` —
      `dataclasses.fields()`/`inspect.signature()` reflection으로 확인,
      Phase 7 DecisionOutput/BaselineRuleDecisionAgent의 경계도 재확인)
- [x] 미래 데이터 유출 방지 회귀 테스트 (`test_risk_point_in_time.py`)
      — 미래 bar 추가 후 과거 시점 Sizing/Risk 결과를 Regime→Prediction→
      Decision→Sizing→Risk 전체 체인으로 재계산해도 결과가 동일함을 확인
- [x] Phase 5 Regime → Phase 6 Prediction → Phase 7 Decision → Phase 8
      Sizing/Risk 전체 체인을 실제 `BacktestEngine` 루프 안에서 순수
      관찰자로 구동해도 기존 전략의 체결 결과가 전혀 변하지 않음을 확인
      (`test_risk_backtest_integration.py`)
- [x] **Phase 2 현금 소진(cost-exhaustion) 버그 회귀 테스트 신규 작성**
      (`TestCashSafetyRegression`) — `BuyAndHoldStrategy.
      COST_SAFETY_MARGIN`과 동일한 목적의
      `PositionSizingConfig.cost_safety_margin`을 도입해, 완전히 사이즈된
      포지션도 거래비용을 위한 현금 여유를 항상 남김을 직접 검증
- [x] Sizing/Risk 5-way SQL join으로 lineage 증명
      (`position_sizing_results`↔`risk_assessments`↔`decision_outputs`↔
      `predictions`↔`regime_composites`, 한 DuckDB 카탈로그) —
      `attach_sizing_context`/`attach_risk_context`는 Phase 7과 동일한
      이유로 의도적으로 만들지 않음(Phase 8 spec §15, ADR-0013 §9 참조)

## Completed (Session 8 — Phase 7)

- [x] **Git/Branch Integrity Check 선행 수행 — 이전 세션 PASS를 재사용
      하지 않고 현재 HEAD(`6c0b0f6`, Phase 6)부터 처음부터 재검증**
      (사용자 지시) — `git log --graph --all`, `merge-base`,
      `is-ancestor`로 Phase 0~6 커밋 전부(9개) 개별 조상 확인, 병합
      커밋 0개, `origin/main` 대비 main에만 있는 커밋 0개/현재
      branch에만 있는 커밋 8개, working tree clean, 349/349 테스트
      통과 확인 → **PASS 판정 후 Phase 7 착수**
- [x] Master Plan/ADR-0001~0012/Phase 1~6 spec/현재 src·tests 재조사
      (충돌 없음 확인, DECISION REQUIRED 신규 발생 없음)
- [x] `docs/specifications/PHASE-7-decision-agent.md` 작성 (Git
      Integrity Check 결과를 §0에 포함, Decision Rules 표, 구조적
      경계, lineage, persistence, 15개 섹션)
- [x] `docs/decisions/ADR-0013-decision-agent.md` 작성 (9개 결정 사항
      + alternatives considered + consequences)
- [x] `src/decision/` 패키지 구현: `config.py`(DecisionConfig — 모든
      threshold configuration으로 분리), `models.py`(DecisionOutput —
      `trade_journal.enums.DecisionAction` 재사용, quantity/order_id/
      broker_order/execution_price 등 order-shaped 필드 구조적으로
      없음, frozen dataclass), `agent.py`(DecisionAgent Protocol +
      `BaselineRuleDecisionAgent` — prediction 필수/regime은 존재할
      때만 gate/portfolio_state None이면 fail-closed NO_TRADE의 6단계
      순차 규칙), `repository.py`(DecisionRepository Protocol +
      InMemoryDecisionRepository, natural-key idempotency, as_of 조회)
- [x] `src/storage/decision_repository.py`(DuckDBDecisionRepository) +
      `schema.py`/`serialization.py`에 `decision_outputs` 테이블(Trade
      Journal의 기존 `decisions` 테이블과 명칭 충돌 회피)/직렬화 추가 —
      기존 테이블 스키마 변경 없음
- [x] Phase 1~6 소스코드 변경 없음(Phase 7은 `schema.py`/
      `serialization.py`에 대한 순수 추가만 있으며 — `git diff | grep
      '^-'` 결과 두 파일 모두 삭제/변경 없음으로 확인 — 그 외
      Phase 1~6 코드 전혀 수정하지 않음)
- [x] `tests/decision/`(32) + `tests/storage/test_decision_repository.py`(5)
      + `tests/integration/test_decision_lineage.py`(3) — 신규 40개
      테스트 작성 및 전부 통과 (파일명 충돌 방지를 위해
      `test_boundary.py`를 `test_decision_boundary.py`로 명명)
- [x] **전체 테스트 스위트 389개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57 + Phase6 39 + Phase7 40) —
      Phase 1~6 기존 테스트 무손상 확인
- [x] Decision Agent가 quantity/order/broker/risk-bypass를 만들지
      않음을 구조적으로 검증 (`test_decision_boundary.py` —
      `dataclasses.fields()`/`inspect.signature()` reflection으로
      DecisionOutput/decide()에 금지 필드·파라미터가 없음을 확인)
- [x] 미래 데이터 유출 방지 회귀 테스트 (`test_decision_point_in_time.py`)
      — 미래 bar 추가 후 과거 시점 Decision을 재계산해도 결과가
      바이트 단위로 동일함을 확인
- [x] Phase 5 Regime → Phase 6 Prediction → Phase 7 Decision 전체
      체인을 실제 `BacktestEngine` 루프 안에서 순수 관찰자로 구동해도
      기존 전략의 체결 결과가 전혀 변하지 않음을 확인
      (`test_decision_backtest_integration.py`)
- [x] Decision↔Prediction↔Regime lineage를 Phase 3
      `build_experience_records`를 수정하지 않고 3-way SQL join으로
      증명 (`ExperienceRecord.action`이 이미 실제 체결 결과를 담고
      있어 hypothetical Decision으로 덮어쓰면 사실과 가설이 혼동되기
      때문에 `attach_decision_context`는 의도적으로 만들지 않음,
      ADR-0013 §9)

## Completed (Session 7 — Phase 6)

- [x] **Git/Branch Integrity Check 선행 수행** (사용자 지시) — 현재
      branch(`claude/phase-4-baseline-storage-tuavwk`)의 HEAD(d386420,
      Phase 5)부터 시작해 `git log --graph --all`, `merge-base`,
      `is-ancestor`로 검증: 단일 선형 히스토리(Initial commit → Phase 0
      → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5), `origin/main`과
      `origin/claude/autonomous-ai-investment-system-wvscwe` 둘 다 현재
      HEAD의 진짜 조상이며 두 branch 모두 HEAD에 없는 커밋이 0개, 병합/
      분기/reset/force-push 흔적 없음, 모든 Phase 산출물(`docs/specifications/
      PHASE-{1..5}*`, ADR 11개, `src/{data_infra,backtest,trade_journal,
      storage,baseline,regime}/`) 실존 확인, 310/310 테스트 통과, working
      tree clean → **PASS 판정 후 Phase 6 착수**
- [x] Master Plan/ADR-0001~0011/Phase 1~5 spec/현재 src·tests 재조사
      (충돌 없음 확인)
- [x] `docs/specifications/PHASE-6-prediction.md` 작성 (Git Integrity
      Check 결과를 §0에 포함)
- [x] `docs/decisions/ADR-0012-prediction-layer.md` 작성
- [x] `src/predict/` 패키지 구현: `enums.py`(PredictionMethodType —
      DETERMINISTIC_BASELINE/MODEL_BASED 명시적 구분), `config.py`
      (PredictionConfig), `models.py`(PredictionOutput — order/risk-shaped
      필드 구조적으로 없음, frozen dataclass), `predictor.py`
      (Predictor Protocol + `RandomWalkPredictor`(null hypothesis,
      데이터 조회 없음) + `DriftPredictor`(trailing mean return 외삽 +
      realized vol persistence) + `RegimeAwarePredictor`(Phase5 Regime을
      입력으로 사용하는 예시, alpha 주장 없음)), `repository.py`
      (PredictionRepository Protocol + InMemoryPredictionRepository),
      `experience.py`(attach_prediction_context — Phase3
      `ExperienceRecord.expected_outcome` 필드를 비침습적으로 채움)
- [x] `src/storage/prediction_repository.py`(DuckDBPredictionRepository) +
      `schema.py`/`serialization.py`에 predictions 테이블/직렬화 추가 —
      기존 테이블 스키마 변경 없음
- [x] Phase 5에 **1건의 additive 변경**: `regime.features.
      _annualized_realized_vol`를 `annualized_realized_vol`로 공개
      (rename만, 동작 변경 없음) — Phase5 기존 48개 regime 테스트 전부
      통과 확인 후 진행
- [x] `tests/predict/`(31) + `tests/storage/test_prediction_repository.py`(5)
      + `tests/integration/test_prediction_experience_lineage.py`(3) —
      신규 39개 테스트 작성 및 전부 통과 (파일명 충돌 방지를 위해
      `test_point_in_time.py`/`test_version_lineage.py`를 각각
      `test_predict_point_in_time.py`/`test_predict_version_lineage.py`로
      명명)
- [x] **전체 테스트 스위트 349개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57 + Phase6 39) — Phase 1~5 기존
      테스트 무손상 확인
- [x] Prediction은 BUY/SELL을 직접 만들지 않음을 구조적으로 검증
      (`test_boundary.py` — PredictionOutput에 order/risk-shaped 필드
      없음, Predictor는 Strategy Protocol을 구현하지 않음, `predict()`
      시그니처에 portfolio/risk 파라미터 없음을 reflection으로 확인)

## Completed (Session 6 — Phase 5)

- [x] Master Plan/ADR-0001~0010/Phase 1~4 spec/현재 src/tests 재조사
      (충돌 없음 확인)
- [x] `docs/specifications/PHASE-5-market-regime.md` 작성
- [x] `docs/decisions/ADR-0011-market-regime-detection.md` 작성
- [x] `src/regime/` 패키지 구현: `enums.py`(RegimeAxis/SubjectKind/
      TrendState 등, TradeProvenance는 재사용), `config.py`
      (RegimeConfig — 모든 threshold configuration으로 분리),
      `points.py`(PriceBar/BenchmarkPoint → PricePoint 정규화 어댑터),
      `features.py`(deterministic feature 계산 — MA관계/realized vol
      percentile/거래량 비율/rolling correlation/drawdown 기반 stress),
      `models.py`(RegimeObservation/CompositeRegimeObservation, frozen
      dataclass), `detector.py`(RegimeDetector — Phase2
      `AsOfDataView`/`BacktestClock`를 그대로 재사용하여 point-in-time
      guard를 새로 만들지 않음, curated composite label 테이블),
      `repository.py`(RegimeRepository Protocol +
      InMemoryRegimeRepository), `experience.py`(attach_regime_context —
      Phase3 `ExperienceRecord.market_regime` 필드를 비침습적으로 채움),
      `strategy.py`(RegimeConditionedStrategy — Phase2 Strategy Protocol
      그대로 구현하는 예시적 conditioning 전략, alpha 주장 없음)
- [x] `src/storage/regime_repository.py`(DuckDBRegimeRepository) +
      `schema.py`/`serialization.py`에 regime 테이블/직렬화 추가 — Phase4
      storage architecture(단일 DuckDB 카탈로그) 그대로 확장, 기존 테이블
      스키마는 변경 없음
- [x] `tests/regime/`(53) + `tests/storage/test_regime_repository.py`(6)
      + `tests/integration/test_regime_experience_lineage.py`(3) — 신규
      57개 테스트 작성 및 전부 통과 (파일명 충돌 방지를 위해
      `tests/regime/test_backtest_integration.py`를
      `test_regime_backtest_integration.py`로 명명)
- [x] **전체 테스트 스위트 310개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51 + Phase5 57) — Phase 1~4 기존 테스트 무손상
      확인
- [x] Phase 1~4 소스코드 변경 없음 (Phase 5는 완전히 additive) —
      `BacktestEngine`/`Strategy` Protocol/`TradeJournalRepository`/
      기존 storage schema 전부 그대로

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

### Session 5 (Phase 4)
- [x] Master Plan/ADR-0001~0009/Phase 1~3 spec 재조사 (충돌 없음 확인)
- [x] `docs/specifications/PHASE-4-baseline-models-and-storage.md` 작성
- [x] `docs/decisions/ADR-0010-persistent-storage-backend.md` 작성
- [x] `src/storage/` 패키지 구현: `config.py`, `engine.py`(단일 DuckDB
      connection 라이프사이클), `schema.py`(멱등 DDL, 전 테이블),
      `parquet_layer.py`(append-only, atomic temp-file+rename 배치 쓰기),
      `serialization.py`(명시적 typed row↔dataclass 변환),
      `data_repository.py`(`DuckDBDataRepository` — Phase1
      `DataRepository` Protocol 구현 + raw payload 저장 + ingestion용
      `append_bars`/`all_bars`), `trade_journal_repository.py`
      (`DuckDBTradeJournalRepository` — Phase3 `TradeJournalRepository`
      Protocol 구현), `experiment_repository.py`(신규 `ExperimentRepository`
      Protocol + DuckDB 구현), `experience_repository.py`(신규
      `ExperienceRepository` Protocol + DuckDB 구현)
- [x] `src/baseline/` 패키지 구현: `runner.py`(`run_baseline`/
      `run_multiple_baselines` — Phase2 BacktestEngine → Phase3
      ingest_backtest_result → 영속 Experiment/Experience 저장까지 연결),
      `report.py`(벤치마크 대비 비교 리포트, ranking/winner 필드 없음)
- [x] Phase 1에 **1건의 additive 변경**: `data_infra.repository`에
      `AppendableDataRepository` Protocol 추가, `IngestionRunner`의 타입
      힌트를 concrete class에서 이 Protocol로 확장(widening) — 기존 202개
      테스트 전부 통과 확인 후 진행
- [x] `tests/storage/`(34), `tests/baseline/`(9), `tests/integration/`(8)
      — 신규 51개 테스트 작성 및 전부 통과
- [x] **전체 테스트 스위트 253개 전부 통과** (Phase1 57 + Phase2 82 +
      Phase3 63 + Phase4 51) — Phase 1~3 기존 테스트 무손상 확인
- [x] `pyproject.toml`에 `duckdb`/`pyarrow` 런타임 의존성 추가
- [x] `tests/conftest.py` 신설 — 각 Phase 테스트 디렉터리의 helper 모듈을
      다른 Phase 테스트 디렉터리에서도 import 가능하게 하는 순수
      추가적(additive) sys.path 설정 (기존 테스트 파일 변경 없음)

---

## In Progress

없음 (Phase 18 — Production Safety Follow-up + Paper Trading
Validation — 완료. Live Trading은 Toss capability가 UNKNOWN인 한
여전히 구조적으로 비활성).

## Blocked

Live Trading 활성화 — Toss `ACCOUNT_BALANCE`/`POSITIONS`/
`ORDER_STATUS`/`CANCEL_ORDER` 4개 capability가 UNKNOWN인 한 구조적으로
불가 (`evaluate_safety_gate`가 실제로 차단). 상세는 위 "Current Phase"
섹션 및 `docs/operations/PRODUCTION-READINESS-MATRIX.md` 참조 — 이
섹션 이하는 Phase 4~9 시절에 작성된 이후 갱신되지 않고 있던 하위
섹션으로, Phase 17에서 그 사실 자체를 stale-doc 발견 사항으로
기록했고 이번 Phase 18에서 현재 상태에 맞게 갱신한다.

**DECISION REQUIRED 3건 누적 (Phase 2/3에서 이어짐) — 사용자 확인 필요.**
Phase 4, Phase 5, Phase 6, Phase 7, Phase 8, Phase 9, Phase 10, Phase 11,
Phase 12, Phase 13, Phase 14, Phase 15, Phase 16, Phase 17, Phase 18
세션 모두(Phase 14~18은 이번 갱신에서 일괄 재확인) 세 항목을
재검토했으며, 매번 이번 Phase의 완료 조건과 무관함을 확인하여 여전히
해결하지 않고 이연한다(재검토했으며 이번 Phase와 무관하여 이연) (Phase
4 spec §19, Phase 5 spec §16, Phase 6 spec §16, Phase 7 spec §14, Phase
8 spec §20, Phase 9 spec §20에 각각 재검토 근거 상세 기록):

1. (Phase 2에서 이어짐) 벤치마크 return type (PRICE_RETURN vs
   TOTAL_RETURN)
2. (Phase 3에서 이어짐) `BacktestEngine`의 per-decision `data_version`
   미노출 — Trade Journal이 결정 단위 데이터 버전을 `None`으로 기록
3. (Phase 3에서 이어짐) `BacktestResult`의 per-step corporate action
   이벤트 미노출 — Trade Journal의 `portfolio_state` 재구성이 fill 재생
   기반 근사치이며 두 fill 사이에 발생한 corporate action을 반영하지
   못함

원문은 아래 "DECISION REQUIRED — Phase 2 정밀도 개선" 섹션 참조. Phase
4 코드/테스트 자체는 이 결정들과 무관하게 정상 동작하며 구현이 차단된
것은 아니다.

## DECISION REQUIRED — Phase 2 정밀도 개선 (Phase 3에서 이어짐, 미결)

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
(문서화된 한계, ADR-0009). Phase 4는 이 값들을 있는 그대로(정직하게
None인 채로) 영속 저장소에 저장할 뿐, 값 자체를 재계산하거나
추정하지 않는다.

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
Option B는 Phase 2 아키텍처 변경이므로 Phase 2/3/4 세션 하나에서
임의로 결정하지 않는다.

Impact:
현재 Trade Journal에서 나온 Experience Record는 data_version 필드가
비어 있으므로(None) 재현성 검증 시 trade-level(Fill.data_version)
정밀도까지만 신뢰할 수 있다. corporate action이 포함된 백테스트의
portfolio_state 스냅샷은 근사치일 수 있다. 둘 다 성능/정확성 지표
자체(realized_pnl, execution_price 등)에는 영향이 없다 — 영향은
오직 "그 순간의 재현된 컨텍스트"의 정밀도에 국한된다. Phase 4에서
이 값들은 영속 저장소에도 동일하게 정직한 상태(None 또는 근사치임을
문서화한 상태)로 저장된다 — 저장소가 정밀도 문제를 해결하지도, 악화
시키지도 않는다.
```

## Design Decisions (Phase 10 세션의 핵심 결정)

1. Phase 10 착수 전 Git/Branch Integrity Check를 처음부터 재수행 —
   지정된 작업 브랜치가 실제로는 `main`에서 새로 생성되어 Phase 0~9
   lineage를 갖고 있지 않음을 발견. 지정 브랜치의 유일한 커밋이 실제
   lineage(`origin/claude/phase-4-baseline-storage-tuavwk`, Phase 9
   HEAD)의 조상임을 확인한 뒤 브랜치 포인터를 그 lineage로 재설정 —
   공유 히스토리를 rewrite하거나 force-push하지 않음(원격의 stale
   브랜치는 이미 삭제되어 있었음). 실제 저장소 상태를 인수인계 문서보다
   우선했다(위 "Current Subtask" 참조).
2. `AlternativeOutcome`/`CounterfactualRecord`/`AttributionResult`는
   Phase 3가 이미 이 Phase를 위한 예약 필드로 정의해 둔 정확히 그 타입을
   재사용 — Phase 9의 `LearningExperimentRecord`(새 타입이 필요했던
   사례)와 달리, 이번에는 재사용이 정확히 들어맞아 병렬 타입을 만들지
   않음(ADR-0016 §1).
3. `CounterfactualRecord` 영속화는 재구현하지 않음 — Phase 3의
   `TradeJournalRepository.record_counterfactual`/`get_counterfactual`이
   이미 임의 길이의 `alternatives` tuple을 완전히 저장/복원함을 기존
   코드를 읽어 확인한 뒤, `AttributionResult`에만(유일하게 저장소가
   없었던 타입) 신규 저장소를 추가(ADR-0016 §2).
4. CASH counterfactual의 `risk_free_rate` 기본값은 이 코드베이스에 이미
   존재하는 `0.0` 관행(`backtest.metrics.sharpe_ratio`/`sortino_ratio`)을
   그대로 따름 — 새로운 "전형적인" 무위험이자율을 발명하지 않음
   (ADR-0016 §3).
5. `market` attribution은 Phase 2 `BenchmarkEngine`/
   `compute_performance_report`가 이미 계산·영속화한
   `benchmark_cumulative_return`을 그대로 읽음 — 재계산하지 않아 저장된
   값과 어긋날 위험, 그리고 아직 해결되지 않은 PRICE_RETURN/
   TOTAL_RETURN DECISION REQUIRED를 두 번째 장소에서 다시 상속하는 것
   모두를 피함(ADR-0016 §4).
6. `selection`은 `cumulative_return - market - execution`의 정확한
   residual로 정의 — 순수 "종목 선택 능력"이 아니라 selection+timing이
   합쳐진 residual임을 문서에 명시. `market + selection + execution ==
   cumulative_return` 항등식이 구성상 항상 정확히 성립하며, 이를 직접
   테스트로 검증(`test_attribution.py::TestAttributionReconciles`,
   `test_attribution_lineage.py`)(ADR-0016 §5).
7. Brinson-Fachler류 가중치 기반 `timing`/`selection` 완전 분해는
   검토했으나 이번 Phase에서 구현하지 않음 — 필요한 원재료
   (`PositionSizingResult.proposed_target_weight` 시계열,
   `BenchmarkResult.value_series`)는 있지만, 검증되지 않은 모델이
   "그럴듯하지만 틀릴 수 있는" 숫자를 만들 위험이 이번 Phase가 실제로
   전달해야 하는 "AI가 실제로 alpha를 만들어냈는지"를 정직한 residual로
   전달하는 것보다 크다고 판단(ADR-0016 §5, Alternatives Considered §2).
8. `alternative_action_1`/`alternative_action_2`(다른 모델/전략의
   가상 의사결정과 비교)는 Phase 3가 이미 Phase 11(Model Evolution)로
   지정해둔 근거를 재검토 후 그대로 유지 — 대안 모델의 전체 파이프라인을
   별도로 실행/등록/추적하는 것은 이번 Phase가 아니라 Model Evolution의
   고유 범위(ADR-0016 §7).
9. Phase 10은 새로운 `AsOfDataView`/`DataRepository` 호출 지점을 하나도
   추가하지 않음 — CASH는 데이터 조회가 전혀 필요 없고, HOLD는 Phase 3의
   기존 호출을 변경 없이 재사용하며, attribution은 이미 계산된
   `ExperimentRecord` 필드만 읽음(ADR-0016 §8).

## Design Decisions (Phase 9 세션의 핵심 결정)

1. Phase 9 착수 전 Git/Branch Integrity Check를 **이전 세션의 PASS
   결과를 재사용하지 않고** 현재 HEAD 기준으로 처음부터 재수행 —
   사용자가 명시적으로 반복 요구했음. 실제 검증 결과는 PASS였으므로
   그대로 Phase 9 진행.
2. `LearningExperimentRecord`는 `backtest.experiment.ExperimentRecord`를
   재사용하지 않고 새 타입으로 정의 — 재사용을 먼저 시도했으나
   `ExperimentRecord`가 `PerformanceReport`/transaction_cost_config/
   slippage_config/benchmark 등 backtest 실행에 특화된 필드로 구성되어
   있어 training run(dataset_id/trainer_version/evaluator_version 등)과
   구조적으로 맞지 않음을 확인. 대신 저장 패턴(단일 DuckDB 카탈로그,
   id-allocating tracker, natural-key idempotency)은 `storage.
   experiment_repository`가 이미 확립한 것을 그대로 재사용 — "타입은
   새로 만들되 아키텍처 패턴은 재사용"이라는 Phase 8의
   PositionSizingResult/RiskCheckedPosition과 동일한 판단 기준을 적용
   (ADR-0015 §1).
3. `CandidateModelStatus`에 Master Plan §11.2의 7개 상태를 전부
   예약하되, 이번 Phase 코드는 오직 `CANDIDATE`만 실제로 생성 —
   `APPROVED`/`DEPLOYED`를 생성할 수 있는 코드 경로가 `learning/*.py`
   어디에도 없음을 AST 스캔으로 구조적으로 검증(ADR-0015 §2).
4. `build_training_dataset`의 `provenance` 파라미터는 기본값을 두지
   않음(다른 모든 config는 기본값 있음) — provenance가 섞이는 것을
   "쉬운 기본 경로"로 만들지 않기 위한 의도적 설계, `DataCleaner`도
   요청된 provenance와 다른 레코드를 INVALID로 표시(ADR-0015 §3).
5. `as_of_cutoff` 필터링을 Data Cleaning이 레코드를 보기 *전에* 적용 —
   `AsOfDataView`의 "미래 데이터는 존재하지 않는다" 원칙을 Experience
   Dataset 구성에도 동일하게 적용(문자 그대로 재사용은 아니지만 동일한
   설계 원칙 적용, ADR-0015 §4).
6. **(자체 테스트로 발견/수정)** `dataset_version`이 처음에는
   `source_experience_ids` 목록만 해싱했으나, `trade_id`/`experience_id`가
   journal마다 로컬로 재시작되는 시퀀스라는 사실(Phase 3 자체 문서화된
   설계) 때문에 서로 다른 두 journal이 우연히 동일한 id를 가지면서 실제
   내용이 다른데도 동일한 dataset_version이 나오는 문제를 발견 — 실제
   sample 내용((trade_id, label_value, sample_as_of_time) 튜플)을
   해싱하도록 수정하여 `compute_data_version`의 진짜 content-hash
   계약을 충족(ADR-0015 §5).
7. **(자체 테스트로 발견/수정)** 위와 동일한 원인으로
   `TrainingDataset.dataset_id` 등 storage PRIMARY KEY가 in-process
   allocator에서 나와 독립적인 두 pipeline 실행이 충돌하는 문제 발견 —
   Phase 4가 `experience_id_seq`로 이미 확립한 "자연키로 dedup 확인 후
   storage-level 시퀀스로 새 id 발급" 패턴을 4개 Learning 저장소 모두에
   동일하게 적용(ADR-0015 §6).
8. Label은 `TradeRecord.realized_return`(이미 실현된 실제 결과)만
   사용 — 가격 데이터 기반의 새로운 forward-return 계산을 이번 Phase에서
   만들지 않음. `label_horizon`은 고정값이 아니라 각 거래의 실제
   holding_period를 반영해 정직하게 `None`으로 둠(ADR-0015 §7).
9. Train/Validation/Test는 `sample_as_of_time` 기준 시간순 분할만
   구현 — random shuffle 사용하지 않음, Purged K-Fold/Embargo 전체
   구현은 이후 Validation 전용 Phase로 명시적으로 이연(ADR-0015 §8).

## Design Decisions (Phase 8 세션의 핵심 결정)

1. Phase 8 착수 전 Git/Branch Integrity Check를 **이전 세션의 PASS
   결과를 재사용하지 않고** 현재 HEAD 기준으로 처음부터 재수행 —
   사용자가 명시적으로 반복 요구했음. 실제 검증 결과는 PASS였으므로
   그대로 Phase 8 진행.
2. Position Sizing과 Portfolio Risk Engine을 별도 top-level 패키지로
   나누지 않고 `src/risk/` 패키지 안에 `sizing.py`/`engine.py` 두
   모듈로 구현 — Phase 3 `trade_journal`이 이미 여러 책임(models/
   repository/analysis/experience/backtest_adapter)을 한 패키지
   아래 모듈로 나눈 패턴을 그대로 적용(ADR-0014 §1).
3. `RiskCheckStatus`(PASS/REDUCE/REJECT/UNKNOWN)를 Position Sizing과
   Risk Engine 양쪽 모두의 결과 상태로 공유 — 병렬 enum을 만들지 않음
   (ADR-0014 §2).
4. `PositionSizer.size()`/`PortfolioRiskEngine.assess()`는 Phase 7의
   `DecisionAgent.decide()`와 동일하게 순수 data-in/data-out 함수 —
   `AsOfDataView`나 저장소를 전혀 직접 호출하지 않음. `current_price`는
   호출자가 이미 조회해 전달하는 값(예: Strategy가 `data.get_bars(...)
   .close`로 조회하는 것과 동일한 방식) — Phase 8은 새로운 leakage
   guard를 전혀 작성하지 않음(ADR-0014 §3).
5. `single_position_limit`을 Position Sizing과 Risk Engine 양쪽에서
   독립적으로(서로 다른 config 값으로) 재검사 — Risk Engine이 상위
   계층의 결과를 무조건 신뢰하지 않는 defense-in-depth 원칙을 의도적으로
   적용(ADR-0014 §4).
6. `RiskConfig`의 각 한도값은 "설정 안 됨(`None`, 검사 자체를
   건너뜀)"과 "설정됐지만 이번 호출에 필요한 데이터가 없음(fail-closed
   REJECT)"을 명확히 구분 — 전자를 후자처럼 처리하면 구현되지 않은
   모든 constraint가 영구적으로 거래를 막고, 후자를 전자처럼 처리하면
   활성화된 검사가 데이터 없이도 조용히 통과하는 두 가지 잘못된 결과를
   모두 방지(ADR-0014 §5). 이 구분은 신규 위험 증가(BUY) 행동에만
   적용되며 HOLD/NO_TRADE/SELL/EXIT는 절대 차단되지 않음.
7. `PositionSizingConfig.cost_safety_margin`은 Phase 2
   `BuyAndHoldStrategy.COST_SAFETY_MARGIN`과 동일한 값·목적을 재사용 —
   지시사항이 명시한 Phase 2 현금 소진 버그의 재발 방지를 위한 전용
   regression test(`TestCashSafetyRegression`)로 직접 검증
   (ADR-0014 §7).
8. `risk_state`(PortfolioRiskState)는 별도 테이블 없이
   `risk_assessments.payload_json`에 내장 — `decision_outputs`가 이미
   `regime` context dict를 내장한 것과 동일한 선택(ADR-0014 §6).
9. `max_sector_weight`/`max_factor_exposure`는 `None`(설정 안 됨)으로
   유지 — `data_infra.models.SecurityMaster`에 sector/factor 필드
   자체가 없어 검사할 데이터가 없음. Phase 5의 Correlation/Stress
   3축 조합 미구현과 동일한 패턴으로 문서화된 확장 지점만 준비
   (ADR-0014 §9).
10. 다중 포지션 포트폴리오의 gross_exposure/position_weights는 현재
    호출 대상 종목을 제외한 나머지 보유 포지션에 대해 `average_cost`
    proxy를 사용 — Phase 2 `PortfolioAccounting.mark_to_market`이
    이미 사용하던 동일한 fallback이며, Phase 5부터 이어지는
    "종목 1개당 호출 1회" 아키텍처에서 상속된 한계임을 명시적으로
    문서화(ADR-0014 §10, Known Risks 참조) — 새로운 DECISION REQUIRED가
    아니라 이미 알려진 구조적 제약.
11. `DecisionAction.EXIT`는 `BaselineRuleDecisionAgent`가 아직 생성하지
    않지만, `PositionSizer`는 `SELL`과 동일하게(전량 청산) 처리하도록
    미리 구현 — 향후 Risk Engine이 강제 청산을 위해 `EXIT`를 생성하기
    시작해도 `risk.sizing` 변경이 필요 없음(ADR-0014 §11).
12. `turnover`는 `risk.engine`이 재계산하지 않고 호출자가 전달 —
    `PortfolioAccounting.turnover()`가 이미 추적하고 있는 값을
    중복 구현하지 않음. 호출자가 값을 갖고 있지 않으면(예: Strategy
    관찰자) `None`으로 정직하게 전달하고 `RiskConfig.max_turnover`는
    기본값 `None`(검사 비활성)으로 둠(ADR-0014 §12).

## Design Decisions (Phase 7 세션의 핵심 결정)

1. Phase 7 착수 전 Git/Branch Integrity Check를 **이전 세션의 PASS
   결과를 재사용하지 않고** 현재 HEAD 기준으로 처음부터 재수행 —
   사용자가 명시적으로 반복 요구했음. 실제 검증 결과는 PASS였으므로
   그대로 Phase 7 진행.
2. `DecisionOutput.action`은 `trade_journal.enums.DecisionAction`
   (Phase 3이 이미 "Phase 7 예약"으로 명시해둔 enum)을 그대로 재사용 —
   병렬 enum을 만들지 않음 (ADR-0013 §1).
3. `DecisionOutput`은 quantity/order_id/broker_order/execution_price/
   risk-limit-override 등 어떤 order/risk-shaped 필드도 구조적으로
   갖지 않음. weight 필드명도 `target_weight`가 아니라
   `target_weight_hint`로 명명해 Position Sizing(Phase 8)의 권위 있는
   출력이 아님을 타입 이름 자체로 표시. `BaselineRuleDecisionAgent`도
   `decide()` 외 공개 메서드가 없고 quantity/broker/risk override를
   전달할 파라미터가 없음 — reflection 기반 테스트로 검증
   (`test_decision_boundary.py`, ADR-0013 §2).
4. `DecisionAgent.decide()`는 이미 계산된 입력(prediction, regime,
   portfolio_state, risk_state)만 받는 순수 data-in/data-out 함수 —
   `AsOfDataView`나 어떤 저장소도 직접 호출하지 않음. Point-in-time
   안전성은 전적으로 Phase 5/6가 만든 입력에서 상속받으며, Phase 7은
   새로운 leakage guard를 전혀 작성하지 않음 (ADR-0013 §3).
5. Portfolio State/Risk State는 Phase 7이 생산하지 않는 optional
   파라미터로만 받음 — Portfolio State는 백테스트 루프의 실제
   `PortfolioView`, Risk State는 미래 Risk Engine(Phase 8)의 몫으로
   남겨두고 현재는 항상 `None` (ADR-0013 §4).
6. `portfolio_state is None` → `NO_TRADE`(reason:
   `portfolio_state_unavailable`)로 fail-closed — Master Plan §1.4의
   "Position Unknown → 신규 주문 차단" 규칙을 문자 그대로 구현
   (ADR-0013 §5).
7. Regime은 **존재할 때만** 추가 게이트(Trend UNKNOWN 또는 Stress
   HIGH → NO_TRADE)로 작동하고, Prediction은 없거나 불완전하면
   (`expected_return`/`confidence` 중 하나라도 `None`) 항상
   무조건 NO_TRADE — 두 입력의 비대칭적 취급은 의도적 설계
   (ADR-0013 §6).
8. `DecisionAction.EXIT`는 enum에는 존재하되 baseline 규칙 어디서도
   생성되지 않음 — Phase 2가 `OrderStatus.CANCELLED`를 미리 예약해둔
   것과 동일한 패턴으로, risk-driven 강제 청산은 Risk Engine(Phase 8)
   의 몫 (ADR-0013 §7).
9. 영속화 테이블명은 `decisions`가 아니라 `decision_outputs` — Phase 3
   Trade Journal이 이미 `decisions` 테이블(실제 체결된 결정의 기록)을
   갖고 있어, Phase 7의 (아직 order 생성에 연결되지 않은) hypothetical
   agent 출력과 명칭이 충돌하지 않도록 구분 (ADR-0013 §8).
10. Phase 5/6의 `attach_*_context` 패턴과 달리 `attach_decision_context`는
    **의도적으로 만들지 않음** — `ExperienceRecord.action`은 이미 실제
    체결(`Fill.side`)에서 나온 ground truth이며, 여기에
    `BaselineRuleDecisionAgent`의 hypothetical 병렬 판단을 덮어쓰면
    사실과 가설을 혼동시키는 결과가 됨. 대신 Decision↔Prediction↔Regime
    lineage는 한 DuckDB 카탈로그 안에서의 3-way SQL join으로만 증명
    (ADR-0013 §9).

## Design Decisions (Phase 6 세션의 핵심 결정)

1. Phase 6 착수 전 Git/Branch Integrity Check를 먼저 수행 — 사용자가
   명시적으로 요구했고, 결과가 FAIL이었다면 임의로 merge/rebase/reset/
   force-push를 하지 않고 DECISION REQUIRED로 보고한 뒤 작업을 중단할
   계획이었음. 실제 검증 결과는 PASS였으므로 그대로 Phase 6 진행.
2. `PredictionOutput`은 order/risk-shaped 필드(side, quantity,
   target_weight, risk_state, portfolio_state 등)를 구조적으로 전혀
   갖지 않음 — `Predictor.predict()`도 portfolio/risk 파라미터를 받지
   않음. "Prediction 결과만으로 주문 생성 금지"를 문서가 아니라 타입
   구조로 강제 (ADR-0012 §1).
3. `Predictor`는 Phase 5 `RegimeDetector`와 동일하게 오직
   `backtest.asof.AsOfDataView`만 입력으로 받음 — Phase 6에서 새로운
   point-in-time guard를 전혀 작성하지 않음 (ADR-0012 §2).
4. Baseline predictor 2종을 명확히 구분: `RandomWalkPredictor`(무정보
   null hypothesis, 데이터 조회 자체가 없음, expected_return=0/
   probability=0.5는 추정이 아니라 가설 자체) vs `DriftPredictor`(trailing
   mean return 외삽 + realized vol persistence — 둘 다 표준적인 naive
   forecasting baseline). `PredictionMethodType`(DETERMINISTIC_BASELINE/
   MODEL_BASED)으로 타입 레벨에서 구분 (ADR-0012 §3, §6).
5. `confidence`는 Phase 5의 `reliability`와 동일한 실제 data completeness
   비율을 재사용 — 가짜 confidence score 아님. `uncertainty`는 실제
   추정량(trailing mean return)의 standard error — RandomWalk는 추정 자체를
   하지 않으므로 uncertainty=None (ADR-0012 §4).
6. Phase 5에 **1건의 additive rename**: `regime.features.
   _annualized_realized_vol` → `annualized_realized_vol`(공개) — Phase 6가
   동일한 realized volatility 공식을 중복 구현하지 않도록 재사용. 동작
   변경 없음, Phase 5 기존 48개 테스트 전부 통과 확인 후 진행 (ADR-0012 §5).
7. `RegimeAwarePredictor`로 "Market Regime Detection → Prediction/Signal
   Engine" 데이터 흐름(Master Plan §4.1)을 실제로 연결하되, Phase 5의
   `RegimeConditionedStrategy`와 동일한 원칙 적용: 어떤 테스트도 조건부
   예측이 더 정확하다고 주장하지 않음, 오직 mechanism(EXTREME 변동성일
   때만 dampening 발생, 항상 0 방향으로만 이동)만 검증 (ADR-0012 §6).
8. Phase 5의 `RegimeConditionedStrategy`와 달리, Prediction → 주문을
   만드는 Strategy wrapper는 **의도적으로 만들지 않음** — 이번 Phase
   지시사항이 "Prediction 결과만으로 주문 생성 금지"를 Phase 5보다 더
   강하게 명시했고, Position Sizing/Risk Engine(Phase 8)이 아직 없어
   그런 wrapper를 만들면 지켜야 할 경계를 스스로 흐리게 됨. Backtest
   integration은 "매 체크포인트에서 prediction을 계산해도 백테스트
   결과가 바이트 단위로 동일함"을 증명하는 순수 관찰 방식으로만 구현
   (ADR-0012 §7).
9. Prediction/Regime/Trade Journal/Experiment 전부 Phase 4의 단일 DuckDB
   카탈로그에 저장 — `predictions` 테이블 1개만 추가, 기존 테이블 스키마
   변경 없음 (ADR-0012 §8).
10. Prediction↔Trade Journal lineage는 Phase 5의 `attach_regime_context`와
    동일한 비침습적 opt-in 패턴(`attach_prediction_context`)으로 구현 —
    Phase 3 코드 변경 없음, `ExperienceRecord.expected_outcome`(Phase 3가
    이미 예약해둔 필드)을 채움 (ADR-0012 §9).

## Design Decisions (Phase 5 세션의 핵심 결정)

1. `RegimeObservation`/`CompositeRegimeObservation.provenance`는
   `trade_journal.enums.TradeProvenance`를 그대로 재사용 — 병렬 enum을
   만들지 않음 (ADR-0009가 이미 확립한 "기존 타입 재사용" 원칙을 Phase 5
   에도 그대로 적용, ADR-0011 §1).
2. `RegimeDetector`는 오직 `backtest.asof.AsOfDataView`만 입력으로
   받음 — Phase 2가 이미 만들고 검증한 point-in-time-safe view를 그대로
   재사용하여 Phase 5에서 새로운 look-ahead guard를 전혀 작성하지 않음.
   Backtest 루프 밖(standalone) 사용은 `make_single_point_view()`가
   `BacktestClock`을 체크포인트 1개로 구성해 재사용 (ADR-0011 §2).
3. Regime observation/composite는 Phase 4가 만든 DuckDB 카탈로그에
   테이블 2개(`regime_observations`, `regime_composites`)를 추가하는
   방식으로 영속화 — Parquet가 아님. ADR-0010 §1이 이미 세운 기준(대용량
   시계열=Parquet, point-lookup/조인 중심 relational=DuckDB)을 그대로
   적용한 것으로, 기존 테이블 스키마는 전혀 변경하지 않음 (ADR-0011 §4).
4. Regime↔Trade Journal lineage는 Phase 3 코드(`build_experience_records`)
   를 수정하지 않고, `regime.experience.attach_regime_context()`라는
   별도의 opt-in enrichment 함수로 구현 — `ExperienceRecord.market_regime`
   필드는 Phase 3가 "Phase 5용으로 예약"해둔 것을 그대로 채움 (ADR-0011 §5).
5. `RegimeConditionedStrategy`는 Phase 2 `Strategy` Protocol을 그대로
   구현하는 예시적 wrapper이며, 이를 사용하는 모든 테스트는 조건부 실행
   결과가 더 우수하다고 주장하지 않음 — 오직 mechanism이 동작하는지와
   기계적 성질(BUY 억제 시 거래 수가 늘지 않음)만 검증 (ADR-0011 §6).
6. `reliability`는 실제로 계산 가능한 데이터 완전성 비율이며, 가짜
   ML confidence score가 아님 — lookback window 대비 실제 확보한 데이터
   비율이 `min_data_completeness` 미만이면 axis 상태를 `UNKNOWN`으로
   강제 (fail-closed) (ADR-0011 §7).
7. Phase 1~4 소스코드는 전혀 수정하지 않음 — Phase 5는 완전히 additive
   (신규 패키지 `src/regime/`, 신규 저장소 모듈, 기존 테이블에 영향 없는
   신규 테이블 2개만 추가).

## Design Decisions (Phase 4 세션의 핵심 결정)

1. DuckDB 카탈로그 파일 1개(모든 relational/metadata 테이블) + Parquet
   append-only 파일(대용량 시계열 — Raw/Clean market data만) 조합.
   Benchmark처럼 시계열이지만 볼륨이 작은 데이터는 DuckDB 테이블로 유지
   (ADR-0010 §1).
2. Parquet 쓰기는 temp file + atomic rename(`os.replace`)로만 수행 —
   기존 파일을 열어 append/rewrite하지 않음. 크래시 시 반파일이 아니라
   최대 orphan temp 파일만 남음 (ADR-0010 §2).
3. Raw Market Data는 Clean Market Data와 물리적으로 분리된 별도 Parquet
   데이터셋 — Phase 1은 원래 정규화 이전 payload를 전혀 저장하지
   않았으므로 이번 Phase에서 신규로 추가 (ADR-0010 §3).
4. Idempotency는 각 데이터셋마다 natural key 기반 애플리케이션 레벨
   체크(Parquet는 쿼리 후 필터링, DuckDB 테이블은 `ON CONFLICT DO
   NOTHING` 또는 check-then-insert) — Phase 1/3가 이미 확립한 패턴을
   영속 계층까지 확장 (ADR-0010 §4).
5. Repository 추상화 완전 유지 — `DuckDBDataRepository`/
   `DuckDBTradeJournalRepository`/`DuckDBExperimentRepository`/
   `DuckDBExperienceRepository`는 기존(또는 신규) Protocol만 구현하며,
   `BacktestEngine`/`ingest_backtest_result` 등 Phase 2/3 소비자 코드는
   전혀 수정하지 않음 (ADR-0010 §5).
6. Phase 1에 **1건의 additive 변경**: `AppendableDataRepository`
   Protocol 추가 + `IngestionRunner` 타입 힌트 확장 — 기존 202개 테스트
   전부 통과 확인 후 진행 (ADR-0010 §6).
7. **(자체 테스트로 발견/수정)** `run_baseline`으로 여러 baseline을
   비교할 때는 `ExperimentTracker`를 반드시 공유해야 함 —
   `BacktestEngine`이 기본적으로 인스턴스마다 새 tracker를 생성하므로
   공유하지 않으면 두 실험이 동일한 `experiment_id`("BT-000001")로
   충돌하고, `ExperimentRepository.record()`의 멱등성 때문에 두 번째
   실험이 조용히 저장되지 않는다. `run_multiple_baselines()`가 이를
   자동으로 처리한다 (Phase 4 spec §10.1, ADR-0010 "Known correctness fix").
8. **(자체 테스트로 발견/수정)** `DuckDBExperienceRepository`는
   `ExperienceRecord.experience_id`가 아니라 `trade_id`를 dedup key로
   사용 — `build_experience_records()`의 `experience_id`는 호출 1회
   범위로만 유일함이 문서화되어 있어(전역 유일 아님), 성장하는 영속
   journal에 대해 반복 호출하면 서로 다른 trade가 같은 `experience_id`를
   재사용할 수 있고, 그 값으로 dedup하면 첫 호출 이후의 레코드가 조용히
   유실된다. 저장소가 자체 시퀀스로 전역 유일 `experience_id`를 새로
   발급한다 (Phase 4 spec §12.1, ADR-0010 "Known correctness fix").

## Known Risks / Limitations (의도적으로 남겨둔 항목)

- Learning Engine이 생산한 `CandidateModelArtifact`를 실제로 검증/승인/
  배포하는 로직 없음 (Phase 10/11) — Phase 9는 CANDIDATE 상태까지만
  생산하고, `CandidateModelStatus`의 나머지 6개 상태(BACKTESTED/
  VALIDATED/OOS_TESTED/PAPER_TESTED/APPROVED/DEPLOYED)는 enum에만
  예약되어 있을 뿐 이를 실제로 부여하는 코드가 전혀 없다.
- `MeanRewardBaselineTrainer`는 실제 예측 가치를 주장하지 않는
  null-hypothesis baseline(TRAIN split 평균)일 뿐 — 실제 ML/통계 모델
  구현은 아직 없음(`CandidateTrainer` Protocol만 확장 지점으로 준비).
- `Evaluator`는 MAE/MSE + baseline 비교만 제공 — PBO/Deflated
  Sharpe/Walk-Forward 검증은 구현하지 않음(Phase 10 Validation 범위,
  Design Decisions #9, ADR-0015 §8).
- Label은 `TradeRecord.realized_return` 1종만 구현 —
  forward_return/direction/excess_return_vs_benchmark/
  risk_adjusted_outcome 등은 아직 구현하지 않음(Design Decisions #8,
  ADR-0015 §7).
- `EvaluationResult`에 S&P 500 벤치마크와의 직접 비교는 아직 연결되지
  않음 — Experience Dataset 샘플이 거래 단위(per-trade)이지 벤치마크
  단위가 아니기 때문(Phase 9 spec §14에 문서화된 한계, 향후 확장
  가능).
- `ExperienceRecord`↔`TrainingDataset` 간 비침습적 lineage enrichment
  함수(`attach_learning_context`류)는 만들지 않음 — Phase 7/8과 동일한
  이유(Trade Journal의 ground truth 레코드를 hypothetical 결과로
  덮어쓰지 않음), 대신 4-way SQL join으로 lineage 증명(Phase 9 spec
  §15, ADR-0013 §9의 연장).
- Position Sizing/Risk Engine의 출력(`RiskCheckedPosition`)을 실제로
  소비해 주문을 만드는 Order Creation 없음 (Phase 8+ 이후) — Phase 8은
  sizing/risk 계산을 생산/영속화/lineage 연결까지만 하고, 어떤
  Strategy도 아직 `RiskCheckedPosition`을 읽어 주문을 만들지 않는다
  (ADR-0014 Negative/Trade-offs — 의도적으로 만들지 않음).
- 다중 포지션 포트폴리오의 gross_exposure/position_weights/
  concentration은 현재 호출 대상 종목 외 나머지 포지션에 대해
  `average_cost` proxy를 사용 — 실시간 가격이 있는 종목은 1개
  호출당 1개뿐인 "종목당 호출 1회" 아키텍처(Phase 5~8 공통)에서
  상속된 제약이며 Phase 8이 새로 만든 문제가 아님(Design Decisions
  #10, ADR-0014 §10).
- `RiskConfig.max_sector_weight`/`max_factor_exposure`는 `None`(검사
  비활성) — `SecurityMaster`에 sector/factor 데이터가 없어 실제로
  검사할 수 없음(Design Decisions #9, ADR-0014 §9).
- `PositionSizingConfig`/`RiskConfig`의 threshold(`max_position_weight`,
  `reference_volatility`, `minimum_cash_ratio`, `max_drawdown` 등)는
  실제 성과 데이터에 맞춰 보정되지 않은 예시적 기본값 — 실 배포
  캘리브레이션 주장 없음(ADR-0014 "Negative/Trade-offs").
- `turnover`는 Risk Engine이 자체 계산하지 않고 호출자가 전달해야 함 —
  백테스트 루프의 Strategy 관찰자 컨텍스트에서는 이 값을 갖고 있지
  않아 `None`으로 전달되며, 기본 `RiskConfig.max_turnover=None`이라
  turnover_limit 검사는 기본적으로 비활성 상태(Design Decisions #12,
  ADR-0014 §12).
- `DecisionAction.EXIT`를 실제로 생성하는 risk-driven 강제 청산 로직
  없음 — Phase 8의 `PositionSizer`는 `EXIT`를 `SELL`과 동일하게 처리할
  준비만 되어 있을 뿐, 아직 아무 것도 `EXIT`를 생성하지 않는다(Phase 7
  Design Decisions #8 계속).
- `DecisionAction.EXIT`를 실제로 생성하는 risk-driven 강제 청산 로직
  없음 — enum만 예약(위 Design Decisions #8).
- `DecisionOutput`↔`ExperienceRecord` 간 비침습적 lineage enrichment
  함수(`attach_decision_context`) 없음 — 의도적 설계 결정(위 Design
  Decisions #10, ADR-0013 §9), 오류나 누락이 아님.
- `DecisionConfig`의 threshold(`min_confidence`,
  `min_signal_to_uncertainty_ratio`, `min_expected_return`,
  `exit_return_threshold`, `max_target_weight_hint`)는 실제 성과
  데이터에 맞춰 보정되지 않은 예시적 기본값 — 실 배포 캘리브레이션
  주장 없음(ADR-0013 "Negative/Trade-offs").
- (Phase 7/8에서 부분 해결) Prediction은 이제 Decision Agent(Phase 7)와
  Position Sizing(Phase 8, `expected_volatility` 소비)이 실제로
  사용한다. 다만 그 결과(`RiskCheckedPosition`)를 실제 주문으로
  연결하는 Order Creation은 여전히 없음 — Prediction → 주문을 만드는
  Strategy wrapper는 여전히 의도적으로 만들지 않음.
- Prediction의 model-based(`MODEL_BASED`) 구현 없음 — baseline
  (RandomWalk/Drift) 2종만 존재, 통계적/ML 모델은 baseline 검증 없이
  조기 구현하지 않음(지시사항에 따라 의도적으로 보류).
- `DriftPredictor.probability`는 개별 일별 수익률 중 양수 비율이라는
  거친(coarse) 근사치 — 정밀한 다일(multi-day) horizon 복리 확률이
  아님, 문서에 명시적으로 단순화로 기록됨 (ADR-0012 "Negative/Trade-offs").
- (Phase 7/8에서 부분 해결) Regime은 이제 Decision Agent(Phase 7,
  Trend/Stress 게이트)와 Position Sizing/Risk Engine(Phase 8,
  Liquidity 게이트)이 실제로 사용한다. 다만 Correlation/Volatility
  축은 아직 어떤 거래 판단 로직에도 소비되지 않음.
- Regime의 Correlation/Stress 조합 확장(3축 이상 조합) 미구현 — 필요성이
  아직 확인되지 않아 `features.py`에 확장 지점만 문서화 (ADR-0011
  "Alternatives Considered").
- Spread 기반 유동성 지표 미구현 — Phase 1 `PriceBar`에 bid/ask spread
  필드 자체가 없어 계산 불가 (문서화된 데이터 모델 한계, 은폐 아님).
- 일반화된 Feature Registry 미구현 — Phase 5는 Regime 자신에게 필요한
  최소한의 feature 메타데이터(`feature_version`/`method_version`/
  `configuration_version`)만 구현했으며, 향후 더 넓은 registry가
  이를 스키마 변경 없이 흡수할 수 있도록 설계됨 (ADR-0011).
- 실 데이터 provider 없음(ADR-0005), 벤치마크 return type 미결(위
  DECISION REQUIRED 참조) — Phase 4의 스토리지/베이스라인 구현과 무관하게
  계속 이연.
- Phase 3의 `data_version`(per-decision) 및 `portfolio_state`(corporate
  action 반영) 정밀도 한계 — 위 DECISION REQUIRED 참조. Phase 4는 이
  값을 있는 그대로 영속화할 뿐 해결하지 않는다.
- `prediction_error`, `timing_error`, `risk_estimation_error`,
  `regime_error`, `signal_error`, `market`/`sector`/`factor`/
  `selection`/`timing` attribution — 전부 `None` (Phase 5/6/8 부재).
- (Phase 7에서 해결) `DecisionOutput`을 통해 `NO_TRADE`가 정상적인
  결과로 명시적으로 기록되나, 이 기록은 여전히 Trade Journal의
  `decisions` 테이블(실제 주문)과는 분리된 별도 `decision_outputs`
  테이블에만 남는다 — Phase 2 Strategy가 실제로 주문 의도를 생성한
  경우만 Trade Journal에 기록되는 것은 변함없음.
- Experience Record의 `reward`는 단순 `realized_return` 매핑 — 실제
  reward function 설계는 Phase 9 과제. Learning Engine 자체는 아직
  구현하지 않음(Phase 9) — 영속 Experience Dataset은 축적만 될 뿐 아직
  아무 것도 그것을 학습에 사용하지 않는다.
- DuckDB는 단일 프로세스 임베디드 엔진 — 동시 다중 writer 지원 없음
  (ADR-0002에서 이미 인지된 한계, ADR-0010에서 재확인). Phase 15/16에서
  다중 프로세스 Paper/Live 배포가 필요해지면 재검토 필요.
- Paper/Live 브로커 어댑터 없음 — Trade Journal/Experience의
  `PAPER_TRADING`/`LIVE_TRADING` provenance 분리는 저장소 레벨까지
  검증되었으나, 이를 실제로 생산할 producer는 아직 없음 (Phase 13/15/16).
- Model Registry / "왜 모델이 변경되었는가" 감사 질문 (Phase 11).
- 일반화된 Feature Engine 없음, Order Creation/Validation/Broker 없음
  (Phase 9+) — Market Regime Detection(Phase 5), Prediction(Phase 6),
  Decision Agent(Phase 7), Position Sizing/Portfolio Risk Engine
  (Phase 8)은 구현 완료. Baseline 전략은 여전히 Phase 2의 단순 Strategy
  인터페이스로 직접 신호를 계산 (Regime을 조건으로 사용하는 것은
  `RegimeConditionedStrategy`로, Prediction을 Regime에 조건화하는
  것은 `RegimeAwarePredictor`로, Regime+Prediction+Portfolio State를
  결합하는 것은 `BaselineRuleDecisionAgent`로, 그 결과를 risk-aware
  포지션으로 변환하는 것은 `DeterministicPositionSizer`+
  `DeterministicPortfolioRiskEngine`으로 각각 시연만 함, 실제 주문에
  연결된 채택 전략/모델 아님).
- Limit order, Purged K-Fold/Embargo, 5종 corporate action 처리 없음
  (Phase 2부터 이어짐).
- Simple ML baseline 미구현 — Phase 2 spec이 `Strategy` Protocol만
  예약해두었고, 이번 Phase 지시사항도 필수가 아닌 선택 사항으로 명시함.
  Buy & Hold + Simple Momentum 두 baseline으로 최소 요구사항 충족.

## Recent Experiments

(이 섹션은 Phase 9~10 시점 이후 갱신되지 않고 있던 것을 Phase 18에서
현재 상태로 갱신함.) 여전히 실 시장 데이터 기반 실험은 없다 (실 데이터
provider가 없으므로 — ADR-0005, Phase 1부터 이연). Phase 11의
`TrailingWindowMeanTrainer`(Phase 9 baseline과 다른 두 번째
deterministic trainer, ML 의존성 추가 없이 비교/검증/lineage 기계를
실제로 exercise), Phase 18의 `broker.paper.performance` 성과 지표
계산(Sharpe/Sortino/Calmar/drawdown/turnover 등, 목 fixture 기반 pipeline
검증)까지 전부 mechanism 검증 목적이며, 조건부/파생/학습 버전이
baseline보다 우수하다고 주장하지 않는다. Paper Trading을 통한 실제
전략 실험은 아직 수행되지 않았다 — Phase 18이 만든 것은 실험 결과를
평가할 도구(Performance Report)이지 실험 자체가 아니다.

## Current Model / Current Benchmark

Phase 2와 동일한 baseline 전략(Buy & Hold, Simple Momentum) — 변화
없음. Phase 6 baseline predictor 2종, Phase 7
`BaselineRuleDecisionAgent`, Phase 8 `Deterministic*` 사이징/리스크
1쌍, Phase 9 `MeanRewardBaselineTrainer`, Phase 11
`TrailingWindowMeanTrainer` 모두 "현재 채택된 모델"이 아니라 향후
비교의 기준선으로만 존재 — 실제 주문 생성/Live 배포에 연결되지 않는다.
**Phase 20 갱신**: 벤치마크의 PRICE_RETURN vs TOTAL_RETURN DECISION
REQUIRED(Phase 2부터 미결)가 **TOTAL_RETURN으로 결정**됨
(`docs/decisions/ADR-0026-benchmark-return-type.md`) — S&P 500 자체
데이터가 없어 SPY를 proxy로 채택하고, `backtest.total_return.
build_total_return_benchmark_points`로 배당재투자 지수를 실제
구현했다. 하지만 **실제 SPY 가격/배당 데이터는 여전히 이 repository에
전혀 없다**(Tiingo가 provider로 선정되었으나 이 환경에서 실제 네트워크
접근은 검증되지 않음, ADR-0025) — `backtest.benchmark.BenchmarkEngine`/
`broker.paper.performance.BenchmarkComparison` 둘 다 이 경우 정직하게
`None`/`BENCHMARK_UNAVAILABLE`을 반환하도록 이미 설계되어 있으며, 실
데이터가 수집되기 전까지는 계속 그렇게 동작한다.

## Last Validation

(이 섹션은 Phase 9 시점 이후 갱신되지 않고 있던 것을 Phase 18에서
갱신함 — 정확한 현재 수치는 아래 "Current Phase" 섹션 참조.)
`python -m pytest tests/ -q` — Phase 17 종료 시점 1345 passed → Phase
18 종료 시점 최종 수치는 이 문서 상단 "Current Phase" 섹션의 Last
Validation 항목을 참조할 것(이 섹션은 요약이며, 매 세션 정확한 숫자는
상단 Current Phase 섹션에만 기록한다 — 중복 유지로 인한 불일치를
방지하기 위함).

---

## Not Yet Implemented

(이 섹션은 Phase 9~10 시점 이후 갱신되지 않고 있던 것을 Phase 18에서
전면 갱신했고, Phase 20에서 다시 갱신함.)

- 실제 Toss API 주문상태조회/계좌조회/포지션조회/취소 **구현** — 공식
  스펙(Tier 1)은 Phase 20에서 전부 확보/문서화됐으나
  (`docs/operations/TOSS-API-GAP-ANALYSIS.md` Phase 20 addendum),
  `TossBrokerAdapter`/`endpoints.py`/`BrokerOrderStatus` 코드 자체는
  의도적으로 아직 구현하지 않음(다음 권장 Phase로 명시) —
  `CapabilityStatus`는 코드상 여전히 UNKNOWN. Live Trading 활성화
  (`LIVE_TRADING_ENABLED=false` 유지)도 이와 무관하게 여전히 불가.
- 실제 시장 데이터 수집 — Phase 20에서 provider 선정(Tiingo,
  ADR-0025)과 `TiingoDataProvider` 코드는 완성했으나, 이 환경에서
  `api.tiingo.com` 접근 자체가 차단되어 있어 **실제로 수집된 시세가
  단 하나도 없음**. 따라서 실 S&P 500(SPY) 벤치마크 데이터도 여전히
  없음(총수익 계산기(`backtest.total_return`)는 Phase 20에서 구현
  완료, 투입할 실 데이터만 없는 상태).
- Limit order 실사용(Toss 자체는 지원 확인되었으나 상위 레이어에 가격
  소싱 입력이 없음), Purged K-Fold/Embargo(Phase 18 연구 완료,
  `docs/research/walk-forward-pbo-deflated-sharpe.md` — 현재 아키텍처에
  아직 적용 대상 없음), 5종 corporate action 처리
- Prediction/Decision/Sizing/Risk/Learning의 model-based(통계적/ML/AI)
  실제 구현 — 전부 baseline 1~2종만 존재, drop-in 확장 지점만 마련됨
- Sector/Factor limit 실제 검사 — `SecurityMaster`에 해당 데이터 필드
  자체가 없어 구현 불가 (`RiskConfig`에 확장 지점만 예약,
  `docs/operations/LIVE-RISK-POLICY.md` #5)
- 일반화된 Feature Registry
- 실제 Post Trade Analysis 알고리즘의 일부(prediction/timing/risk/regime
  error 등), 모델 기반 Counterfactual — Phase 10에서 구조/일부 채워짐,
  전체 정밀도는 여전히 제한적
- Candidate Model의 APPROVED/DEPLOYED 상태 전이 로직 — 구조적으로
  자동 전이 불가능하도록 설계(Phase 11 ADR-0017, Phase 17/18에서
  저장소 전체 AST 스캔으로 재확인, 사람의 명시적 승인 필수)
- Model Registry / "왜 모델이 변경되었는가" 감사 질문 (Phase 11 lineage로
  일부 충족, 전용 서비스는 미구현 — 의도적, ADR-0017 alternatives #5)
- DuckDB 다중 프로세스 동시 writer 지원
- Regime의 HMM/통계적/ML 기반 확장
- **Paper Trading 자체 성과 리포트의 실제 사용** — Phase 18이 계산
  도구(`broker.paper.performance`)는 만들었으나, 이를 실제 Paper 세션
  운영에 자동으로 연결하는 상시 실행 루프는 없음(Phase 15부터
  "상시 실행 Trading Engine 루프 없음"으로 이미 문서화된 한계)
- Walk-Forward / PBO / Deflated Sharpe Ratio 검증 (Phase 18 연구 완료,
  Phase 20이 구체적 trigger 조건을 추가했으나(§9) 어느 조건도 아직
  발생하지 않아 구현은 여전히 미착수 —
  `docs/research/walk-forward-pbo-deflated-sharpe.md`의 DECISION
  REQUIRED 참조)
- Toss `cancel_order`/`get_order_status`/`get_account`/`get_positions`
  **구현** — Phase 20에서 공식 스펙(Tier 1) 기반 엔드포인트/스키마
  문서화는 완료했으나(`TOSS-API-GAP-ANALYSIS.md`), 어댑터 코드 자체는
  다음 Phase로 의도적으로 미룸(추측 구현 금지 원칙과는 무관 — 이번엔
  공식 문서가 있음에도 별도 Phase로 분리한 것)

---

## Next Recommended Task

(이 섹션은 Phase 9~10 시점 이후 갱신되지 않고 있던 것을 Phase 18에서
전면 갱신했고, Phase 20에서 다시 갱신함. legacy DECISION REQUIRED
항목은 위 "Blocked"/"Current Phase → Decision Required" 섹션에서 계속
추적한다.)

1. **Toss Securities 어댑터를 공식 OpenAPI 스펙(Tier 1, Phase 20에서
   확보/문서화 완료) 기준으로 실제 구현하는 전용 Phase** —
   `TossBrokerAdapter`/`endpoints.py`/`BrokerOrderStatus`에
   ACCOUNT_BALANCE/POSITIONS/ORDER_STATUS/CANCEL_ORDER를 실제로 구현.
   더 이상 "공식 문서가 없어서 못 함"이 아니라 "문서는 있고 구현만
   남음" 상태이므로, 남은 후속 작업 중 가장 명확하고 가치가 큰 단일
   항목이다(`docs/operations/TOSS-API-GAP-ANALYSIS.md` Phase 20
   addendum 참조). 이것이 이번 Phase의 **최우선 권장 다음 작업**이다.
2. **실 Tiingo API 키/네트워크 접근 확보** — 확보되는 즉시:
   (a) `TiingoDataProvider`의 실제 응답 스키마를 Tier 2 문서 기반
   가정과 대조 검증, (b) 16종목 pilot universe 실제 수집, (c) SPY
   실 데이터로 `backtest.total_return`을 실제 실행해 처음으로 진짜
   벤치마크 비교를 만들어낼 것.
3. **Phase 17/18/20에 걸쳐 쌓인 DECISION REQUIRED에 대한 사람의
   판단**: (a) risk policy `None`이 Live를 구조적으로 차단해야 하는지
   여부, (b) daily loss/turnover/order frequency 숫자값 — Phase 20이
   근거를 갖춘 제안값(2%/3.0/30)을 제시했으니 이제 승인/수정만 남음
   (`docs/operations/LIVE-RISK-POLICY.md`), (c) Walk-Forward/PBO/
   Deflated Sharpe 채택 여부 — trigger 조건은 Phase 20이 구체화함
   (`docs/research/walk-forward-pbo-deflated-sharpe.md` §9).
4. **Paper Trading을 실제로 운영하는 상시 실행 루프** 구축 — 실 데이터
   연결 경로는 Phase 20이 구조적으로 증명했으나(`tests/integration/
   test_paper_trading_real_market_data.py`), `PaperTradingSession`/
   `compute_paper_performance_report`를 정기적으로 호출하는 스케줄러는
   여전히 없다. 실 데이터 수집(#2)이 먼저 확보되어야 의미가 있다.
5. 향후 model-based Prediction/Decision/Sizing/Risk/Learning 구현 시
   반드시 각 baseline과 비교해 실제로 가치가 있는지 검증할 것
   (baseline 우선 원칙, 변경 없음).
6. Candidate Model이 실제로 `APPROVED`/`DEPLOYED`로 전이되는 상황이
   생기면, 그 과정이 항상 사람의 명시적 승인을 거치며 AI가 스스로
   부여할 수 없다는 원칙(Master Plan §11.5)이 그대로 유지되는지 매
   Phase마다 재확인할 것 — Phase 17/18/20 모두 이를 저장소 전체
   스캔으로 재확인했다.

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

### Session 5 — 2026-08-24 (Phase 4)
- Master Plan/ADR-0001~0009/Phase 1~3 spec 재조사 (충돌 없음 확인)
- Phase 4 명세, ADR-0010 작성
- Phase 1에 additive 변경 1건 (`AppendableDataRepository` Protocol) —
  기존 202개 테스트 영향 없음 확인
- `src/storage/` (DuckDB+Parquet 영속 저장소 4종 Repository 구현) +
  `src/baseline/` (baseline runner + comparison report) 참조 구현
- Storage 8개 + Baseline 6개 + Integration 2개 카테고리 포함 51개
  테스트 작성, 전체 253개 테스트 전부 통과
- 자체 테스트로 정합성 이슈 2건 발견 및 즉시 수정 (ExperimentTracker
  공유 필요성, ExperienceRecord dedup key — 위 Design Decisions 참조)
- Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
  않다고 판단, 계속 이연 (임의 결정하지 않음)
- 실제 AI API, Toss Securities, Live Trading은 여전히 구현하지 않음

### Session 6 — 2026-08-24 (Phase 5)
- Master Plan/ADR-0001~0010/Phase 1~4 spec/현재 src·tests 재조사
  (충돌 없음 확인)
- Phase 5 명세, ADR-0011 작성
- `src/regime/` 참조 구현: 5개 baseline regime 축(Trend/Volatility/
  Liquidity/Correlation/Stress) deterministic feature 계산,
  RegimeDetector(Phase2 AsOfDataView/BacktestClock 재사용 — 신규
  look-ahead guard 없음), RegimeRepository, 비침습적 Regime↔Trade
  Journal lineage, RegimeConditionedStrategy(alpha 주장 없는 예시적
  conditioning 실험)
- `src/storage/regime_repository.py` — Phase4 DuckDB 카탈로그에 신규
  테이블 2개 추가(기존 테이블 스키마 변경 없음)
- Phase 1~4 소스코드 변경 전혀 없음 (완전히 additive)
- regime 8개 + storage 1개 + integration 1개 카테고리 포함 57개 테스트
  작성, 전체 310개 테스트 전부 통과 (파일명 충돌 발견 및 즉시 수정 —
  `test_backtest_integration.py` → `test_regime_backtest_integration.py`)
- Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
  않다고 판단, 계속 이연 (임의 결정하지 않음)
- 실제 AI API, Toss Securities, Live Trading, LLM 기반 regime 판단은
  구현하지 않음 (지시대로)

### Session 7 — 2026-08-24 (Phase 6)
- **Phase 6 착수 전 Git/Branch Integrity Check 선행 수행** (사용자
  지시) — 단일 선형 히스토리 확인(Initial commit→Phase0→1→2→3→4→5),
  `origin/main`/`origin/claude/autonomous-ai-investment-system-wvscwe`
  모두 현재 HEAD의 조상이며 누락된 커밋 0개, 병합/분기/reset 흔적 없음,
  Phase 1~5 산출물 전부 실존, 310/310 테스트 통과 확인 → PASS 판정
- Master Plan/ADR-0001~0011/Phase 1~5 spec/현재 src·tests 재조사
  (충돌 없음 확인)
- Phase 6 명세(Git Integrity Check 결과 포함), ADR-0012 작성
- `src/predict/` 참조 구현: RandomWalk/Drift deterministic baseline
  predictor 2종(Predictor Protocol), PredictionOutput(order/risk-shaped
  필드 구조적으로 없음), PredictionRepository, 비침습적 Prediction↔Trade
  Journal lineage, RegimeAwarePredictor(alpha 주장 없는 예시적
  Regime-conditioning)
- `src/storage/prediction_repository.py` — Phase4 DuckDB 카탈로그에
  신규 테이블 1개 추가(기존 테이블 스키마 변경 없음)
- Phase 5에 additive rename 1건(`annualized_realized_vol` 공개) —
  Phase 5 기존 48개 테스트 영향 없음 확인. 그 외 Phase 1~5 소스코드
  변경 없음
- predict 7개 카테고리 + storage 1개 + integration 1개 카테고리 포함
  39개 테스트 작성, 전체 349개 테스트 전부 통과 (파일명 충돌 발견 및
  즉시 수정 — `test_point_in_time.py`/`test_version_lineage.py` →
  `test_predict_point_in_time.py`/`test_predict_version_lineage.py`)
- Prediction이 BUY/SELL을 직접 만들지 않음을 reflection 기반 구조
  테스트로 검증 (test_boundary.py)
- Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
  않다고 판단, 계속 이연 (임의 결정하지 않음)
- 실제 AI API, Toss Securities, Live Trading, 학습된 모델 기반
  prediction은 구현하지 않음 (지시대로)

### Session 8 — 2026-08-24 (Phase 7)
- **Phase 7 착수 전 Git/Branch Integrity Check를 이전 세션 PASS
  결과를 재사용하지 않고 처음부터 재수행** (사용자 지시) — 현재
  HEAD(`6c0b0f6`, Phase 6)부터 Phase 0~6 커밋 9개를 `merge-base
  --is-ancestor`로 개별 재확인, 병합 커밋 0개, `origin/main`과
  `origin/claude/autonomous-ai-investment-system-wvscwe` 모두 조상,
  두 branch 모두 HEAD에 없는 커밋 0개, Phase 0~6 산출물 전부 실존,
  349/349 테스트 통과, working tree clean → PASS 판정
- Master Plan/ADR-0001~0012/Phase 1~6 spec/현재 src·tests 재조사
  (충돌 없음 확인)
- Phase 7 명세(Git Integrity Check 결과 포함), ADR-0013 작성
- `src/decision/` 참조 구현: `BaselineRuleDecisionAgent`(Prediction
  필수/Regime은 존재 시에만 게이트/portfolio_state 없으면 fail-closed
  NO_TRADE의 6단계 순차 규칙), `DecisionOutput`(order/risk-shaped
  필드 구조적으로 없음, `trade_journal.enums.DecisionAction` 재사용),
  `DecisionRepository`
- `src/storage/decision_repository.py` — Phase4 DuckDB 카탈로그에
  `decision_outputs` 테이블 신규 추가(Trade Journal의 기존 `decisions`
  테이블과 명칭 충돌 회피, 기존 테이블 스키마 변경 없음)
- Phase 1~6 소스코드 변경 전혀 없음(`schema.py`/`serialization.py`에
  대한 순수 추가만 존재, `git diff | grep '^-'` 결과 두 파일 모두
  삭제/변경 없음으로 확인)
- decision 4개 카테고리(Unit/Boundary/Leakage/Integration) + storage
  1개 + integration 1개 카테고리 포함 40개 테스트 작성, 전체 389개
  테스트 전부 통과 (파일명 충돌 발견 및 즉시 수정 — `test_boundary.py`
  → `test_decision_boundary.py`)
- 미래 데이터 유출 방지 회귀 테스트 신규 작성 — 미래 bar 추가 후 과거
  시점 Decision 재계산 결과가 바이트 단위로 동일함을 확인
- Decision Agent가 quantity/order/broker/risk-bypass를 만들지 않음을
  reflection 기반 구조 테스트로 검증 (`test_decision_boundary.py`)
- Decision↔Prediction↔Regime lineage는 `attach_decision_context`를
  만들지 않고 3-way SQL join으로 증명(ADR-0013 §9 — `ExperienceRecord.
  action`이 이미 실제 체결 ground truth이므로 hypothetical Decision으로
  덮어쓰지 않는다는 의도적 결정)
- Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
  않다고 판단, 계속 이연 (임의 결정하지 않음)
- Position Sizing/Portfolio Risk Engine/Order Creation/Broker/Paper
  Trading/Live Trading/Learning Engine/Model Evolution은 이번 Phase
  범위에서 명시적으로 제외 (지시대로) — 실제 AI API, Toss Securities,
  Live Trading도 여전히 구현하지 않음

### Session 9 — 2026-08-25 (Phase 8)
- **Phase 8 착수 전 Git/Branch Integrity Check를 이전 세션 PASS
  결과를 재사용하지 않고 처음부터 재수행** (사용자 지시) — 현재
  HEAD(`6a1c937`, Phase 7)부터 Phase 0~7 커밋 10개를 `merge-base
  --is-ancestor`로 개별 재확인, 병합 커밋 0개, `origin/main`과
  `origin/claude/autonomous-ai-investment-system-wvscwe` 모두 조상,
  두 branch 모두 HEAD에 없는 커밋 0개, Phase 0~7 산출물 전부 실존,
  389/389 테스트 통과, working tree clean → PASS 판정
- Master Plan/ADR-0001~0013/Phase 1~7 spec/현재 src·tests 재조사
  (충돌 없음 확인)
- Phase 8 명세(Git Integrity Check 결과 포함), ADR-0014 작성
- `src/risk/` 참조 구현: `DeterministicPositionSizer`(confidence/
  volatility/liquidity/cash/risk_budget을 반영한 14단계 순차
  fail-closed 규칙, decision의 target_weight_hint는 어디서도 읽지
  않음), `DeterministicPortfolioRiskEngine`(cash_minimum→
  single_position_limit→gross_exposure→concentration→drawdown→
  portfolio_volatility→turnover→liquidity 순서로 재검사하는 최종
  권한자, single_position_limit은 Position Sizing과 독립적으로
  재검사하는 defense-in-depth), `PositionSizingResult`/
  `PortfolioRiskState`/`RiskCheckedPosition`(order_id/broker_order/
  execution_price 등 order-shaped 필드 구조적으로 없음),
  `PositionSizingRepository`/`RiskRepository`
- `src/storage/risk_repository.py` — Phase4 DuckDB 카탈로그에
  `position_sizing_results`/`risk_assessments` 테이블 신규 추가
  (risk_state는 별도 테이블 없이 payload_json에 내장, 기존 테이블
  스키마 변경 없음)
- Phase 1~7 소스코드 변경 전혀 없음(`schema.py`/`serialization.py`에
  대한 순수 추가만 존재, `git diff | grep '^-'` 결과 두 파일 모두
  삭제/변경 없음으로 확인)
- risk 5개 카테고리(sizing/engine/boundary/leakage/backtest-integration,
  85개) + storage 1개(6개) + integration 1개(3개) 포함 94개 테스트
  작성, 전체 483개 테스트 전부 통과 (파일명 충돌 없음 — 처음부터
  phase-prefixed 이름으로 작성)
- **Phase 2 현금 소진 버그의 전용 regression test 신규 작성**
  (`TestCashSafetyRegression`) — `BuyAndHoldStrategy.
  COST_SAFETY_MARGIN`과 동일한 목적의
  `PositionSizingConfig.cost_safety_margin`을 도입해 재발을 직접 검증
- 미래 데이터 유출 방지 회귀 테스트 신규 작성 — 미래 bar 추가 후 과거
  시점 Sizing/Risk 결과를 전체 체인으로 재계산해도 결과가 동일함을 확인
- Position Sizing/Risk Engine이 quantity/order/broker/execution_price를
  만들지 않음을 reflection 기반 구조 테스트로 검증하고, Phase 7
  DecisionOutput/BaselineRuleDecisionAgent의 경계가 여전히 유지됨을
  재확인 (`test_risk_boundary.py`)
- Sizing↔Risk↔Decision↔Prediction↔Regime lineage는
  `attach_sizing_context`/`attach_risk_context`를 만들지 않고 5-way
  SQL join으로 증명(Phase 7과 동일한 이유 — `ExperienceRecord.action`이
  이미 실제 체결 ground truth)
- Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
  않다고 판단, 계속 이연 (임의 결정하지 않음)
- Order Creation/Validation/Broker/Toss Securities API/Paper Trading/
  Live Trading/Prediction model training/Learning Engine/Model
  Evolution/AI Gateway/Model Registry/Drift Detection은 이번 Phase
  범위에서 명시적으로 제외 (지시대로)

### Session 10 — 2026-08-25 (Phase 9)
- **Phase 9 착수 전 Git/Branch Integrity Check를 이전 세션 PASS
  결과를 재사용하지 않고 처음부터 재수행** (사용자 지시) — 현재
  HEAD(`05ac338`, Phase 8)부터 Phase 0~8 커밋 10개를 `merge-base
  --is-ancestor`로 개별 재확인, 병합 커밋 0개, `origin/main`과
  `origin/claude/autonomous-ai-investment-system-wvscwe` 모두 조상,
  두 branch 모두 HEAD에 없는 커밋 0개, Phase 0~8 산출물 전부 실존,
  483/483 테스트 통과, working tree clean → PASS 판정
- Master Plan/ADR-0001~0014/Phase 1~8 spec/현재 src·tests 재조사
  (충돌 없음 확인). Phase 3 `ExperienceRecord`/`build_experience_records`,
  Phase 4 `ExperienceRepository`/`ExperimentRepository`, Phase 5~8의
  `attach_*_context` 비침습적 lineage 패턴을 실제 코드로 재확인 후 설계
- Phase 9 명세(Git Integrity Check 결과 포함), ADR-0015 작성
- `src/learning/` 참조 구현: `DataCleaner`(provenance mismatch/
  duplicate/NaN·Inf/missing decision/no realized outcome을 VALID/
  INVALID/EXCLUDED/UNKNOWN 4상태로 전부 기록, 절대 조용히 제거하지
  않음), `Labeler`(TradeRecord.realized_return만 label 소스로 사용,
  feature_cutoff_time/label_start_time 구조적 분리), `build_training_dataset`
  (as_of_cutoff로 미래 experience를 cleaning 이전에 배제, 시간순
  non-shuffled train/validation/test split, 실제 sample 내용을 해싱하는
  content-hash dataset_version), `MeanRewardBaselineTrainer`(TRAIN
  split 평균만 사용, VALIDATION/TEST 미접근, 항상
  CandidateModelStatus.CANDIDATE만 생산), `Evaluator`(MAE/MSE + baseline
  비교, candidate_is_better 필드 없음), `LearningExperimentTracker`,
  4종 Repository Protocol + InMemory 구현, `run_learning_pipeline`
  오케스트레이션
- `src/storage/learning_repository.py` — Phase4 DuckDB 카탈로그에
  `training_datasets`/`candidate_models`/`evaluation_results`/
  `learning_experiments` 테이블 + 4개 시퀀스 신규 추가(기존 테이블
  스키마 변경 없음)
- Phase 1~8 소스코드 변경 전혀 없음(`schema.py`/`serialization.py`에
  대한 순수 추가만 존재, `git diff | grep '^-'` 결과 두 파일 모두
  삭제/변경 없음으로 확인)
- learning 9개 카테고리(cleaning/labeling/dataset/trainer/evaluation/
  leakage/provenance/boundary/reproducibility, 58개) + storage 1개(8개)
  + integration 1개(4개) 포함 70개 테스트 작성, 전체 553개 테스트 전부
  통과 (파일명 충돌 발견 및 즉시 수정 — `test_provenance.py` →
  `test_learning_provenance.py`, `tests/trade_journal/test_provenance.py`
  와 충돌)
- **자체 발견 및 수정한 버그 2건**: (1) `dataset_version`이
  `source_experience_ids` 목록만 해싱해 서로 다른 두 journal이 우연히
  동일한 trade_id 시퀀스를 가지면 실제 내용이 달라도 동일 버전이
  나오는 문제 — 실제 sample 내용을 해싱하도록 수정. (2) 동일 원인으로
  storage PRIMARY KEY가 in-process allocator에서 충돌하는 문제 — Phase
  4의 `experience_id_seq` 패턴을 4개 Learning 저장소 모두에 동일하게
  적용해 수정. 전용 regression test
  (`test_two_independent_pipeline_runs_do_not_collide_in_storage`) 추가
- Data Cleaning이 샘플을 절대 조용히 버리지 않음을 검증, 미래 데이터
  유출 방지 회귀 테스트 신규 작성(동일 as_of_cutoff로 재구축한 dataset이
  이후 journal에 미래 experience가 추가되어도 완전히 동일함을 확인)
- Provenance 분리를 `provenance` 파라미터 기본값 미제공으로 구조적으로
  강제, Learning Engine이 order/broker/risk mutation을 만들지 않고
  CandidateModelStatus.APPROVED/DEPLOYED를 생성하는 코드 경로가 전혀
  없음을 reflection + AST 스캔으로 검증
  (`test_learning_boundary.py`)
- Reproducibility 검증 — 동일 dataset/config/seed → 동일 결과,
  `learning/*.py` 어디에도 `random` 모듈 미사용을 AST로 확인
- `LearningExperimentRecord`는 `backtest.experiment.ExperimentRecord`를
  재사용하지 않고 새 타입으로 설계(backtest-특화 필드가 training run과
  맞지 않아 기각) — 저장 패턴은 `storage.experiment_repository`를 그대로
  재사용, 중복된 새 Experiment 시스템을 만들지 않음
- Phase 3의 DECISION REQUIRED 3건 재검토 — 이번 Phase 완료에 필요하지
  않다고 판단, 계속 이연 (임의 결정하지 않음)
- Phase 8의 Known Issue 3건(average_cost proxy/sector-factor 데이터
  부재/turnover 호출자 의존) 재검토 — Learning Engine과 무관, 변경 불필요
- Counterfactual Analysis/Performance Attribution(Phase 10)/Model
  Evolution/Model Registry 완성(Phase 11)/AI Gateway(Phase 12)/Toss
  Securities Adapter(Phase 13)/Monitoring(Phase 14)/Paper Trading
  (Phase 15)/Live Trading(Phase 16)은 이번 Phase 범위에서 명시적으로
  제외 (지시대로) — 학습 결과의 자동 Live 적용, 실제 AI API 호출도
  여전히 구현하지 않음
