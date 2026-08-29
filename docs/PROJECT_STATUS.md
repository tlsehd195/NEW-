# PROJECT STATUS

> 새 Claude Code 세션은 이 파일 하나만 읽어도 현재 프로젝트가 어디까지
> 진행되었는지 파악할 수 있어야 한다. 이 파일은 각 세션 종료 시 반드시
> 최신 상태로 갱신한다.

**Last Updated:** 2026-08-29
**Updated By:** Claude Code (Session 35 — Phase 33: fundamentals data source decision (SEC EDGAR) + provider implementation)

---

## Current Phase

**Phase 16 — Live Trading**는 `PROJECT_MASTER_PLAN.md`에 정의된 원래
마지막 공식 Phase다. **Phase 17/18/19/20/21/22/23/24/25/26/27/28/29/30/31은
Master Plan의 정식 Phase가 아니라, Phase 16 완료 후 실제 Live 전환 전에
발견된 안전성·검증 문제를 보완하고 실 시장 데이터/브로커 기반을 놓기
위한 사후 검증/기반 구축 작업**이며, 이 문서의 "Phase 31" 표기는 세션
추적 편의를 위한 라벨일 뿐 Master Plan의 Phase 목록을 확장하는 것이
아니다. 이 번호들은 전부 사용자 본인이 직접 "PHASE N — ..." 형식으로
명시적으로 지시한 작업이며, Phase 19가 남긴 "AI가 스스로 새 Phase
번호를 발명하지 말라"는 원칙에 대한 예외(사람의 명시적 지시)에 정확히
해당한다.

**REAL MARKET DATA / REAL WALK-FORWARD EXECUTION: NOT COMPLETED —
이 sandboxed 세션 자체는 여전히 `ENVIRONMENT_BLOCKED`, 변화 없음(이번엔
DNS/TCP/HTTP 레이어를 분리해 재확인).** DNS는 3개 주요 host 전부 정상
resolve, 설정된 proxy를 우회한 직접 TCP connect(port 443)도 전부 성공 —
오직 HTTP 요청만 거부됨(`403`/`x-deny-reason: host_not_allowed`). 이는
`AUTHENTICATION_FAILED`(요청이 provider에 도달한 적 없음)도,
`PROVIDER_DOES_NOT_SUPPORT_FEATURE`/`DATASET_DOES_NOT_EXIST`(둘 다 판단
불가)도, `USER_ACCOUNT_LIMITATION`(이 세션에 계정/키 자체가 없음)도
아닌, 정확히 `ENVIRONMENT_BLOCKED`임을 재확인. Nasdaq Data Link,
Polygon, Alpha Vantage, Financial Modeling Prep, CRSP까지 5개 추가
provider host도 동일하게 차단(github.com/pypi.org는 정상). `MARKET_DATA_API_KEY`
미설정.

**Phase 31 — Real Data Acquisition / Historical Universe Data Source
Audit** (Live Trading은 여전히 구조적으로 비활성). 목표는 새 전략을
만들거나 튜닝하는 것이 아니라, 이 프로젝트가 실제로 어떻게 broad
survivorship-aware 2010~최신 US 주식 데이터를 확보할 수 있는지
엄밀하게 규명하고 그 확보를 가능케 하는 인프라를 짓는 것이었다. 실
ingestion/universe/walk-forward는 이번에도 환경 차단으로 수행되지
못함(**FINAL STATUS: VALIDATION BLOCKED — ENVIRONMENT**, 동시에
**EXTERNAL_DATASET_REQUIRED** — ADR-0034 Decision 4). 대신 (1)
`scripts/ingest_real_market_data.py`의 manifest에 남아있던 나머지
공백(`providers_used`/`missing_symbols`/`active_count`/
`historical_universe_membership_available`) 수정, (2) 지침이 요구한
외부 데이터 획득 워크플로우(section 21)를 문서로만이 아니라 실제
동작하는 코드로 구현 — `LocalFileDataProvider`(신규,
`src/data_infra/providers/file_import.py`, 네트워크 호출 전혀 없이
로컬 CSV 파일을 읽음)와 `scripts/import_external_market_data.py`(기존
`IngestionRunner`/`DataQualityFramework`/`DuckDBDataRepository`
파이프라인 그대로 재사용) — 네트워크를 쓰지 않으므로 자동화 테스트가
실제로 end-to-end 실행 가능(이 프로젝트 최초로 실행 가능한 CLI
테스트), (3) `audit_survivorship`(신규,
`src/data_infra/universe.py`) — 지침 section 28의 survivorship 10개
질문에 답하는 FULLY_SUPPORTED/PARTIALLY_MITIGATED/
CURRENT-UNIVERSE-ONLY/UNKNOWN 분류기, "survivorship bias 해결됨"이라는
막연한 주장을 절대 하지 않음, (4) ADR-0034 — 지침이 요구한
VERIFIED_BY_DOCUMENTATION/VERIFIED_BY_ACTUAL_ACCESS/UNKNOWN/
NOT_AVAILABLE/ENVIRONMENT_BLOCKED 어휘로 provider matrix 재작성 +
decision framework 5개 상태 중 실제로 적용되는 것(C+D 동시 적용)을
명시적으로 선택.

### Completed (Session 34 — Phase 32: 결과 심층분석 + ML Research Track 설계)

사용자가 챗지피티 상담 후 받아온 상세 지시문(PHASE 32)을 실행. 새로운
좋은 결과를 만드는 게 목적이 아니라, 기존 40종목 결과를 정직하게
분해하고 TEST-1을 영구 잠그고 ML 트랙의 거버넌스를 먼저 설계하는 게
목적이었음.

- **`TEST-1` 영구 잠금** (`src/strategy_research/locked_windows.py`,
  `docs/decisions/ADR-0041-...md`): 2023-04-28~2026-08-27을 코드
  레벨 상수(`TEST_1`)로 기록(실제 리포트 값 그대로, 재계산 아님) +
  `overlaps_any_locked_window()` 헬퍼로 향후 어떤 전략/ML 모델이든
  이 구간을 다시 train/validation/test로 쓰려 하면 감지 가능하게 함.
  신규 테스트 9개.
- **Track A 결과 분해 도구 신규 구축**
  (`src/strategy_research/result_analysis.py` +
  `scripts/analyze_long_horizon_result.py`): fold 수익률 분포,
  레짐별(walk-forward TRAIN+VALIDATION 구간만) 성과, gross-to-net
  비용 드래그를 리포트 JSON만으로 계산. **중요한 발견**: 이 세션
  체크아웃엔 40종목 실제 리포트 파일이 아예 없음(`data/`는
  gitignore돼 있고 비어있음, 직접 확인) — 그래서 Signal IC와 종목별
  집중도는 `NOT_COMPUTABLE_FROM_REPORT`로 명시하고, 사용자가 이
  스크립트를 실제 리포트에 돌려서 결과를 relay해야 완성됨. 신규 테스트
  24개(locked_windows 9 + result_analysis 13 + CLI 2).
- **Track A 해석적 분석 작성** (STRATEGY-VALIDATION-REPORT.md "Phase
  32 Track A Addendum"): 이미 이 대화에 relay된 데이터만 사용해서
  OBSERVED/INFERRED/HYPOTHESIS/UNKNOWN으로 분류 — 4개 전략 전부
  SPY보다 53~89%p 저조, `trend_volatility`가 거래비용 드래그 최대
  (3.13%), `risk_controlled_momentum`이 손익 대비 최악의 낙폭
  (-39.4% DD로 겨우 +4.0% 수익), PBO 개선과 TEST 저조 사이의 관계를
  "선택 편향 없음"과 "투자할 가치 있음"은 다른 질문이라고 재해석.
  Signal IC/레짐별 TEST 성과/종목 집중도는 UNKNOWN으로 정직하게 남김.
- **ML Research Track 거버넌스 설계** (`docs/research/
  ML-RESEARCH-PROTOCOL.md`, 신규 ML 코드/의존성 0줄): 기존
  `predict/`(Phase 6)·`learning/`(Phase 9, 실은 거래 경험 기반 학습이라
  시장데이터 기반 예측과는 다른 문제)·`evolution/`(Phase 11)·
  `regime/features.py`(Phase 5) 감사 — 놀랍게도 point-in-time 안전
  `Predictor` Protocol과 버저닝 관례는 이미 상당 부분 존재함을 확인.
  Leakage 방지(feature_available_at), TRAIN/VALIDATION/TEST 구조
  (기존 `build_chronological_split` 재사용), 실험 거버넌스/하이퍼파라미터
  예산 추적, 모델 선택을 multiple-testing으로 취급(기존 `compute_pbo`/
  `compute_dsr_for_all_candidates` 재사용 예정), feature/target/model
  registry 스키마(구현은 아직 안 함), 의존성 정책(ADR-0039와 동일 논리로
  지금 numpy/scipy/scikit-learn 등 추가 안 함) 명시. 상태:
  `ML_RESEARCH_PARTIALLY_READY`.
- **브랜치**: `claude/phase-32-result-analysis-ml-research` 신규 생성
  (main에서 분기). Baseline 1834 passed. 보안 스캔: 신규 코드에 API
  키/시크릿/네트워크 호출 전혀 없음(확인됨).
- **사용자가 `analyze_long_horizon_result.py`를 실제 환경에서 실행,
  결과 relay** — 레짐별(BEAR/BULL/NEUTRAL) fold 승률/수익률 확보.
  **핵심 발견**: `risk_controlled_momentum`의 walk-forward BULL fold
  평균수익(1.92%)이 `trend_volatility`(1.15%)보다 오히려 좋았는데도
  held-out TEST(3.3년 연속 상승장)에서는 정반대로 최악(3.99% vs
  22.78%) — "이미 보유 중인 종목엔 추가매수 안 함 + 포지션 상한
  초과분 현금 방치" 가설을 뒷받침(짧은 2개월 fold에선 안 드러나다가
  긴 연속 보유기간엔 누적되는 결함).
- **Signal IC 계산 스크립트 신규 구축**
  (`scripts/compute_signal_ic_from_catalog.py`): 실 DuckDB 카탈로그
  대상으로 `signal_ic.compute_ic_series` 실행. **TEST-1 보호 로직
  내장**(override 플래그 없음) — 기본 `--end`가 `TEST_1.start`이고,
  요청 구간이 TEST-1과 조금이라도 겹치면 즉시 거부(exit 1). 이유:
  `long_term_momentum`/`risk_controlled_momentum`의 `_momentum_score`가
  ADR-0038로 수정됐기 때문에, 지금 코드로 TEST-1 구간 IC를 계산하면
  "수정된 신호가 이미 관측한 TEST에서 잘 맞는지" 확인하는 꼴이 되어
  RULE 0.8 위반. 신규 테스트 7개(TEST-1 거부 로직 포함, 실제 통과).
  종목 집중도(concentration)는 재실행이 필요한데 재실행하면 수정된
  코드로 TEST-1을 다시 건드리게 되므로 새 TEST 구간 생길 때까지
  구조적으로 닫을 수 없는 UNKNOWN으로 문서화(STRATEGY-VALIDATION-
  REPORT.md Section L).
- 전체 테스트: 1865 passed (Phase 32 신규 총 31개: locked_windows 9 +
  result_analysis 13 + analyze CLI 2 + signal_ic CLI 7).
- **사용자가 Signal IC 스크립트를 실제 카탈로그에 실행, 결과 relay —
  가장 중요한 Track A 결론**: `long_term_momentum`/
  `risk_controlled_momentum`가 공유하는 모멘텀 점수의 실제 예측력이
  **거의 0**(mean_ic=-0.0078, IC information ratio=-0.031,
  positive_ic_ratio=51.9% — 동전던지기 수준, 79개 관측치 기준
  2010~2023-04-28). 이걸로 기존 해석이 바뀜: `risk_controlled_
  momentum`의 참사는 "포트폴리오 구성 버그가 좋은 신호를 망친 것"이
  아니라 "애초에 신호 자체가 정보가 거의 없었는데 구성 버그까지
  겹친 것"으로 재해석. STRATEGY-VALIDATION-REPORT.md Section G/Q2
  갱신.
- **다음 가설 2건 추가 구축** (실제 신호가 momentum 하나에서만 실패한
  건지, 규칙 기반 신호 전체가 안 되는 건지 판단하기 위해 — 결과 보기
  전에 미리 정한 가설, ML 착수 전 저비용 검증 우선):
  1. **저변동성 팩터** (`strategy_research.factor_scores.
     low_volatility_score`) — momentum과 무관한, 학계에 독립적으로
     이미 존재하는 가설(low-volatility anomaly). 새 의존성 없음,
     기존 `trim_to_lookback`/`annualized_volatility` 재사용.
     `compute_signal_ic_from_catalog.py --strategy low_volatility`로
     실행 가능.
  2. **`trend_volatility` 필터의 실제 예측력** — boolean 필터라 IC 계산
     불가해서 새 진단 함수 `signal_ic.bucket_return_analysis` 추가
     (필터 통과/탈락 그룹의 forward return 평균 비교). 신규 스크립트
     `scripts/compute_filter_bucket_returns_from_catalog.py`.
  둘 다 momentum IC 스크립트와 동일한 **TEST-1 강제 거부 로직**
  내장(override 없음, 이유 동일 — ADR-0038이 이 필터/점수 윈도우도
  수정했기 때문). 신규 테스트 15개(`bucket_return_analysis` 4 +
  `low_volatility_score` 5 + 두 CLI 스크립트 6). 전체 1880개 통과.
- **두 가설 모두 실제 카탈로그에 실행 완료 — 둘 다 null/음성**
  (2010-01-01~2023-04-28, TEST-1 이전 구간만 사용):
  - **저변동성 팩터**: 80 rebalance dates, mean_ic = **-0.0486**,
    ic_information_ratio = -0.147, positive_ic_ratio = 45.57% — 음의
    방향이지만 79개 관측치 기준 노이즈 대비 작아 "역신호"보다는
    "탐지 가능한 엣지 없음"으로 해석.
  - **`trend_volatility` 필터**: 160 rebalance dates(155개는 양쪽
    그룹 존재), mean_passing_return = 1.10%, mean_failing_return =
    1.89%, mean_spread = **-0.0078**(필터 통과 그룹이 오히려 더
    나쁨 — 필터가 의도한 방향과 반대), positive_spread_ratio =
    47.74%(동전던지기에 가까움).
  - **momentum(기존 -0.0078) + 저변동성 + trend_volatility 필터 =
    독립적으로 선정한 가설 3개 전부 null 또는 음성.** 사후 유리한
    결과가 나올 때까지 가설을 바꿔가며 찾은 것이 아니라(cherry-picking
    아님), 결과를 보기 전에 미리 정한 3개가 전부 실패 — "이 3개 규칙이
    안 통한다"의 근거로는 충분하지만 "규칙 기반 신호 자체가 전부
    안 통한다"까지 일반화할 근거는 아님. `trend_volatility`의 실제
    fold-consistency(76개 중 61% 양의 fold)는 필터의 종목 선별력보다
    2023-2026 TEST 구간이 대체로 BULL 장이었던 것(76 fold 중 54개
    BULL)으로 설명하는 편이 더 타당함 — Q2의 구조적/레짐 설명을
    재확인·강화. `docs/research/STRATEGY-VALIDATION-REPORT.md` Section
    G/Q3 갱신. **다음 방향(사용자 위임)**: 가격/거래량 기반 단순 규칙을
    더 찾는 것은 기대값이 낮다고 판단 — ML 착수 또는 펀더멘털/대체
    데이터 등 다른 데이터 소스 확보 중 하나로 무게중심 이동. 어느
    쪽을 실제로 시작할지는 아직 미결정(문서에도 단정하지 않고 옵션만
  기록).

### Completed (Session 35 — Phase 33: 펀더멘털 데이터 소스 결정 + 프로바이더 구현)

- **"ML vs 다른 데이터 소스" 방향 결정 (사용자 요청 — "어떤 방향이 우리
  프로젝트 완성에 더 좋다고 생각해?")**: 다른 데이터 소스(펀더멘털)
  먼저를 추천 — 실패한 3개 가설이 전부 가격/거래량 파생 신호였기 때문에
  같은 정보원 위에 ML을 얹어봤자 얻을 정보가 없고, 40종목·13년 규모는
  ML 학습 표본으로도 작아 오히려 과적합 위험(16종목 시절 PBO 62.86%
  선례)만 키운다는 논리. "새 정보원 확보 → 신호 검증 → 신호가 있으면
  그때 ML로 결합"이 올바른 순서라고 판단. 사용자 승인("ㄱㄱ") 후 즉시
  착수.
- **펀더멘털 데이터 소스 접근성 재확인 — 역시 `ENVIRONMENT_BLOCKED`**:
  이 세션(원격 실행 환경)에서 `data.sec.gov`(SEC EDGAR),
  `www.sec.gov`, `www.alphavantage.co`, `financialmodelingprep.com`,
  `stooq.com`에 직접 curl 시도 — 전부 프록시 단계에서 `403`
  (`connect_rejected`, `policy denial`)으로 차단. ADR-0034가 가격
  데이터 프로바이더 전체에 대해 이미 확인한 것과 동일한 패턴이
  펀더멘털 소스에도 예외 없이 적용됨을 재확인 — 이 환경 자체의
  egress allowlist 제약이지 특정 프로바이더의 문제가 아님.
- **소스 선정: SEC EDGAR (XBRL company facts API)** — 무료·API 키 불필요
  (미국 정부 공식 데이터, 지금까지 평가한 모든 상업 프로바이더의
  무료 티어 제약 문제를 원천적으로 피함), 원본 출처(모든 상업
  펀더멘털 프로바이더가 결국 SEC 공시 데이터를 재가공한 것),
  무엇보다 **각 재무 수치에 실제 `filed`(공시 제출일) 필드가 붙어
  있어 point-in-time 안전성이 원천적으로 확보됨** (분기말 시점과
  실제 공시일 사이 수 주의 시차 — 이 프로젝트의 ADR-0004 point-in-time
  원칙과 정확히 같은 문제를 소스 자체가 이미 구조적으로 해결).
  상세 근거·트레이드오프는 `docs/decisions/ADR-0042-fundamentals-
  data-source-selection.md` 참조.
- **`SecEdgarFundamentalsProvider` 구현 (Tier 2 문서 기반, `TiingoDataProvider`와
  동일한 패턴 — 실제 네트워크 검증 전에도 코드 선(先) 구축)**:
  - `src/data_infra/fundamentals_models.py` — 새 도메인 모델
    `FundamentalRecord` (`PriceBar`/`CorporateAction`과 병렬 구조).
    핵심 불변식: `available_time`(실제 공시일)이 `period_end`(보고
    기간 종료일)보다 이를 수 없음 — `__post_init__`에서 강제.
  - `src/data_infra/providers/sec_edgar_config.py`,
    `sec_edgar_transport.py`, `sec_edgar.py` —
    `tiingo_config.py`/`tiingo_transport.py`/`tiingo.py` 구조를 그대로
    미러링. `DataProvider` Protocol은 의도적으로 미구현(가격 바 형태에
    맞춘 인터페이스라 공시 기반 소스와 형태가 안 맞음 — 이유는
    `sec_edgar.py` 모듈 docstring에 명시). SEC의 fair-access 정책이
    요구하는 User-Agent 헤더 처리 포함.
  - `resolve_cik(ticker, ticker_map)` — 순수 함수, 네트워크 없이
    ticker→CIK(10자리 zero-padded) 변환.
  - 신규 테스트 42개 (`test_fundamentals_models.py`,
    `test_sec_edgar_transport.py`, `test_sec_edgar_config.py`,
    `test_sec_edgar_provider.py`) — 전부 `urllib.request.urlopen`
    monkeypatch, 실제 네트워크 절대 미접근(기존 Tiingo 테스트와 동일
    원칙). 전체 1922개 통과.
  - **아직 안 한 것 (명시적으로 유보)**: 실제 ingestion/저장 계층
    (`FundamentalRepository`류), raw concept → 비율(P/E, ROE 등)
    변환, 40종목에 대해 어떤 concept을 실제로 가져올지 확정 — 전부
    실제 EDGAR 접근이 검증된 뒤로 미룸(ADR-0039와 동일한 "성급한
    스키마 설계 방지" 논리).
- **실제 접근 검증 완료 (같은 세션 내, 사용자가 자신의 환경에서 실행)**:
  사용자가 ADR-0042의 curl 명령을 자신의 네트워크 가능 환경에서 실제
  실행 — `data.sec.gov`가 실제로 응답함(`{"cik":320193,"entityName":
  "Apple Inc.","facts":{"dei":{...`). 이 프로젝트가 지금까지 어떤
  프로바이더에 대해서도 얻어본 적 없는 첫 `VERIFIED_BY_ACTUAL_ACCESS`
  결과(ADR-0025~0041은 전부 Tier 2 문서 또는 `ENVIRONMENT_BLOCKED`였음).
  이 원격 세션 자체는 여전히 차단되어 있음 — `ENVIRONMENT_BLOCKED`는
  이 컨테이너 고유의 egress allowlist 문제이지 SEC EDGAR 자체의
  가용성 문제가 아님이 실측으로 확정됨. 최상위 응답 구조(`cik`/
  `entityName`/`facts`→taxonomy→concept)는 확인됐지만, `us-gaap`
  concept의 `units` 배열 안 필드명(`end`/`val`/`accn`/`fy`/`fp`/
  `form`/`filed`)까지는 아직 미확인(처음 요청이 `head -c 500`에
  잘려서). ADR-0042에 후속 확인 명령 추가 기록 — relay 대기 중.

### Completed (Session 33 — Phase 31 continued)

- **40종목(RESEARCH_UNIVERSE_STAGE2) 실 재검증 결과 수신·기록**: 사용자가
  자신의 네트워크 가능 환경에서 `run_long_horizon_validation.py
  --universe RESEARCH_UNIVERSE --data-status REAL`(2010-01-01~
  2026-08-27, 4개 전략 x 76 fold)와 `compute_pbo_dsr_from_report.py`를
  실행해 relay — 상세는
  `docs/research/STRATEGY-VALIDATION-REPORT.md`의 "40-Symbol
  (RESEARCH_UNIVERSE Stage 2) Re-Validation" 절 참조. 핵심: PBO가
  16종목 62.86% → 40종목 0.00%로 급락(집중도 리스크 가설이 옳았음을
  시사), 그래도 4개 전략 전부 여전히 CANDIDATE 미달
  (`trend_volatility`가 DSR 0.93로 0.95 기준에 가장 근접). **새 발견**:
  held-out TEST(2023-04-28~2026-08-27, SPY +93.1%) 구간에서 4개 전략
  전부 SPY 단순 보유보다 큰 폭으로 저조(`risk_controlled_momentum`은
  net CAGR 1.2%에 불과) — PBO/DSR 통과가 "우연이 아니다"는 뜻이지
  "투자할 가치가 있다"는 뜻이 아님을 실측으로 확인. 코드 비교로
  `risk_controlled_momentum`의 구조적 원인(포지션 상한 초과분 미재분배
  + 신규 종목만 매수해 이미 보유 중인 momentum 리더에 추가 투입 안 함)도
  진단·기록 — RULE 0.8에 따라 이 TEST 구간에 대해서는 로직을 고치지
  않고 진단만 기록함(같은 held-out 구간에 대한 사후 수정은 금지).
- **가산적 진단 지표 4종 추가** (전략 로직 미변경, stdlib만 사용):
  낙폭 지속기간/회복일수(`backtest.metrics.compute_drawdown_episodes`),
  신호 예측력 rank IC(`strategy_research.signal_ic`), 종목별 손익
  집중도/HHI(`backtest.contribution`), Ulcer Index·역사적
  VaR/CVaR·연속 승/패 스트릭(`backtest.metrics`) — quantstats/
  empyrical/mlfinlab 실제 코드를 clone해 비교 검증(mlfinlab은 상업
  라이선스라 미사용, quantstats의 PSR 공식에서 첨도 처리 버그 발견 →
  오히려 이 프로젝트 자체 구현이 맞다는 것을 재확인).
- **`DuckDBDataRepository` 성능 수정**: `get_bars`/`get_corporate_actions`가
  체크포인트 x 종목마다 매번 parquet 디렉토리 전체를 다시 글롭·쿼리하던
  구조적 비효율을 발견(40종목 walk-forward가 4시간 넘게 걸린 주 원인으로
  추정) — 종목별 전체 데이터를 인스턴스당 1회만 로드해 메모리에 캐시하고
  이후 호출은 Python에서 `as_of_time`/날짜 필터만 재적용하는 방식으로
  변경. Point-in-time 정확성은 캐시가 "필터링 전 원본"만 보관하고
  필터는 매 호출 그대로 재적용하므로 100% 보존. `append_bars`/
  `add_corporate_action`에서 해당 종목 캐시를 무효화해 stale read 방지.
  신규 회귀 테스트 3개(쓰기 후 캐시 무효화, 종목별 캐시 격리) 포함 전체
  1823개 테스트 통과.
- **보류했던 gs-quant 발견사항 1건 적용 — 모멘텀/이동평균/변동성 윈도우
  희석 버그 수정** (`docs/decisions/ADR-0038-momentum-window-trim-fix.md`):
  `long_term_momentum`/`risk_controlled_momentum`/`trend_volatility`
  전부, lookback 쿼리에 준 캘린더-일 padding(`*1.6`~`*2`)을 실제 신호
  계산 윈도우로 그대로 써버려서 `lookback_months` 등 파라미터가
  명시한 것보다 약 1.4~1.6배 넓은 기간으로 모멘텀/이동평균/변동성을
  계산하고 있던 실제 버그 발견 — gs-quant의
  `timeseries.moving_average`/`volatility`(정확한 크기의 윈도우 사용)와
  비교해서 발견. `strategy_research._dates.trim_to_lookback()` 신규
  추가해 3개 전략 전부에 적용(파라미터 값은 전혀 안 건드림, 윈도우
  계산만 원래 의도대로 수정 — 튜닝이 아니라 정합성 수정). **RULE 0.8
  준수**: 이미 관측된 2023-2026 held-out TEST 구간에 대해서는 수정된
  전략을 재평가하지 않음(같은 TEST 셋 재사용 금지) — 향후 이 3개
  전략의 실제 효과를 알려면 새로운, 아직 관측 안 된 TEST 구간이 필요.
  기존 synthetic IC 테스트 1개의 기대값이 정당하게 변경됨(0.5 →
  -1/6, 여전히 부분적 IC — 회귀 아님, 주석으로 설명). 신규 테스트
  5개(`trim_to_lookback` 자체) 포함 전체 1828개 통과.
- **보류했던 gs-quant 발견사항 2건 중 나머지 1건도 재검증 후 적용 —
  NaN/Infinity 데이터 품질 가드 추가**
  (`docs/decisions/ADR-0040-non-finite-value-data-quality-check.md`):
  compaction 이전 기억이 불확실해서 지난번엔 억지로 적용 안 하고
  건너뛰었던 항목 — 이번에 gs-quant의 pandas 기반 `timeseries`(자동
  NaN 전파/제외)와 다시 비교해서 처음부터 재검증. 실제 갭 확인:
  `DataQualityFramework`의 기존 숫자 체크(`negative_or_zero_price`,
  `ohlc_consistency`, `impossible_price_movement`)가 전부 단순 비교
  연산자를 쓰는데, NaN과 비교하면 항상 `False`가 나와서 NaN이 조용히
  전부 통과됨(회귀 테스트로 직접 증명). `_check_non_finite_values`
  신규 추가(CRITICAL 등급), 데이터 품질 경계에서만 작동 — 전략/파라미터
  전혀 안 건드림. 신규 테스트 6개 포함 전체 1834개 통과.
- **포트폴리오 최적화 라이브러리 도입 보류 결정**
  (`docs/decisions/ADR-0039-defer-portfolio-optimization-library.md`):
  40종목 결과(4개 전략 전부 CANDIDATE 미달 + held-out TEST에서 SPY
  대비 큰 폭 저조)를 근거로 PyPortfolioOpt/Riskfolio-Lib 지금 도입
  안 하기로 결정 — 아직 검증된 신호가 하나도 없는데 신호 간 배분을
  최적화하는 건 의미가 없고, 이 프로젝트는 지금 한 번에 전략 1개만
  돌리므로 배분 문제 자체가 아직 실존하지 않음. `risk_controlled_
  momentum`의 배분 로직 버그가 오히려 "배분 기법을 더할수록 실수
  가능성도 커진다"는 반증 사례. 재검토 조건 명시(전략 1개 이상
  CANDIDATE 도달 + 동시에 여러 신호 운용 계획 확정 시).

### Completed (Session 32 — Phase 31)

- **Git/Branch Integrity 선행 확인**: 로컬 HEAD가 Phase 30 HEAD
  (`0305fb3`)와 정확히 일치함(현재 브랜치의 직접 부모)을 확인 →
  `claude/phase-31-real-data-source-and-acquisition` 브랜치 신규 생성.
  전체 히스토리에 merge commit 0개. Baseline **1687/1687 테스트 통과**
  실제 실행으로 확인.
- **네트워크 재확인(DNS/TCP/HTTP 레이어 분리)**: 3개 주요 host 전부
  DNS 정상, TCP 성공, HTTP만 거부 확인 — `ENVIRONMENT_BLOCKED`를
  `AUTHENTICATION_FAILED`/`PROVIDER_DOES_NOT_SUPPORT_FEATURE`/
  `DATASET_DOES_NOT_EXIST`/`USER_ACCOUNT_LIMITATION`과 명확히 구분.
  추가 5개 provider host 동일 결과.
- **Ingestion manifest 추가 공백 수정**: `providers_used`(실제
  persist된 bar의 `provenance.source`에서 계산), `missing_symbols`(0
  bar로 끝난 요청 심볼), `active_count`,
  `historical_universe_membership_available`/
  `survivorship_mitigation_applied`(실제 provider-confirmed 날짜가
  있었는지 여부 — `delisted_count`가 0인 이유가 "실제로 상장폐지가
  없어서"인지 "애초에 실 날짜가 입력된 적이 없어서"인지 구분). 신규
  AST 기반 회귀 테스트 7개(파일 전체는 Phase 30의 8개 + 이번 7개 =
  15개).
- **외부 데이터 획득 워크플로우 실제 구현(지침 section 21)**:
  `LocalFileDataProvider`(`src/data_infra/providers/file_import.py`)
  — 사전 다운로드·정규화된 CSV 파일을 읽는 `DataProvider` Protocol
  구현체, 네트워크 호출 전혀 없음. 문서화된 하나의 CSV 스키마만
  이해(실제 CRSP/Nasdaq Data Link bulk 파일 형식을 추측하지 않음 —
  사용자의 전처리 책임으로 명확히 분리). `source_name`은 호출자가
  정직하게 공급해야 하며 `Provenance.source`가 됨(하드코딩/추측 없음).
  `scripts/import_external_market_data.py`가 이를 기존
  `IngestionRunner`/`DataQualityFramework`/`DuckDBDataRepository`
  파이프라인에 그대로 연결. 네트워크가 없으므로 이 스크립트는
  자동화 테스트가 `main()`을 직접 호출해 실제 end-to-end 실행 —
  `ingest_real_market_data.py`가 절대 갖지 못하는 테스트 강도.
  신규 테스트 14개(provider 단위 11개 + CLI end-to-end 3개).
- **`audit_survivorship` 신규**
  (`src/data_infra/universe.py`): 지침 section 28의 10개 survivorship
  진단 질문에 답하고
  FULLY_SUPPORTED/PARTIALLY_MITIGATED/CURRENT-UNIVERSE-ONLY/UNKNOWN
  중 하나로 분류. "permanent ID 100%"가 구조적 보장일 뿐 실제
  provider-confirmed 값이 아님을 명시(이 프로젝트는 현재
  `security_id == ticker`), RENAMED/MERGED 카운트를 데이터 소스가
  없으면 절대 추측하지 않고 정직하게 0으로 유지. 신규 테스트 6개.
- **ADR-0034 신규**: ADR-0033의 provider 사실관계를 재인용하며 지침이
  요구한 confidence label 어휘로 매트릭스 재작성, 이번 phase의 8-host
  네트워크 재확인을 `ACCESS STATUS` 열로 명시적으로 추가, decision
  framework(5개 상태) 중 C(EXTERNAL_DATASET_REQUIRED)와
  D(ENVIRONMENT_BLOCKED)가 서로 다른 레이어에서 동시에 성립함을 근거와
  함께 명시적으로 선택(가장 편리한 답을 고르지 않음).
- **기존 1687개 테스트 전부 유지** — 최종 테스트 카운트는 이 phase의
  최종 pytest 실행 결과를 따른다(아래 Last Validation 참조).
- **신규 문서**: ADR-0034,
  `docs/research/STRATEGY-VALIDATION-REPORT.md` Phase 31
  Addendum(지침 section 40의 15개 질문 전부 답변). README.md/
  PROJECT_STATUS.md/PRODUCTION-READINESS-MATRIX.md/MARKET-DATA-PROVIDER.md
  갱신(이 항목).
- **Toss/Live 활성화 코드, RiskConfig 숫자, 새 전략 추가, parameter
  tuning, `src/broker/`/`src/risk/`/`src/learning/`/`src/evolution/`/
  `src/ai_gateway/` 전부 무수정.**

### In Progress (Session 32 — Phase 31)

없음 — 이번 세션 작업 완료.

### Blocked (Session 32 — Phase 31)

- 이 sandboxed 세션 자체의 실 시장데이터 접근 — Phase 26-30과 동일한
  원인(network egress allowlist), 이번엔 8개 provider host + DNS/TCP/HTTP
  레이어 분리로 재확인. 변화 없음.
- 2010~최신 broad survivorship-aware universe 실 ingestion 및 실
  Walk-Forward 실행 — 위 항목에 종속. 이 데이터는 어느 환경에도 존재한
  적 없음. ADR-0034 Decision 4: EXTERNAL_DATASET_REQUIRED(무료/기존
  통합 provider 어느 것도 delisted+historical membership을 제공하지
  않음)도 동시에 성립 — 네트워크가 뚫려도 이 문제는 별도로 남는다.

### Decision Required (Session 32 — Phase 31)

1. (Phase 17-30에서 이어짐) 전부 변경 없음.
2. **(이어짐)** 2010~최신 broad universe 실 ingestion을 언제/어떻게
   수행할지 — network egress allowlist 해결이 선행 조건이지만, 그것만
   으로는 충분하지 않음(ADR-0034: survivorship-aware 데이터는 유료
   tier 또는 CRSP급 기관 데이터가 필요). 사용자가 외부 환경에서
   데이터를 확보 → `scripts/import_external_market_data.py`로 이
   저장소에 import하는 경로가 이제 실제로 존재함(이번 phase 신규).

### Known Issues (Session 32 — Phase 31)

- Phase 30까지의 Known Issues 전부 유지. 이번 phase가 발견한 gap
  (ingestion manifest의 providers_used/missing_symbols/active_count/
  historical_universe_membership_available 누락)은 이미 수정·회귀
  테스트 추가됨.

### Architecture Changes (Session 32 — Phase 31)

`src/data_infra/providers/file_import.py`(신규, additive),
`scripts/import_external_market_data.py`(신규, additive),
`src/data_infra/universe.py`(`audit_survivorship` 신규 함수 추가,
additive), `scripts/ingest_real_market_data.py`(manifest 필드 추가,
additive). 그 외 `IngestionRunner`/`DataQualityFramework`/
`DuckDBDataRepository`/`backtest.engine`/`strategy_research.*`는 전부
무수정(기존 파이프라인을 그대로 재사용).

### Toss API Status (Session 32 — Phase 31)

변경 없음: `CapabilityStatus` 전부 `UNKNOWN` 유지.

### Last Validation (Session 32 — Phase 31)

`python -m pytest tests/ -q` — baseline **1687 passed**(코드 변경 전
직접 실행 확인) → 최종 **1714 passed**(신규 27개: ingestion manifest
wiring 추가 7 + file import provider 11 + import CLI end-to-end 3 +
survivorship audit 6). 기존 1687개 테스트 전부 삭제/약화 없이 유지.

### Next Task (Session 32 — Phase 31)

1. workspace/environment 관리자가 network egress allowlist에 실
   provider host를 추가 — 이 세션 자체에서 실 데이터 확보의 유일한
   직접 경로(단, 그것만으로 survivorship-aware 데이터가 저절로
   생기지는 않음 — ADR-0034 참조).
2. **(신규, 가장 우선순위 높음)** 사용자가 외부 네트워크 접근 가능
   환경에서 ADR-0034의 매트릭스를 참고해 실제 provider/데이터셋을
   선택·확보하고, `data_infra.providers.file_import` 모듈이 문서화한
   CSV 스키마로 전처리한 뒤, `scripts/import_external_market_data.py`로
   이 저장소에 import — 이 경로는 이번 phase에 실제로 구현·테스트됨.
3. Import된 데이터에 대해 `audit_survivorship`을 실행해 정직한
   survivorship 분류를 확인한 뒤에만 `run_long_horizon_validation.py
   --data-status REAL`로 실 Walk-Forward 진행.
4. 그 전까지는 사용자가 이미 보유한 2023-2024 실 데이터로도 동일한 CLI를
   외부 환경에서 실행하는 것이 가장 빠른 실 evidence 확보 경로(변경
   없음).

## Previous Subtask (Session 31 — Phase 30)

**REAL MARKET DATA / REAL WALK-FORWARD EXECUTION: NOT COMPLETED —
이 sandboxed 세션 자체는 여전히 `BLOCKED_BY_ENVIRONMENT` +
`BLOCKED_BY_DATA`, 변화 없음(재확인함, 이번엔 더 넓은 provider host
집합으로).** Tiingo/Stooq/Toss 외에 Nasdaq Data Link, Polygon, Alpha
Vantage, Financial Modeling Prep, CRSP까지 총 5개 추가 후보 provider
host를 테스트했으나 전부 동일한 `x-deny-reason: host_not_allowed`로
차단됨 — 반면 github.com/pypi.org는 동일 세션에서 정상 응답, 이는 이
환경의 차단이 시장 데이터 provider에 국한된 allowlist이지 전체 네트워크
장애가 아님을 확인해준다. `MARKET_DATA_API_KEY` 미설정 확인. 전체
파일시스템 재탐색 — 실 데이터 없음, 변화 없음.

**Phase 30 — Real Historical US Equity Dataset Acquisition,
Survivorship-Aware Dataset Validation, and Full Walk-Forward
Execution** (Live Trading은 여전히 구조적으로 비활성). 목표는
"survivorship-aware 아키텍처는 있지만 실 broad 검증은 막혀있다"에서
"실 데이터가 확보·검증되어 기존 walk-forward 파이프라인을 실제로
실행할 수 있다"로 넘어가는 것이었으나, 환경 네트워크 차단이 근본적으로
동일해 실 ingestion/universe/walk-forward는 이번에도 수행되지 못함
(**FINAL STATUS: VALIDATION BLOCKED — ENVIRONMENT**). 대신 (1)
`scripts/ingest_real_market_data.py`의 manifest가 요청한 날짜 범위만
기록하고 실제로 관측된 날짜 범위(`actual_data_start`/`actual_data_end`)는
전혀 기록하지 않던 실제 gap을 발견·수정(지침 section 16의 "2010 coverage를
날조하지 말라" 요구사항에 직접 대응), (2) 지침 section 8의 CASE A-G를
그대로 이름 붙인 회귀 테스트 8개 추가(새 메커니즘 아님, Phase 1/29
메커니즘의 직접 traceability용), (3) ADR-0033으로 7개 후보 provider의
역량을 지침이 요구한 6개 차원에서 분류(공개 문서 기반, 실 API 응답으로
검증된 적 없음).

### Completed (Session 31 — Phase 30)

- **Git/Branch Integrity 선행 확인**: 로컬 HEAD가 Phase 29 HEAD
  (`2d56283`)와 정확히 일치함(현재 브랜치의 직접 부모)을 확인 →
  `claude/phase-30-real-dataset-acquisition-and-walk-forward` 브랜치
  신규 생성. 전체 히스토리에 merge commit 0개 확인. Baseline
  **1671/1671 테스트 통과** 실제 실행으로 확인(어떤 코드도 변경하기
  전에 먼저 실행).
- **인프라 감사(새로 만들기 전에 먼저 확인)**: `DataQualityFramework`가
  지침 section 15가 요구하는 체크(duplicate records, OHLC consistency,
  negative/zero price, negative volume, impossible price movement,
  missing timestamp gaps, split/dividend consistency,
  ingestion-precedes-availability, insufficient coverage)를 이미
  전부 구현함을 직접 코드로 확인. `valid_from < valid_to`는 이미
  `SecurityMaster`/`UniverseMembership` 생성 시점에 구조적으로
  강제됨(`ValueError`). `IngestionRunner`가 이미 checkpointing,
  retry/backoff, idempotent 재실행, 심볼별
  SUCCESS/PARTIAL_SUCCESS/FAILED 리포팅(지침 section 14)을 전부
  구현함을 확인 — 전부 Phase 1/20-22부터 무수정. 새 quality check나
  ingestion retry 코드는 필요하지 않았음.
- **네트워크 재확인(이전 phase보다 더 넓은 provider 집합)**:
  Tiingo/Stooq/Toss 외에 Nasdaq Data Link, Polygon, Alpha Vantage,
  Financial Modeling Prep, CRSP까지 5개 추가 host 테스트 — 전부 동일한
  `403`/`host_not_allowed`. github.com/pypi.org는 동일 세션에서 정상
  응답(`200`) — 시장 데이터 provider에 국한된 allowlist임을 확인.
  `MARKET_DATA_API_KEY` 미설정. 전체 파일시스템 재탐색 — 실 데이터
  없음.
- **Ingestion manifest 실제 공백 발견·수정(지침 section 16)**:
  `scripts/ingest_real_market_data.py`의 manifest가 요청한
  `start`/`end`만 기록하고 실제로 provider가 반환한 날짜 범위는 전혀
  기록하지 않던 문제 — provider가 요청보다 짧은 기간만 보유한 경우
  이를 구분할 방법이 없어 "2010부터 커버함" 같은 거짓 주장을 초래할 수
  있었음. `actual_data_start`/`actual_data_end`(실제 저장된 bar의
  timestamp에서 계산, bar가 없으면 `None`), `delisted_count`(실제
  저장된 `SecurityMaster.status`에서 계산), `data_status: "REAL"`
  필드 추가. 기존 모호했던 `start`/`end` key는
  `requested_start`/`requested_end`로 이름 변경(구 key 유지하며 추가
  아님). ACTUAL_DATA_START/END는 stdout에도 출력. 신규 AST 기반 회귀
  테스트 8개(`tests/data_infra/test_ingest_real_market_data_wiring.py`
  — 이 스크립트는 실 네트워크를 호출하므로 자동화 테스트가 절대
  실행/import하지 않음, `run_long_horizon_validation.py` wiring
  테스트와 동일한 방식).
- **CASE A-G 회귀 테스트 신규 8개(지침 section 8)**:
  `tests/data_infra/test_phase30_survivorship_cases.py` — 새 메커니즘
  아님(Phase 1/29의 `SecurityMaster`/`UniverseMembership`/
  `get_universe(as_of_time=...)` 그대로 재사용), 지침이 명시한 7개
  CASE 각각에 이름으로 직접 대응하는 테스트를 만들어 향후 감사자가
  CASE→테스트를 1:1로 추적할 수 있게 함(Phase 26의 CASE 5 패턴과 동일
  원칙).
- **ADR-0033 신규**: Tiingo/Stooq/Nasdaq Data Link/Polygon/Alpha
  Vantage/Financial Modeling Prep/CRSP 7개 provider를 지침이 요구한 6개
  차원(historical prices, delisted, ticker changes, corporate actions,
  historical universe membership, point-in-time metadata,
  licensing/access)에서 REALISTIC/PARTIAL/INSUFFICIENT/UNKNOWN으로
  분류 — 이번 세션의 web search로 얻은 공개 문서 기반(출처 인라인
  명시), 실 API 응답으로 검증된 적 없음. 지침 section 5의 "3가지
  universe 개념" 구분(price universe/tradable universe/index
  constituent universe)도 문서화 — 기존 코드가 이미 이 구분을
  지키고 있음을 확인만 함(코드 변경 없음).
- **기존 1671개 테스트 전부 유지** — 최종 테스트 카운트는 이 phase의
  최종 pytest 실행 결과를 따른다(아래 Last Validation 참조).
- **신규 문서**: ADR-0033,
  `docs/research/STRATEGY-VALIDATION-REPORT.md` Phase 30
  Addendum(지침 section 33의 15개 질문 전부 답변). README.md/
  PROJECT_STATUS.md/PRODUCTION-READINESS-MATRIX.md/MARKET-DATA-PROVIDER.md
  갱신(이 항목).
- **Toss/Live 활성화 코드, RiskConfig 숫자, 새 전략 추가, parameter
  tuning, `src/broker/`/`src/risk/`/`src/learning/`/`src/evolution/`/
  `src/ai_gateway/` 전부 무수정.**

### In Progress (Session 31 — Phase 30)

없음 — 이번 세션 작업 완료.

### Blocked (Session 31 — Phase 30)

- 이 sandboxed 세션 자체의 실 시장데이터 접근 — Phase 26-29와 동일한
  원인(network egress allowlist), 이번엔 5개 추가 provider host로도
  재확인. 변화 없음.
- 2010~최신 broad survivorship-aware universe 실 ingestion 및 실
  Walk-Forward 실행 — 위 항목에 종속. 이 데이터는 어느 환경에도 존재한
  적 없음(사용자의 Codespaces 환경도 2023-2024만 보유).

### Decision Required (Session 31 — Phase 30)

1. (Phase 17-29에서 이어짐) 전부 변경 없음.
2. **(이어짐)** 2010~최신 broad universe 실 ingestion을 언제/어떻게
   수행할지 — network egress allowlist 해결이 선행 조건. ADR-0033이
   후보 provider들을 정리했으나 어느 것도 이 세션이 스스로 선택할 수
   있는 문제가 아님(라이선스/비용 결정, 사용자 몫).

### Known Issues (Session 31 — Phase 30)

- Phase 29까지의 Known Issues 전부 유지. 이번 phase가 발견한 유일한
  gap(ingestion manifest의 actual_data_start/end 누락)은 이미
  수정·회귀 테스트 추가됨.

### Architecture Changes (Session 31 — Phase 30)

`scripts/ingest_real_market_data.py`(manifest에
`actual_data_start`/`actual_data_end`/`delisted_count`/`data_status`
필드 추가, `start`/`end` key를 `requested_start`/`requested_end`로
이름 변경 — 순수 additive/명확화, 실제 ingestion 로직 무변경). 그
외 `src/data_infra/*`, `backtest.engine`, `strategy_research.*`,
`storage.data_repository`는 전부 무수정(감사만 수행, 이미 올바르게
동작함을 확인).

### Toss API Status (Session 31 — Phase 30)

변경 없음: `CapabilityStatus` 전부 `UNKNOWN` 유지.

### Last Validation (Session 31 — Phase 30)

`python -m pytest tests/ -q` — baseline **1671 passed**(코드 변경 전
직접 실행 확인) → 신규 테스트 16개(ingestion manifest wiring 8 + CASE
A-G 8) 추가 후 최종 실행 결과는 이 문서 갱신 시점의 실제 pytest 실행을
따른다(아래 "최종 검증" 절차 참조). 기존 1671개 테스트 전부
삭제/약화 없이 유지.

### Next Task (Session 31 — Phase 30)

1. workspace/environment 관리자가 network egress allowlist에 실
   provider host(ADR-0033 기준 Tiingo 유지 또는 대안 선택)를 추가 —
   이 세션 자체에서 실 데이터 확보의 유일한 경로.
2. 선택한 provider의 실제 계정으로 무료/유료 tier 한도를 실제로 확인
   — broad universe 규모 결정의 선행 조건.
3. 위 두 조건이 충족되면: `fetch_symbol_metadata`로 broad universe
   discovery Stage 1 시작, `SymbolMetadata.listed_from`/`listed_to`에
   실제 값 채우기 → Phase 29가 수정한 배선이 자동으로
   survivorship-aware universe를 만들어냄(추가 아키텍처 작업 불필요).
   `ingest_real_market_data.py`의 새 manifest 필드가 실 provider의
   실제 커버리지(2010 vs 실제 시작일)를 즉시 정직하게 보고함.
4. 그 전까지는 사용자가 이미 보유한 2023-2024 실 데이터로
   `scripts/run_long_horizon_validation.py --data-status REAL`을 외부
   환경에서 실행하는 것이 가장 빠른 실 evidence 확보 경로(변경 없음).

## Previous Subtask (Session 30 — Phase 29)

**Phase 29 — Long-Horizon / Broad-US-Universe / Survivorship-Aware Real
Walk-Forward Validation** (Live Trading은 여전히 구조적으로 비활성 —
Toss capability가 `CapabilityStatus.UNKNOWN`인 한 활성화 불가). 목표는
2010~최신 실 데이터로 broad survivorship-aware universe Walk-Forward를
실행하는 것이었으나 환경 제약으로 이번에도 불가능 — 대신 이번 phase는
architecture audit을 통해 중요한 사실을 발견함: point-in-time-safe
survivorship-aware 아키텍처(`SecurityMaster.security_id`가 이미
ticker와 독립적인 permanent identifier, `valid_from`/`valid_to`,
`SecurityStatus.DELISTED`, `get_universe(as_of_time=...)`의 정확한
point-in-time 필터링)가 **Phase 1부터 이미 존재**했다는 것 — 실제
공백은 `build_security_masters`/`build_universe_memberships`(Phase
24)가 `SymbolMetadata.listed_from`/`listed_to`를 무시하던 것뿐이었음
(수정함, 기존 데이터에 대해서는 완전히 동일하게 동작 — additive).

### Completed (Session 30 — Phase 29)

- **Git/Branch Integrity 선행 확인**: 로컬 HEAD가 Phase 28 HEAD
  (`61c9507`)와 정확히 일치함을 확인 후 `origin/main`을
  fast-forward-only로 병합(merge commit 0개) → push →
  `claude/phase-29-broad-universe-survivorship-aware-validation` 브랜치
  신규 생성. Baseline **1652/1652 테스트 통과** 실제 실행으로 확인
  (지침이 예상한 1649는 stale — 실제 실행 결과를 신뢰).
- **Architecture audit(핵심 발견)**: `src/data_infra/models.py`/
  `repository.py`를 직접 읽어 확인 — `SecurityMaster.security_id`가
  이미 ticker와 분리된 permanent identifier, `valid_from`/`valid_to`
  + `SecurityStatus`(ACTIVE/DELISTED/RENAMED/MERGED)가 이미
  delisted/inactive 추적, `UniverseMembership.valid_from`/`valid_to`
  + `get_universe(as_of_time=...)`가 이미 정확한 point-in-time
  survivorship-aware 쿼리를 수행(InMemory와 DuckDB 양쪽 구현 모두 직접
  코드 확인) — 전부 Phase 1부터 무수정으로 존재. 새 아키텍처를
  만들지 않고 이 사실을 문서화하는 것 자체가 이번 phase의 핵심
  결정(ADR-0032 Decision 1).
- **실제 공백 수정 — listed_from/listed_to 미배선**:
  `build_security_masters`/`build_universe_memberships`가
  `SymbolMetadata.listed_from`/`listed_to`를 무시하고 모든 심볼에
  동일한 `valid_from`/`status=ACTIVE`/`valid_to=None`을 적용하던 문제.
  심볼별 실제 날짜를 사용하도록 수정(`status`는 `listed_to` 존재 여부로
  DELISTED/ACTIVE 판정 — RENAMED/MERGED는 더 세밀한 근거 없이 추측하지
  않음). 기존 `SymbolMetadata`(전부 listed_from/listed_to가 None)는
  완전히 동일하게 동작 — 순수 additive, 회귀 테스트로 확인.
- **`detect_ticker_collisions` 신규**: 서로 다른 security_id가 같은
  ticker를 겹치는 기간에 주장하면 collision(데이터 버그)으로 감지,
  겹치지 않는 기간의 정당한 ticker 재사용은 감지하지 않음.
- **`TiingoDataProvider.fetch_symbol_metadata`/`normalize_symbol_metadata`
  신규**: broad-universe discovery 준비 작업(Tier 2 문서 기반, 실
  응답으로 검증된 적 없음 — 기존 `fetch_corporate_actions`와 동일한
  정직성 원칙). `sector`/`market_cap_bucket`은 이 endpoint가 제공하지
  않으므로 채우지 않음.
- **신규 테스트 19개**: survivorship-aware point-in-time 쿼리(delisted
  종목이 valid_to 이후 사라짐/이전엔 존재, 미래 상장 종목이 과거
  쿼리에 안 나타남, current-survivor-only vs historical universe가
  실제로 다른 결과를 냄 — 지침의 핵심 질문을 직접 증명), ticker
  reuse/collision 구분, DuckDB 실제 재시작 후 delisted 종목 처리,
  Tiingo metadata fetch/normalize. 전부 SYNTHETIC fixture — 실 데이터
  주장 아님.
- **실 데이터/네트워크 재확인**: 전체 파일시스템 재탐색, network egress
  동일 진단(`host_not_allowed`), 변화 없음. **REAL WALK-FORWARD
  EXECUTION: NOT COMPLETED.**
- **기존 1652개 테스트 전부 유지** — 최종 **1671 passed**.
- **신규 문서**: ADR-0032, `docs/research/STRATEGY-VALIDATION-REPORT.md`
  Phase 29 Addendum(지침 section 86의 10개 질문 전부 답변). README.md/
  PROJECT_STATUS.md/PRODUCTION-READINESS-MATRIX.md/MARKET-DATA-PROVIDER.md
  갱신(이 항목).
- **Toss/Live 활성화 코드, RiskConfig 숫자, 새 전략 추가, parameter
  tuning 전부 없음.**

### In Progress (Session 30 — Phase 29)

없음 — 이번 세션 작업 완료.

### Blocked (Session 30 — Phase 29)

- 이 sandboxed 세션 자체의 실 시장데이터 접근 — Phase 26-28과 동일한
  원인(network egress allowlist), 변화 없음.
- 2010~최신 broad survivorship-aware universe 실 ingestion 및 실
  Walk-Forward 실행 — 위 항목에 종속. 이 데이터는 어느 환경에도 존재한
  적 없음(사용자의 Codespaces 환경도 2023-2024만 보유).

### Decision Required (Session 30 — Phase 29)

1. (Phase 17-28에서 이어짐) 전부 변경 없음.
2. **(신규, 실질적으로는 이어짐)** 2010~최신 broad universe 실
   ingestion을 언제/어떻게 수행할지 — network egress allowlist 해결이
   선행 조건. provider(Tiingo) 무료 tier의 실제 500 symbols/month 등
   한도가 이번 phase에서도 실제 계정으로 확인되지 않음(여전히 UNKNOWN).

### Known Issues (Session 30 — Phase 29)

- Phase 28까지의 Known Issues 전부 유지. 이번 phase가 발견한 유일한
  gap(`listed_from`/`listed_to` 미배선)은 이미 수정·회귀 테스트
  추가됨.

### Architecture Changes (Session 30 — Phase 29)

`src/data_infra/universe.py`(`build_security_masters`/
`build_universe_memberships` 배선 수정 + `detect_ticker_collisions`
신규, additive),
`src/data_infra/providers/tiingo.py`(`fetch_symbol_metadata`/
`normalize_symbol_metadata` 신규, additive) — 전부 기존 코드에 대한
순수 추가/버그 수정. `backtest.engine`, `strategy_research.*`,
`data_infra.repository`/`storage.data_repository`의 쿼리 로직 전부
무수정(이미 올바르게 동작함을 확인만 함).

### Toss API Status (Session 30 — Phase 29)

변경 없음: `CapabilityStatus` 전부 `UNKNOWN` 유지.

### Last Validation (Session 30 — Phase 29)

`python -m pytest tests/ -q` — baseline **1652 passed** → 최종
**1671 passed, 0 failed, 0 skipped**. 기존 1652개 테스트 전부
삭제/약화 없이 유지, 신규 19개 추가.

### Next Task (Session 30 — Phase 29)

1. workspace/environment 관리자가 network egress allowlist에
   `api.tiingo.com`을 추가 — 이 세션 자체에서 실 데이터 확보의 유일한
   경로.
2. Tiingo 실제 계정으로 무료 tier 한도(unique symbols/month,
   requests/day 등)를 실제로 확인 — broad universe 규모 결정의 선행
   조건.
3. 위 두 조건이 충족되면: `fetch_symbol_metadata`로 broad universe
   discovery Stage 1 시작, `SymbolMetadata.listed_from`/`listed_to`에
   실제 값 채우기 → 이번 phase가 수정한 배선이 자동으로
   survivorship-aware universe를 만들어냄(추가 아키텍처 작업 불필요).
4. 그 전까지는 사용자가 이미 보유한 2023-2024 실 데이터로
   `scripts/run_long_horizon_validation.py --data-status REAL`을 외부
   환경에서 실행하는 것이 가장 빠른 실 evidence 확보 경로(변경 없음).

## Previous Subtask (Session 29 — Phase 28)

**Phase 28 — Real-Data Walk-Forward Execution & Strategy Evidence**
(Live Trading은 여전히 구조적으로 비활성 — Toss capability가
`CapabilityStatus.UNKNOWN`인 한 활성화 불가). 목표는 처음으로 실 데이터
Walk-Forward TEST를 실제 실행하는 것이었으나 환경 제약으로 이번에도
불가능 — 대신 이번 phase의 자체 검증 과정에서 실제 gap을 발견·보강함
(아래 참조).

### Completed (Session 29 — Phase 28)

- **Git/Branch Integrity 선행 확인**: 로컬 HEAD가 Phase 27 HEAD
  (`4fd7a5f`)와 정확히 일치함을 확인 후 `origin/main`을
  fast-forward-only로 병합(merge commit 0개) → push →
  `claude/phase-28-real-data-walk-forward-execution` 브랜치 신규
  생성. Baseline **1649/1649 테스트 통과** 실제 실행으로 확인.
- **실 데이터 전체 파일시스템 탐색**: `data/`뿐 아니라 프로젝트 문서,
  ingestion manifest, DuckDB/Parquet 파일(전체 파일시스템), 환경변수,
  기존 스크립트까지 순서대로 탐색 — 실 데이터를 어디에서도 찾지 못함.
  network egress 재확인 결과도 Phase 26/27과 동일한 `host_not_allowed`
  진단, 변화 없음.
- **버그/gap 발견 및 수정 — `--data-status REAL`이 호출자 주장만
  신뢰**: `--data-status REAL`을 실제 데이터의 provenance와 교차검증하는
  로직이 전혀 없었음(호출자가 REAL이라고 주장하면 그대로 믿음). 수정:
  실제 bar들의 `Provenance.source`가 실 provider 문자열(`tiingo`/
  `stooq`, provider 소스코드에서 직접 확인)과 일치하는지 검증하고,
  불일치 시 어떤 전략 평가도 시작하기 전에 거부(exit 1). **런타임으로
  직접 검증**: Phase 25-27이 dry-run에 쓰던 것과 동일한 synthetic
  fixture 카탈로그(`provenance.source="test_source"`)로
  `--data-status REAL`을 붙이면 정확히 거부됨(exit 1)을, `--data-status
  SYNTHETIC`을 붙이면 정상 실행되어 `INSUFFICIENT_EVIDENCE`/
  `SYNTHETIC_TOTAL_RETURN`을 올바르게 출력함을 직접 확인.
- **신규 테스트 3개**(AST 기반, `tests/strategy_research/test_run_long_horizon_validation_wiring.py`
  확장): `_KNOWN_REAL_PROVIDER_SOURCES`가 실제 provider 소스 문자열과
  일치, 불일치 시 경고가 아닌 명확한 비정상 종료(return 값 != 0), 이
  검증이 어떤 전략 평가보다도 먼저 실행됨.
- **기존 1649개 테스트 전부 유지** — 최종 **1652 passed**.
- **신규 문서**: `docs/operations/MARKET-DATA-PROVIDER.md`/
  `docs/research/STRATEGY-VALIDATION-REPORT.md`에 Phase 28 절 추가.
  README.md/PROJECT_STATUS.md/PRODUCTION-READINESS-MATRIX.md 갱신(이
  항목).
- **Toss/Live 활성화 코드, RiskConfig 숫자는 전혀 건드리지 않음.**

### In Progress (Session 29 — Phase 28)

없음 — 이번 세션 작업 완료.

### Blocked (Session 29 — Phase 28)

- 이 sandboxed 세션 자체의 실 시장데이터 접근 — Phase 26/27과 동일한
  원인(network egress allowlist), 변화 없음. 이번엔 파일시스템 전체
  탐색으로 로컬 데이터 부재도 재확인(`BLOCKED_BY_DATA`).
- 실제 Walk-Forward TEST 실행 — 위 항목에 종속. 사용자가 이미 보유한
  2023-2024 실 데이터로는 지금 바로 외부 환경에서 실행 가능
  (`scripts/run_long_horizon_validation.py --data-status REAL ...` —
  이제 provenance 교차검증까지 통과해야 함, 실제 Tiingo 데이터라면
  자동으로 통과).

### Decision Required (Session 29 — Phase 28)

1. (Phase 17-27에서 이어짐) 전부 변경 없음.
2. `scripts/run_long_horizon_validation.py --data-status REAL`을 사용자가
   이미 보유한 실 데이터로 실행할 시점 — 변경 없음, 지금 바로 외부
   환경에서 실행 가능.

### Known Issues (Session 29 — Phase 28)

- Phase 27까지의 Known Issues 전부 유지. 이번 phase가 발견한 유일한
  gap(`--data-status REAL` provenance 미검증)은 이미 수정·회귀 테스트
  추가됨.

### Architecture Changes (Session 29 — Phase 28)

`scripts/run_long_horizon_validation.py`(REAL-provenance plausibility
check 추가, additive),
`tests/strategy_research/test_run_long_horizon_validation_wiring.py`
(확장) — 전부 기존 코드에 대한 순수 추가. `src/strategy_research/*`,
`backtest.engine` 전부 무수정.

### Toss API Status (Session 29 — Phase 28)

변경 없음: `CapabilityStatus` 전부 `UNKNOWN` 유지 — 이번 Phase는 Toss
코드를 전혀 건드리지 않았음.

### Last Validation (Session 29 — Phase 28)

`python -m pytest tests/ -q` — baseline **1649 passed** → 최종
**1652 passed, 0 failed, 0 skipped**. 기존 1649개 테스트 전부
삭제/약화 없이 유지, 신규 3개 추가.

### Next Task (Session 29 — Phase 28)

1. 사용자가 이미 보유한 2023-2024 실 데이터로
   `scripts/run_long_horizon_validation.py --universe PILOT_UNIVERSE
   --start 2023-01-02 --end 2024-12-31 --db-path ./data/real_market_data
   --data-status REAL` 실행(외부 환경) — 처음으로 실 walk-forward/evidence
   결과 확보의 가장 빠른 경로. Provenance 교차검증을 통과하려면 실제
   Tiingo/Stooq ingestion 결과여야 함(자동으로 통과할 것).
2. workspace/environment 관리자가 network egress allowlist에
   `api.tiingo.com`을 추가하면 이 세션 자체에서도 직접 시도 가능.
3. 위 Decision Required 항목들에 대한 사람의 판단.

## Previous Subtask (Session 28 — Phase 27)

**Phase 27 — Real-Data Walk-Forward Validation & Strategy Evidence**
(Live Trading은 여전히 구조적으로 비활성 — Toss capability가
`CapabilityStatus.UNKNOWN`인 한 활성화 불가). 목표는 실 데이터로 실제
Walk-Forward를 실행하는 것이었으나 환경 제약으로 이번에도 불가능 —
대신 이번 phase의 자체 검증 과정에서 실제 버그를 발견·수정함(아래
참조).

### Completed (Session 28 — Phase 27)

- **Git/Branch Integrity 선행 확인**: 로컬 HEAD가 Phase 26 HEAD
  (`ee17e26`)와 정확히 일치함을 확인 후 `origin/main`을
  fast-forward-only로 병합(merge commit 0개) → push →
  `claude/phase-27-real-data-walk-forward-validation` 브랜치 신규
  생성. Baseline **1640/1640 테스트 통과** 실제 실행으로 확인.
- **실 데이터 재확인**: `data/` 여전히 비어 있음, `MARKET_DATA_API_KEY`
  미설정, network egress 여전히 `host_not_allowed` — Phase 26과 동일한
  진단, 변화 없음.
- **버그 발견 및 수정 — `is_real_data` 하드코딩**: 이번 phase의 지침이
  명시적으로 요구한 "real/synthetic status를 report에서 혼동하지
  않는다" 조건을 감사하던 중, `scripts/run_long_horizon_validation.py`의
  `classify_evidence_level(..., is_real_data=True, ...)`가 `--db-path`가
  실제로 무엇을 담고 있는지와 무관하게 하드코딩되어 있었음을 발견 —
  즉 이 스크립트로 실행한 모든 synthetic dry-run(Phase 25/26의 자체
  smoke test 포함)이 실제로는 real-data 기준 evidence threshold로
  분류되고 있었음(report 자체에는 이를 구분할 필드도 없었음). **수정**:
  필수 CLI 인자 `--data-status {REAL,SYNTHETIC}` 추가, `is_real_data`를
  이 값으로 직접 게이팅, `experiment_id` 해시에도 포함(REAL/SYNTHETIC
  실행이 같은 experiment_id로 충돌하지 않도록), report에 `data_status`
  필드 신규 추가. 동일한 synthetic dry-run 카탈로그로
  `--data-status SYNTHETIC`을 붙여 재실행해 수정 전/후 차이를 직접
  확인(수정 전 동작이면 ROBUSTNESS_PENDING이 나왔을 것, 수정 후
  올바르게 INSUFFICIENT_EVIDENCE로 나옴).
- **신규 회귀 테스트 9개** (`tests/strategy_research/test_run_long_horizon_validation_wiring.py`,
  스크립트를 import/실행하지 않는 순수 AST/소스 텍스트 기반 — 기존
  `test_security_boundary.py`와 동일한 원칙): `is_real_data` 하드코딩
  literal 금지, `--data-status` 필수/정확한 choices, `experiment_id`
  해시에 `data_status` 포함, report dict에
  `data_status`/`experiment_id`/`data_version` 존재, walk-forward
  호출은 `train_start`..`validation_end`만 사용(TEST 구간 미침범),
  held-out test 호출은 `test_start`..`test_end`만 사용, 두 평가
  호출이 동일한 `benchmark_id` 변수 참조(전략 간 조건 불일치 방지),
  `benchmark_id`는 `None` 또는 `spy_bars` 게이팅된 조건식으로만
  할당(fabricated fallback 없음), 스크립트가 `datetime.now()`/`random`을
  사용하지 않음.
- **기존 1640개 테스트 전부 유지** — 최종 **1649 passed**.
- **신규 문서**: `docs/operations/MARKET-DATA-PROVIDER.md`/
  `docs/research/STRATEGY-VALIDATION-REPORT.md`에 Phase 27 절 추가.
  README.md/PROJECT_STATUS.md/PRODUCTION-READINESS-MATRIX.md 갱신(이
  항목).
- **Toss/Live 활성화 코드, RiskConfig 숫자는 전혀 건드리지 않음.**

### In Progress (Session 28 — Phase 27)

없음 — 이번 세션 작업 완료.

### Blocked (Session 28 — Phase 27)

- 이 sandboxed 세션 자체의 실 시장데이터 접근 — Phase 26과 동일한
  원인(network egress allowlist), 변화 없음.
- 실제 Walk-Forward TEST 실행 — 위 항목에 종속. 사용자가 이미 보유한
  2023-2024 실 데이터로는 지금 바로 외부 환경에서 실행 가능
  (`scripts/run_long_horizon_validation.py --data-status REAL ...`).

### Decision Required (Session 28 — Phase 27)

1. (Phase 17-26에서 이어짐) 전부 변경 없음 — risk 기본값 3개,
   `RiskConfig.max_turnover` None-semantics, PBO/Deflated Sharpe 실제
   계산 채택, 실제 Toss credential 확보, `RESEARCH_UNIVERSE` Stage 2
   확장, network egress allowlist 추가 여부.
2. `scripts/run_long_horizon_validation.py --data-status REAL`을 사용자가
   이미 보유한 실 데이터로 실행할 시점 — 변경 없음, 지금 바로 외부
   환경에서 실행 가능.

### Known Issues (Session 28 — Phase 27)

- Phase 26까지의 Known Issues 전부 유지. 이번 phase가 발견한 유일한
  이슈(`is_real_data` 하드코딩)는 이미 수정·회귀 테스트 추가됨.

### Architecture Changes (Session 28 — Phase 27)

`scripts/run_long_horizon_validation.py`(`--data-status` 필수 인자
추가, additive bug fix),
`tests/strategy_research/test_run_long_horizon_validation_wiring.py`
(신규) — 전부 기존 코드에 대한 순수 추가/버그 수정.
`src/strategy_research/*`, `backtest.engine` 전부 무수정.

### Toss API Status (Session 28 — Phase 27)

변경 없음: `CapabilityStatus` 전부 `UNKNOWN` 유지 — 이번 Phase는 Toss
코드를 전혀 건드리지 않았음.

### Last Validation (Session 28 — Phase 27)

`python -m pytest tests/ -q` — baseline **1640 passed** → 최종
**1649 passed, 0 failed, 0 skipped**. 기존 1640개 테스트 전부
삭제/약화 없이 유지, 신규 9개 추가.

### Next Task (Session 28 — Phase 27)

1. 사용자가 이미 보유한 2023-2024 실 데이터로
   `scripts/run_long_horizon_validation.py --universe PILOT_UNIVERSE
   --start 2023-01-02 --end 2024-12-31 --db-path ./data/real_market_data
   --data-status REAL` 실행(외부 환경) — 처음으로 실 walk-forward/evidence
   결과 확보의 가장 빠른 경로.
2. workspace/environment 관리자가 network egress allowlist에
   `api.tiingo.com`을 추가하면 이 세션 자체에서도 직접 시도 가능.
3. 위 Decision Required 항목들에 대한 사람의 판단.

## Previous Subtask (Session 27 — Phase 26)

**Phase 26 — Long-Horizon Real-Data Validation (재확인)** (Live
Trading은 여전히 구조적으로 비활성 — Toss capability가
`CapabilityStatus.UNKNOWN`인 한 활성화 불가, 이번 Phase도 Toss 코드를
전혀 건드리지 않았으므로 Phase 21의 사유가 그대로 유지된다). 목표는
Phase 25 인프라를 실제 장기 실 데이터에 적용하는 것이었으나 위 환경
제약으로 실행하지 못함 — 대신 실제로 완료한 작업은 아래 참조.

### Completed (Session 27 — Phase 26)

- **Git/Branch Integrity 선행 확인**: 로컬 HEAD가 origin의 Phase 25
  브랜치 HEAD(`8dff011`)와 정확히 일치함을 확인 후 `origin/main`을
  fast-forward-only로 병합(merge commit 0개) → push →
  `claude/phase-26-long-horizon-real-validation` 브랜치 신규 생성.
  Baseline **1638/1638 테스트 통과** 실제 실행으로 확인(추측 아님).
- **정확한 network block 원인 진단(3단계 독립 검증)**: DNS resolve
  (`socket.gethostbyname`) 성공 → TCP connect(설정된 proxy 우회) 성공
  → 실제 HTTPS 요청(proxy 우회 포함)만 403, 응답 헤더/본문에서
  `x-deny-reason: host_not_allowed`를 직접 확인 — 이전 phase들이
  기록하지 못한 정밀도. `docs/operations/MARKET-DATA-PROVIDER.md`
  "Phase 26 precise block diagnosis" 절에 상세 기록.
- **Point-in-Time CASE 1-5 감사** (지침 section 9): CASE 1-4는 기존
  `tests/data/test_lookahead_guard.py`/`tests/backtest/test_total_return.py`가
  이미 커버함을 코드로 직접 확인(중복 작성 안 함). CASE 5(재-ingestion이
  이미 확립된 과거 as_of 결과를 소급 변경하지 않음)는 기존 테스트가
  없음을 확인 — 실제 `IngestionRunner`/`DuckDBDataRepository` 경로를
  사용하는 신규 테스트 2개(`tests/data/test_phase26_point_in_time_cases.py`)
  추가: 실 데이터 확장 시나리오(새 기간 추가)와 동일 기간 재실행
  (retry/resume) 시나리오 둘 다 과거 as_of 쿼리 결과가 불변임을 확인.
- **Corporate action 8개 질문 감사** (지침 section 8): raw
  close/adjusted_close 분리(`tiingo.py`), split/dividend 별도
  `CorporateAction` 레코드, `effective_time` vs
  `available_time`/`ingestion_time` 구조적 분리, split 발생 시
  `CorporateActionApplier`가 보유 포지션 수량을 조정
  (`test_split_adjusts_held_position`), dividend가 total-return
  benchmark에 반영(`test_dividend_is_added_back_into_the_days_return`)
  — 전부 기존 코드/테스트로 이미 올바르게 구현되어 있음을 확인. **공백
  없음.**
- **`scripts/run_long_horizon_validation.py`에 재현성 필드 추가**
  (지침 section 22): `experiment_id`(universe/기간/split 비율/walk-forward
  윈도우/initial_capital 등 호출자 제공 설정값만의 결정론적 해시 —
  wall-clock 미사용) + `data_version`(실행 시점 repository의 실제
  종목별 bar 개수 기반 해시, `scripts/ingest_real_market_data.py`와
  동일한 `compute_data_version` 재사용). 소규모 synthetic dry-run으로
  두 필드가 JSON report에 정상 기록됨을 확인.
- **신규 테스트 2개** — 기존 1638개 테스트는 전부 그대로 유지, 약화
  없음. 최종 **1640 passed**.
- **신규 문서**: `docs/operations/MARKET-DATA-PROVIDER.md`의 "Phase 26
  precise block diagnosis" 절, `docs/research/STRATEGY-VALIDATION-REPORT.md`의
  "Phase 26 Addendum"(지침 section 32의 18개 질문 전부 답변). README.md/
  PROJECT_STATUS.md 갱신(이 항목).
- **Toss/Live 활성화 코드, RiskConfig 숫자는 전혀 건드리지 않음.**

### In Progress (Session 27 — Phase 26)

없음 — 이번 세션 작업 완료.

### Blocked (Session 27 — Phase 26)

- 이 sandboxed 세션 자체의 실 시장 데이터 확장/ingestion — 원인은 이번
  phase에서 정확히 진단됨(network egress allowlist, `x-deny-reason:
  host_not_allowed`)이나 해결 자체는 이 세션 권한 밖(workspace/environment
  설정 변경 필요).
- `scripts/run_long_horizon_validation.py`를 실 데이터로 이 세션에서
  직접 실행하는 것 — 위 항목에 종속. 사용자가 이미 보유한 2023-2024 실
  데이터로는 지금 바로 실행 가능(외부 환경에서).
- Live Trading 활성화 — 변경 없음, Toss capability 4종이 여전히
  `CapabilityStatus.UNKNOWN`.

### Decision Required (Session 27 — Phase 26)

1. (Phase 17-25에서 이어짐) `RiskConfig.max_turnover` None-semantics,
   risk 기본값 3개 최종 승인, cancel-on-shutdown 자동화, PBO/Deflated
   Sharpe 실제 계산 채택, 실제 Toss credential 확보, `RESEARCH_UNIVERSE`
   Stage 2 확장 — 전부 변경 없음.
2. (Phase 25에서 이어짐) `scripts/run_long_horizon_validation.py`를
   실 데이터로 실행할 시점/방법 — 변경 없음, 사용자가 지금 바로 외부
   환경에서 실행 가능.
3. **(신규)** 이 환경의 network egress allowlist에 `api.tiingo.com`
   (및 필요 시 `stooq.com`)을 추가할지 — workspace/environment 설정
   권한을 가진 사람의 결정 필요. 추가되면 이 세션 자체에서도 실 데이터
   ingestion이 가능해짐.

### Known Issues (Session 27 — Phase 26)

- Phase 24까지의 Known Issues 전부 유지. 신규 이슈 없음(이번 phase의
  감사에서 corporate action/point-in-time 관련 실제 공백은 CASE 5
  하나였고, 이미 해소함).

### Architecture Changes (Session 27 — Phase 26)

`scripts/run_long_horizon_validation.py`(experiment_id/data_version
필드 추가, additive), `tests/data/test_phase26_point_in_time_cases.py`
(신규) — 전부 기존 코드에 대한 순수 추가. `backtest.engine`,
`backtest.strategy`, `strategy_research.*` 전부 무수정.

### Toss API Status (Session 27 — Phase 26)

변경 없음(Phase 21 상태 그대로): `CapabilityStatus` 전부 `UNKNOWN`
유지 — 이번 Phase는 Toss 코드를 전혀 건드리지 않았음.

### Last Validation (Session 27 — Phase 26)

`python -m pytest tests/ -q` — baseline **1638 passed** → 최종
**1640 passed, 0 failed, 0 skipped**. 기존 1638개 테스트 전부
삭제/약화 없이 유지, 신규 2개 추가.

### Next Task (Session 27 — Phase 26)

1. workspace/environment 관리자가 network egress allowlist에
   `api.tiingo.com`을 추가하면, 이 세션 자체에서도
   `scripts/ingest_real_market_data.py --start <더 이른 날짜>`로 장기
   실 데이터 ingestion을 직접 시도할 수 있음.
2. 그 전까지는 사용자가 이미 보유한 2023-2024 실 데이터로
   `scripts/run_long_horizon_validation.py`를 외부 환경에서 실행 —
   처음으로 실 walk-forward/evidence 결과 확보의 가장 빠른 경로.
3. 실 결과 확보 후: `STRATEGY-VALIDATION-REPORT.md`에 fold-by-fold
   결과를 addendum으로 기록.
4. 위 Decision Required 항목들에 대한 사람의 판단.

## Previous Subtask (Session 26 — Phase 25)

**Phase 25 — Long-Horizon Real-Data Strategy Validation** (Live
Trading은 여전히 구조적으로 비활성 — Toss capability가
`CapabilityStatus.UNKNOWN`인 한 활성화 불가, 이번 Phase도 Toss 코드를
전혀 건드리지 않았으므로 Phase 21의 사유가 그대로 유지된다). 목표는
"그럴듯해 보이는 전략 하나 고르기"가 아니라, 기존 4개 전략 후보의 일반화
가능성을 chronological Train/Validation/Test + Walk-Forward로 평가하는
인프라를 구축하는 것 — 최종 결론은 반드시 실 데이터 기준.

### Completed (Session 26 — Phase 25)

- **Git/Branch Integrity 선행 확인**: 로컬 HEAD가
  `origin/claude/phase-24-real-data-expandable-universe`와 정확히
  일치함을 확인 후 `origin/main`이 Phase 22 HEAD에 정체되어 있던 것을
  fast-forward-only로 병합(merge commit 0개, 35 files) → push →
  `claude/phase-25-long-horizon-validation` 브랜치 신규 생성. Baseline
  **1608/1608 테스트 통과** 실제 실행으로 확인.
- **아키텍처 감사**: `src/regime/`(Phase 5)가 이미 BULL/BEAR/NEUTRAL
  regime 분류를 제공함을 확인해 새 regime 모델을 만들지 않고 재사용하기로
  결정. `AsOfDataView.get_bars`가 `BacktestConfig.start_date`와 무관하게
  자체 clock에 바인딩됨을 코드로 직접 확인 — 이 통찰이 `backtest.engine`을
  전혀 수정하지 않고 walk-forward out-of-sample 평가를 구현할 수 있게 한
  핵심 설계 근거(ADR-0031 Decision 1).
- **`src/strategy_research/walk_forward_evaluation.py` 신규**:
  `run_walk_forward_evaluation` — 기존 `generate_walk_forward_windows`/
  `run_gross_and_net`(Phase 23, 무수정)을 그대로 재사용해 각 fold의
  TEST 구간만 `start_date`/`end_date`로 설정, TRAIN 구간은 strategy의
  자체 lookback이 point-in-time 아키텍처를 통해 자연스럽게 조회.
  `WalkForwardFoldResult`/`WalkForwardAggregate`(median/stdev/worst/best
  fold 통계, regime breakdown 포함).
- **`src/strategy_research/evidence.py` 신규**: `EvidenceLevel`
  5단계(INSUFFICIENT_EVIDENCE/PRELIMINARY/ROBUSTNESS_PENDING/CANDIDATE/
  VALIDATED) — `classify_evidence_level`은 구조적으로 `VALIDATED`를
  절대 반환하지 않음(도달 가능한 최고 등급은 CANDIDATE; 이 함수가 수행할
  수 없는 사람의 검토를 위한 목표 상태로만 enum에 존재 — `CandidateClassification`에
  `PROVEN_ALPHA` 값 자체가 없는 기존 패턴과 동일한 구조적 장치).
  `assess_pbo_dsr_applicability` — Phase 18이 이미 정의한 PBO/Deflated
  Sharpe 채택 조건(후보 2개 이상, 각 6-fold 이상 실 out-of-sample fold)이
  충족됐는지만 확인, 실제 계산은 여전히 미구현(사람의 채택 결정 대기).
  두 모듈 전부 광범위한 시나리오로 smoke-test 및 pytest 검증 완료.
- **`scripts/run_long_horizon_validation.py` 신규**: `build_chronological_split`
  (Phase 23, 무수정)로 실 ingestion 윈도우를 TRAIN/VALIDATION/TEST로 분할,
  walk-forward는 TRAIN+VALIDATION 구간에서만 반복 실행, TEST 구간은
  `held_out_test`로 단 한 번만 평가(instruction section 24의 "TEST 구간은
  마지막에 딱 한 번만 사용한다" 구조적으로 준수). 모든 전략은 기존 기본
  파라미터만 사용(grid search 없음, RULE 0.8 — 결과를 본 뒤 재조정 금지).
  실 DuckDB 카탈로그가 있는 환경에서만 실행 가능, 자동화 테스트는 이
  스크립트를 절대 import/실행하지 않음. **PILOT_UNIVERSE의 실제 15개
  종목 티커에 synthetic deterministic 가격을 채운 대규모 dry-run**으로
  CLI 자체의 정합성을 이 세션에서 직접 검증(4개 전략 x 7개 윈도우(6
  fold + held-out) x gross/net 전부 정상 완료, 실 SPY TOTAL_RETURN
  벤치마크 구성 성공, PBO/DSR 적용가능성 판정도 정상 동작 확인) — 이
  결과는 **synthetic pipeline 검증용일 뿐 실 성과 주장이 아님**, 실 데이터
  실행 결과는 사람이 별도 환경에서 직접 실행해야 한다.
- **신규 테스트 30개** (`tests/strategy_research/test_walk_forward_evaluation.py`
  14개, `tests/strategy_research/test_evidence.py` 16개) — instruction
  section 24가 요구한 카테고리 A~R 전부 커버: chronological split
  재검증(A/B), no-future-leakage(C), walk-forward 순서/미겹침(D/E),
  결정론적 재현(F), 거래비용 반영(G), gross/net 일관성(H), benchmark
  정렬(I), as_of_time 무결성(J, 각 fold가 자기 자신의 test_end를
  사용함을 monkeypatch로 직접 검증), corporate action 가용성(K), research
  log 완전성(L), 전략 파라미터 불변성(M), random/wall-clock/network 미사용
  (N/O/P — 기존 `test_security_boundary.py`가 패키지 전체를 재귀 스캔하므로
  자동 커버), universe-benchmark 배제(Q). 카테고리 R(재시작 영속성)은
  명시적으로 N/A(이번 phase는 새 `DataRepository` 영속화를 추가하지 않음)
  — 두 신규 테스트 파일 docstring에 이유 명시.
- **신규 문서**: ADR-0031(Long-Horizon Walk-Forward Validation, 5개
  결정), `docs/research/STRATEGY-VALIDATION-REPORT.md`(19개 절 — 데이터
  소스부터 필요한 추가 검증까지, 실 데이터 실행이 이 세션에서 BLOCKED임을
  명시하고 정확한 외부 실행 커맨드 제공). README.md/PROJECT_STATUS.md
  갱신(이 항목) — Phase 24 이후 사용자가 실제로 실 Tiingo 데이터를
  확보했던 사실(당시 문서 갱신 누락)도 이번에 함께 반영.
- **Toss/Live 활성화 코드는 전혀 건드리지 않음** — `src/broker/toss/*`,
  `LiveTradingSession`, Decision/Risk 로직, 모델 승인/배포, `RiskConfig`
  숫자 전부 이번 Phase 범위 밖.
- 기존 1608개 테스트 전부 삭제/약화 없이 유지 + 신규 30개 추가.
  최종 **1638 passed**.

### In Progress (Session 26 — Phase 25)

없음 — 이번 세션 작업 완료.

### Blocked (Session 26 — Phase 25)

- Live Trading 활성화 — 변경 없음, Toss capability 4종이 여전히
  `CapabilityStatus.UNKNOWN`인 한 구조적으로 불가.
- 이 sandboxed 세션 자체의 실 시장 데이터 접근/ingestion — 재확인 결과도
  여전히 `BLOCKED`(egress 차단, `curl`로 세 도메인 전부 CONNECT 403).
- `scripts/run_long_horizon_validation.py`를 실 데이터로 이 세션에서
  직접 실행하는 것 — 위 항목에 종속, 사람이 실 데이터가 이미 있는
  환경(Codespaces)에서 직접 실행해야 함.
- PBO/Deflated Sharpe 실제 계산 구현 — 사람의 채택 결정 대기, 이번 phase도
  DEFER 유지(`assess_pbo_dsr_applicability`는 적용가능성만 확인, 계산
  자체는 미구현).

### Decision Required (Session 26 — Phase 25)

1. (Phase 17-24에서 이어짐) `RiskConfig.max_turnover`의 None-semantics
   — 변경 없음, 여전히 미결.
2. (Phase 20/22에서 이어짐) risk 기본값 3개 최종 승인 — 변경 없음,
   여전히 PROPOSED / AWAITING USER RATIFICATION.
3. (Phase 16에서 이어짐) cancel-on-shutdown 자동화 — 변경 없음.
4. (Phase 18-24에서 이어짐) Walk-Forward/PBO/Deflated Sharpe 실제 계산
   채택 — 이번 phase가 적용가능성 확인 인프라(`assess_pbo_dsr_applicability`)는
   추가했으나, 계산 자체를 구현할지는 여전히 사람의 결정 대기.
5. (Phase 21에서 이어짐) 실제 Toss 계좌 credential 확보 + 사람의
   운영 검증 — 여전히 유일하게 자동화 세션이 완료할 수 없는 항목.
6. (Phase 24에서 이어짐) `RESEARCH_UNIVERSE` Stage 2 확장 시점/방법 —
   변경 없음.
7. **(신규)** `scripts/run_long_horizon_validation.py`를 실 데이터로
   실행할 시점/방법 — 사용자가 이미 확보한 2023-2024 실 데이터로 지금
   바로 실행 가능(`STRATEGY-VALIDATION-REPORT.md` 12절 커맨드), 더 긴
   실 역사를 먼저 추가로 ingest할지는 사람의 판단.

### Known Issues (Session 26 — Phase 25)

- 실 데이터가 2023-2024 약 2년뿐이라 TRAIN/VALIDATION/TEST 분할과
  multi-fold walk-forward를 동시에 만족시키기엔 짧음 — 실행 시 실 fold
  수가 적을 것으로 예상됨(구조적 한계, 이번 phase가 만든 문제가 아님).
  2023-2024는 단일 방향 강세장(AI/반도체 랭크업)이라 실 evidence가 BULL
  regime에 편중될 것으로 예상.
- 그 외 Phase 24까지의 Known Issues 전부 유지.

### Architecture Changes (Session 26 — Phase 25)

`src/strategy_research/walk_forward_evaluation.py`(신규),
`src/strategy_research/evidence.py`(신규),
`scripts/run_long_horizon_validation.py`(신규) — 전부 기존 코드에 대한
순수 추가. `backtest.engine`, `backtest.strategy`, `strategy_research.splits`/
`runner`/`classification`/`research_log`, `regime.*` 전부 무수정.

### Toss API Status (Session 26 — Phase 25)

변경 없음(Phase 21 상태 그대로): `CapabilityStatus` 전부 `UNKNOWN`
유지 — 이번 Phase는 Toss 코드를 전혀 건드리지 않았음.

### Last Validation (Session 26 — Phase 25)

`python -m pytest tests/ -q` — baseline **1608 passed** → 최종
**1638 passed, 0 failed, 0 skipped**. 기존 1608개 테스트 전부
삭제/약화 없이 유지, 신규 30개 추가.

### Next Task (Session 26 — Phase 25)

1. 사람이 실 데이터가 이미 있는 환경(Codespaces)에서
   `scripts/run_long_horizon_validation.py --universe PILOT_UNIVERSE
   --start 2023-01-02 --end 2024-12-31 --db-path ./data/real_market_data`
   실행 — 처음으로 실 walk-forward/evidence 결과 확보의 유일한 남은 단계.
2. 실 결과 확보 후: `docs/research/STRATEGY-VALIDATION-REPORT.md`
   섹션 12-14에 fold-by-fold/aggregate/regime 결과를 addendum으로 기록
   (Phase 24 Addendum과 동일한 패턴).
3. 실 fold 수가 2개 후보 이상에서 각 6개 이상 확보되면: PBO/Deflated
   Sharpe 실제 계산 구현 여부에 대한 사람의 결정(Decision Required #4).
4. 더 긴 실 역사 ingestion — `scripts/ingest_real_market_data.py`는
   이미 임의의 `--start`를 지원하므로 새 스크립트/플래그 불필요, 네트워크
   접근 가능한 환경에서 재실행만 하면 됨.
5. 실제 Toss 계좌 credential 확보 + 사람의 운영 검증(위 Decision
   Required #5) — 여전히 유일하게 남은 Toss 관련 항목.
6. 위 Decision Required 항목들에 대한 사람의 판단.

## Previous Subtask (Session 25 — Phase 24)

**Phase 24 — Real Market Data + Expandable US Equity Universe** (Live
Trading은 여전히 구조적으로 비활성 — Toss capability가
`CapabilityStatus.UNKNOWN`인 한 활성화 불가, 이번 Phase도 Toss 코드를
전혀 건드리지 않았으므로 Phase 21의 사유가 그대로 유지된다). 목표는
"종목 수를 늘리는 것"이 아니라 16종목을 영구적인 시스템 설계로 만들지
않는 확장 가능한 Universe 아키텍처를 만드는 것이었다.

### Completed (Session 25 — Phase 24)

- **Git/Branch Integrity 선행 확인**: 지침이 제시한 Phase 23 HEAD
  (`746b4d016a977f040c6051cccf757002c2f76866`)가 이 세션 시작 시점의
  실제 HEAD와 정확히 일치함을 `git rev-parse`로 직접 확인(로컬==원격,
  working tree clean, merge commit 0개). 그 HEAD에서
  `claude/phase-24-real-data-expandable-universe` 브랜치를 새로 생성.
  Baseline **1587/1587 테스트 통과, 0 failed, 0 skipped, 0 warnings**를
  실제 실행으로 확인(지침이 "1547?가 아니라 실제로 측정하라"고 명시했으므로
  추측하지 않고 직접 실행).
- **실 시장 데이터 접근성 재확인(세 번째, 독립 경로 2개)**: `curl`을
  통한 egress proxy 상태 조회에 더해 이번에는 `WebFetch`(별도 fetch
  경로)로 `www.tiingo.com`/`stooq.com`을 추가로 시도 — 둘 다
  `EGRESS_BLOCKED`. 실 ingestion 수행 **없음**.
- **`src/data_infra/universe.py` 신규**: `UniverseDefinition`(name/
  version/role/description/symbols) + `SymbolMetadata`(symbol 외
  전부 기본값 `None` — 실제 provider 응답으로 확인된 적 없는 필드는
  일반 상식으로도 채우지 않음, 모듈 자체 원칙). `role`은 `"PILOT"`/
  `"RESEARCH"`만 허용, `BENCHMARK_SYMBOL`("SPY")이 멤버로 포함되면
  `__post_init__`에서 `ValueError` — 지침 section 32의 "전략 universe와
  benchmark를 혼동하지 않는다"를 구조적으로 강제. `PILOT_UNIVERSE_V1`
  (Phase 22의 기존 15개 거래대상 종목 그대로 보존)과
  `RESEARCH_UNIVERSE_STAGE1`(현재는 동일 — provider 무료 tier 한도가
  이 세션에서 검증 불가하므로 확장하지 않음, 다른 이름으로 미래 확장
  지점만 마련). `build_universe_memberships`/`build_security_masters`
  변환 함수가 Phase 1의 기존 `UniverseMembership`/`SecurityMaster`
  point-in-time 저장 메커니즘(무수정)을 채움 — 이전에는 이 두 테이블을
  채우는 코드가 `src/` 어디에도 없었음(테스트 fixture만 채웠음).
- **`scripts/ingest_real_market_data.py` 갱신**: `--universe`
  (`PILOT_UNIVERSE`/`RESEARCH_UNIVERSE`)로 named universe 선택(스크립트
  내부 하드코딩 리스트 대체), `--symbols`는 명시적 override로 유지.
  `SecurityMaster`/`UniverseMembership`도 함께 영속화하도록 갱신(이전엔
  가격 bar만 저장). Manifest에 `data_infra.versioning.compute_data_version`
  (무수정) 기반 content checksum 추가. Stub transport로 수동
  end-to-end smoke test 실행(universe 해석 → ingestion → quality
  check → checksum → 재시작 후 SecurityMaster/UniverseMembership 유지
  전부 확인) — 자동화 테스트로 커밋하지 않음(스크립트는 실 네트워크
  전용, 테스트가 import하면 안 됨).
- **`strategy_research` 코드 변경 없음**: 기존 `security_ids:
  Sequence[str]` 파라미터가 이미 어떤 심볼 시퀀스도 받으므로
  `UniverseDefinition.symbol_ids`가 그대로 흘러 들어감. 신규 테스트가
  `src/strategy_research/`에 `PILOT_UNIVERSE` 실 종목의 Python 문자열
  리터럴이 전혀 없음을 정적으로 확인(단순 substring 검사는 "V"/"MA"/
  "COST" 같은 짧은 티커가 일반 단어 안에서 오탐되는 것을 발견하고,
  정규식으로 실제 문자열 리터럴만 매칭하도록 수정).
- **provider 무료 tier 체크리스트 문서화**(`MARKET-DATA-PROVIDER.md`):
  historical/coverage/limit/corporate-action/adjusted 등 지침이 요구한
  항목별로 Tier 2 기존 근거(ADR-0025) 재인용 또는 UNKNOWN 명시 — 이
  세션에서 새로 확인된 사실 없음(재시도 자체는 위에서 이미 실패).
- **신규 테스트 18개**: `UniverseDefinition`/`SymbolMetadata` 검증
  (빈 목록/중복 심볼/benchmark 심볼 거부/잘못된 role), 이 모듈의
  변환 함수를 통한 point-in-time 회귀(늦은 valid_from 멤버십이 이른
  as_of 쿼리에 노출되지 않음), universe↔strategy_research 연결 증명,
  DuckDB 기반 SecurityMaster/UniverseMembership 영속화 + 재시작 검증.
- **신규 문서**: ADR-0030(Universe 아키텍처 7개 결정). `LIVE-RISK-POLICY.md`
  (숫자 변경 없음, PROPOSED / AWAITING USER RATIFICATION 재확인,
  `RiskConfig.max_turnover` gate-visibility gap 재검토 결과 변경 없음
  확인)/`PRODUCTION-READINESS-MATRIX.md`/`MARKET-DATA-PROVIDER.md`
  갱신. README.md/PROJECT_STATUS.md 갱신(이 항목).
- **Toss/Live 활성화 코드는 전혀 건드리지 않음** — `src/broker/toss/*`,
  `LiveTradingSession`, Decision/Risk 로직, 모델 승인/배포 전부 이번
  Phase 범위 밖.
- 기존 1587개 테스트 전부 삭제/약화 없이 유지 + 신규 18개 추가.
  최종 **1605 passed**.

### In Progress (Session 25 — Phase 24)

없음 — 이번 세션 작업 완료.

### Blocked (Session 25 — Phase 24)

- Live Trading 활성화 — 변경 없음, Toss capability 4종이 여전히
  `CapabilityStatus.UNKNOWN`인 한 구조적으로 불가.
- 실 시장 데이터 ingestion — 세 번째 재확인 결과도 여전히
  `BLOCKED`(egress 차단, `curl`+`WebFetch` 두 경로 모두 실패).
- `RESEARCH_UNIVERSE` Stage 2 이상 확장 — provider 무료 tier
  request/symbol/rate limit이 전부 UNKNOWN인 한 임의로 진행하지 않음.
- 실 데이터 기반 전략 평가/Walk-Forward 실제 적용/PBO·Deflated Sharpe
  채택 — 전부 위 ingestion BLOCKED 상태에 종속.

### Decision Required (Session 25 — Phase 24)

1. (Phase 17-23에서 이어짐) `RiskConfig.max_turnover`의 None-semantics
   — 변경 없음, 여전히 미결(이번 phase가 재확인만 하고 변경하지 않음).
2. (Phase 20/22에서 이어짐) risk 기본값 3개 최종 승인 — 변경 없음,
   여전히 PROPOSED / AWAITING USER RATIFICATION.
3. (Phase 16에서 이어짐) cancel-on-shutdown 자동화 — 변경 없음.
4. (Phase 18-23에서 이어짐) Walk-Forward/PBO/Deflated Sharpe 채택 —
   변경 없음, DEFER 유지.
5. (Phase 21에서 이어짐) 실제 Toss 계좌 credential 확보 + 사람의
   운영 검증 — 여전히 유일하게 자동화 세션이 완료할 수 없는 항목.
6. **(신규)** `RESEARCH_UNIVERSE` Stage 2 확장 시점/방법 — 실 네트워크
   접근이 확보되어 provider 무료 tier 한도가 실제로 확인된 이후에만
   진행 가능.

### Known Issues (Session 25 — Phase 24)

- `SymbolMetadata.exchange` 등 메타데이터 필드가 전부 `None`(UNKNOWN)
  상태로 남아 있어, `SecurityMaster.exchange`는 항상 `"UNKNOWN"`
  sentinel — 실제 provider 응답이 확보되기 전까지 이 상태 유지.
- 그 외 Phase 23까지의 Known Issues 전부 유지.

### Architecture Changes (Session 25 — Phase 24)

`src/data_infra/universe.py`(신규), `scripts/ingest_real_market_data.py`
(`--universe`/checksum/SecurityMaster·UniverseMembership 영속화 추가) —
전부 기존 코드에 대한 순수 추가 또는 스크립트(자동화 테스트 범위 밖)의
확장. `src/strategy_research/`, `src/backtest/*`, `src/broker/*`,
`src/risk/*` 등 무수정.

### Toss API Status (Session 25 — Phase 24)

변경 없음(Phase 21 상태 그대로): `CapabilityStatus` 전부 `UNKNOWN`
유지 — 이번 Phase는 Toss 코드를 전혀 건드리지 않았음.

### Last Validation (Session 25 — Phase 24)

`python -m pytest tests/ -q` — baseline **1587 passed** → 최종
**1605 passed, 0 failed, 0 skipped**. 기존 1587개 테스트 전부
삭제/약화 없이 유지, 신규 18개 추가.

### Next Task (Session 25 — Phase 24)

1. 실 네트워크 접근이 가능한 환경에서 `scripts/ingest_real_market_data.py
   --universe PILOT_UNIVERSE`를 실행 — 실 시세 데이터 확보의 유일한
   남은 단계.
2. 실 데이터 확보 후: `strategy_research.runner.run_gross_and_net`을
   실제 유니버스에 대해 실행, 처음으로 `has_real_evaluation_data=True`
   classification 시도.
3. provider 무료 tier 실제 한도가 확인되면: `RESEARCH_UNIVERSE` Stage 2
   설계/구현 검토.
4. 실제 Toss 계좌 credential 확보 + 사람의 운영 검증(위 Decision
   Required #5) — 여전히 유일하게 남은 Toss 관련 항목.
5. 위 Decision Required 6건에 대한 사람의 판단.

## Previous Subtask (Session 24 — Phase 23)

**Phase 23 — Strategy Research & Real Market Data Validation** (Live
Trading은 여전히 구조적으로 비활성 — Toss capability가
`CapabilityStatus.UNKNOWN`인 한 활성화 불가, 이번 Phase도 Toss 코드를
전혀 건드리지 않았으므로 Phase 21의 사유가 그대로 유지된다). 목표는
"수익률 숫자가 좋은 전략 하나를 만드는 것"이 아니라 (1) 실 시장 데이터
접근성을 이 세션에서 직접 재확인하고 (2) 장기 미국 주식 전략을 체계적으로
연구하는 파이프라인의 기반을 만드는 것 — 두 가지였다.

### Completed (Session 24 — Phase 23)

- **Git/Branch Integrity 선행 확인 + main 통합**: `git rev-parse`/
  `git merge-base --is-ancestor`로 Phase 22 검증 HEAD
  (`ef24e0099f1eadd642550e6e89f56ec89a6465a3`)가 실제 ancestor임을
  직접 확인. `origin/main`이 여전히 Phase 19 HEAD(`1d0003f...`)에
  머물러 있음을 발견하고, 지침 section 4에 따라
  `git merge --ff-only`로 Phase 22 HEAD를 `origin/main`에 병합
  (merge commit 0개, fast-forward만) 후 `git push origin main`으로
  원격에 반영. 그 새 `origin/main` HEAD에서
  `claude/phase-23-strategy-research-real-data` 브랜치를 새로 생성.
  Baseline **1547/1547 테스트 통과** 확인 후 구현 시작.
- **실 시장 데이터 접근성 재확인(추측 아님, 직접 확인)**: 환경의
  egress proxy 상태(`curl "$HTTPS_PROXY/__agentproxy/status"`)를 직접
  조회 — `api.tiingo.com`/`stooq.com`/`openapi.tossinvest.com` 전부
  403 CONNECT 거부, Phase 20 이후 변화 없이 **BLOCKED**. 이번 세션
  실 ingestion 수행 **없음**.
- **`scripts/ingest_real_market_data.py` 신규 작성**: 기존
  `FallbackDataProvider`/`IngestionRunner`/`DuckDBDataRepository`/
  `DataQualityFramework`를 그대로 재사용해 실 네트워크 접근이 가능한
  외부 환경에서 실행할 수 있는 CLI. API 키는 `MARKET_DATA_API_KEY`
  환경변수로만 읽음(커맨드라인 인자/파일 저장 금지), `end` 날짜는
  필수 CLI 인자로만 받아 wall-clock에 의존하지 않음. 이 저장소의
  자동화 테스트는 이 스크립트를 전혀 import/실행하지 않음(정적 소스
  스캔으로 확인).
- **`src/strategy_research/` 신규 패키지 — 장기 전략 후보 3종**: 전부
  기존 `backtest.strategy.Strategy` Protocol(Phase 2, 무수정)을
  구현해 기존 `BacktestEngine`에 그대로 연결(신규 portfolio
  accounting/cost model/benchmark engine 없음).
  - `LongTermMomentumStrategy`: cross-sectional 모멘텀, lookback
    6/9/12/18개월 · rebalance 월/분기 범위 문서화(grid search 없음),
    decision-step 카운트가 아니라 실제 경과 캘린더 개월 수로 rebalance.
  - `TrendVolatilityStrategy`: 장기 이동평균 추세 필터 + 실현
    변동성 필터, 둘 다 통과하는 종목만 균등비중 보유, 아무것도
    통과 못하면 빈 포지션(가짜 fallback holding 없음).
  - `RiskControlledMomentumStrategy`: 모멘텀 랭킹 + inverse-volatility
    사이징 + 전략 내부 전용 `max_position_weight` 캡 — **`risk.config.
    RiskConfig`와 완전히 무관**함을 모듈 docstring과 ADR-0029에 명시
    (지침 section 17의 "연구 전략 내부 allocation과 production risk
    limit을 혼동하지 않는다" 요구사항).
- **Train/Validation/Test 분할 + Walk-Forward 윈도우 생성기**
  (`strategy_research/splits.py`): 순수 날짜 함수, 실 데이터 없이도
  전부 테스트 가능. `build_chronological_split`(시간순 분할, random
  shuffle 없음), `generate_walk_forward_windows`(rolling window,
  데이터 부족 시 빈 리스트를 정직하게 반환 — 억지 구현 없음).
- **분류 체계 + multiple-testing 로그**
  (`strategy_research/classification.py`, `research_log.py`):
  `CandidateClassification`은 `REJECTED`/`INCONCLUSIVE`/
  `PROMISING_CANDIDATE` 3개 값만 존재 — `PROVEN_ALPHA`/`VERIFIED_ALPHA`
  값 자체가 구조적으로 없음. `classify_candidate`는
  `has_real_evaluation_data=False`이면 무조건 `INCONCLUSIVE`를
  반환(이번 phase의 모든 평가가 이 경우). `ResearchLog`는 거부된
  후보를 포함해 평가된 모든 후보를 보존(승자만 남기고 삭제하지 않음).
- **연구 러너**(`strategy_research/runner.py`): 동일 전략을 gross
  (zero-cost)와 net(Phase 2의 실제 기본 `TransactionCostModel`/
  `SlippageModel`, 무수정)로 각각 1회씩 실행해 비교, 설정된 SPY
  벤치마크와 비교. 신규 비용/벤치마크 계산 로직 없음.
- **결정론적 다년치 SYNTHETIC fixture**
  (`tests/strategy_research/research_helpers.py`): closed-form 수식
  기반(랜덤 없음), ~3년(783 거래일) 5종목 시계열 — 어디서나 SYNTHETIC/
  TEST FIXTURE로 명시, 실 데이터인 것처럼 표현한 곳 없음.
- **신규 테스트 40개**: no-future-leakage(미래 데이터 유무와 무관하게
  과거 시점 신호 동일), 전략별 결정론/가설 sanity(추세 종목 선택,
  추세+변동성 필터 정확성, inverse-vol 가중치 순서, 포지션 캡 준수),
  train/val/test 경계 강제, walk-forward 윈도우 정확성(빈 리스트 케이스
  포함), 분류/research log 동작, gross vs net 비용 통합, 벤치마크 비교,
  재현성, DuckDB 기반(InMemory 아님) backtest 실행 + 엔진 재시작,
  정적 소스 스캔 기반 보안 경계(`os.environ`/wall-clock/`random`/
  네트워크/broker import 전무 확인) — 자체 docstring의 "os.environ"
  텍스트 언급이 스캐너 오탐을 유발한 것을 발견하고, 스캐너를 약화시키지
  않고 docstring 표현만 수정해 해결(Phase 21의 동일 패턴 재사용).
- **신규 문서**: ADR-0029(전략 연구 프레임워크 8개 결정),
  `STRATEGY-RESEARCH-REPORT.md`(DATA/STRATEGIES/VALIDATION/
  CLASSIFICATION — 4개 전략 전부 INCONCLUSIVE, "검증된 알파" 표현
  없음), `PRODUCTION-READINESS-MATRIX.md`/`MARKET-DATA-PROVIDER.md`
  Phase 23 섹션 추가. README.md/PROJECT_STATUS.md 갱신(이 항목).
- **Toss/Live 활성화 코드는 전혀 건드리지 않음** — `src/broker/toss/*`,
  `LiveTradingSession`, Decision/Risk 로직, 모델 승인/배포, 실제
  broker 주문 제출 전부 이번 Phase 범위 밖.
- 기존 1547개 테스트 전부 삭제/약화 없이 유지 + 신규 40개 추가.
  최종 **1587 passed**.

### In Progress (Session 24 — Phase 23)

없음 — 이번 세션 작업 완료.

### Blocked (Session 24 — Phase 23)

- Live Trading 활성화 — 변경 없음, Toss capability 4종이 여전히
  `CapabilityStatus.UNKNOWN`인 한 구조적으로 불가.
- 실 시장 데이터 ingestion — 재확인 결과 여전히 `BLOCKED`(egress
  차단). `scripts/ingest_real_market_data.py`가 외부 환경에서의
  재실행 경로.
- 실 데이터 기반 전략 평가/Walk-Forward 실제 적용/PBO·Deflated Sharpe
  채택 — 전부 위 ingestion BLOCKED 상태에 종속.

### Decision Required (Session 24 — Phase 23)

1. (Phase 17-22에서 이어짐) `RiskConfig.max_turnover`의 None-semantics
   — 변경 없음, 여전히 미결.
2. (Phase 20/22에서 이어짐) risk 기본값 3개 최종 승인 — 변경 없음,
   여전히 사용자 승인 대기.
3. (Phase 16에서 이어짐) cancel-on-shutdown 자동화 — 변경 없음.
4. (Phase 18-22에서 이어짐) Walk-Forward/PBO/Deflated Sharpe 채택 —
   변경 없음, DEFER 유지(모델-진화 레벨 trigger 미발생 + 이번 phase가
   확인한 전략-레벨 실 데이터 부재가 이유 추가).
5. (Phase 21에서 이어짐) 실제 Toss 계좌 credential 확보 + 사람의
   운영 검증 — 여전히 유일하게 자동화 세션이 완료할 수 없는 항목.

### Known Issues (Session 24 — Phase 23)

- 이번 phase가 산출한 모든 전략 성과 지표는 SYNTHETIC fixture
  기반이며, 실 시장 데이터에서의 성과를 전혀 나타내지 않는다 —
  `STRATEGY-RESEARCH-REPORT.md`에 반복적으로 명시했으나, 이 문서를
  읽지 않고 코드의 테스트 결과만 보는 미래 세션/사람이 착각할 위험은
  구조적으로 남아있다(문서화 외의 기술적 방지 장치는 없음).
- 그 외 Phase 22까지의 Known Issues 전부 유지.

### Architecture Changes (Session 24 — Phase 23)

`src/strategy_research/`(신규 패키지, 8개 모듈),
`scripts/ingest_real_market_data.py`(신규) — 전부 기존 코드에 대한
순수 추가. 기존 `src/backtest/*`, `src/broker/*`, `src/risk/*` 등
어떤 기존 모듈도 수정하지 않음(strategy_research는 이들을 import해서
재사용할 뿐).

### Toss API Status (Session 24 — Phase 23)

변경 없음(Phase 21 상태 그대로): `CapabilityStatus` 전부 `UNKNOWN`
유지 — 이번 Phase는 Toss 코드를 전혀 건드리지 않았음.

### Last Validation (Session 24 — Phase 23)

`python -m pytest tests/ -q` — baseline **1547 passed** → 최종
**1587 passed, 0 failed, 0 skipped**. 기존 1547개 테스트 전부
삭제/약화 없이 유지, 신규 40개 추가.

### Next Task (Session 24 — Phase 23)

1. `scripts/ingest_real_market_data.py`를 실 네트워크 접근이 가능한
   환경에서 실행 — 실 시세 데이터 확보의 유일한 남은 단계.
2. 실 데이터 확보 후: `strategy_research.runner.run_gross_and_net`을
   실제 16종목 유니버스에 대해 실행, `ResearchLog`에 실제
   `CandidateEvaluation` 기록, `classify_candidate`를
   `has_real_evaluation_data=True`로 처음 호출.
3. 실제 Toss 계좌 credential 확보 + 사람의 운영 검증(위 Decision
   Required #5) — 여전히 유일하게 남은 Toss 관련 항목.
4. 위 Decision Required 5건에 대한 사람의 판단.

## Previous Subtask (Session 23 — Phase 22)

**Phase 22 — Real-Data Paper Trading / US Long-Term System Hardening**
(Live Trading은 여전히 구조적으로 비활성 — Toss capability가
`CapabilityStatus.UNKNOWN`인 한 활성화 불가, 이번 Phase는 Toss 코드를
전혀 건드리지 않았으므로 Phase 21의 사유가 그대로 유지된다). 사용자가
실 Toss 자격증명을 여전히 제공할 수 없다는 전제 아래, "1,000만원 상당
가상 자본으로 미국 주식 장기 Paper Trading을 반복 실행할 수 있는" 상태를
목표로 Toss 이외의 모든 부분을 강화했다.

### Completed (Session 23 — Phase 22)

- **Git/Branch Integrity 선행 확인**: Phase 21 HEAD
  (`2158c362944b31775509f54a4e99042267d473de`)를 `git rev-parse`로 직접
  재확인, 실제 ancestor임을 확인 후 `claude/phase-22-us-longterm-
  paper-trading` 브랜치를 해당 HEAD에서 직접 생성. Baseline **1511/1511
  테스트 통과** 확인(추측하지 않고 실제 실행) 후 구현 시작.
- **16종목 US 장기 Paper Trading 유니버스 채택**: AAPL/MSFT/NVDA/AMZN/
  GOOGL/META/AVGO/TSLA/JPM/V/MA/COST/WMT/JNJ/XOM/SPY — Phase 20의 이전
  목록을 대체(`MARKET-DATA-PROVIDER.md` Phase 22 섹션, 이전 목록은
  역사적 참조로 보존).
- **Stooq를 2차(fallback) 시장 데이터 provider로 신규 구현**
  (`src/data_infra/providers/stooq*.py`) — API 키 불필요 CSV 엔드포인트
  (Tier 2 근거, ADR-0028). 가격 데이터만 제공, corporate action(분할/
  배당) 데이터는 전혀 없음을 `metadata()["supports_corporate_actions"]
  = False`로 명시(꾸며내지 않음).
- **`FallbackDataProvider` 신규 구현**(`src/data_infra/providers/
  fallback.py`) — 1차 provider 실패 시 2차로 전환하되, 실제 응답한
  provider를 절대 숨기지 않음: 각 raw record에 `_answered_by` 스탬프,
  `normalize()`가 이를 근거로 정확한 provider의 정규화 로직으로
  라우팅 — `PriceBar.provenance.source`가 항상 진짜 출처를 가리킴.
  두 provider 모두 실패 시 `PermanentProviderError`가 둘 다의 이름을
  명시.
- **USD 표시 Paper 계좌 채택**(`src/broker/paper/us_longterm_config.py`)
  — 사용자가 명시한 `10,000,000` KRW 목표를 그대로
  `PAPER_CAPITAL_KRW_STATED_TARGET`으로 기록하되, 이 세션에서 검증
  가능한 실 KRW/USD 환율이 없으므로(모든 FX 데이터 소스 도메인 접근
  차단 — Phase 20 이후 동일) 환율을 조작하는 대신 지침이 명시적으로
  허용한 대안인 USD 표시 계좌를 채택: `PAPER_CAPITAL_USD = 10,000.0`
  (통화 환산이 아니라 자릿수만 맞춘 명시적 대체값, 어떤 환율도
  내포하지 않음). `MARKET-DATA-FX-REFERENCE.md`에 결정 기록.
- **결정론적 Buy & Hold reference 전략 신규 구현**
  (`run_buy_and_hold_paper_session`,
  `src/broker/paper/us_longterm_runner.py`) — 벽시계를 전혀 읽지 않고
  호출자가 명시한 `buy_time`에 세션의 현재 현금을 유니버스 전체에
  균등 배분해 심볼당 1회 MARKET BUY만 실행. 매 심볼 처리 직전 실제
  잔여 현금을 다시 조회해 나누는 방식(고정 최초 분할 아님)과
  `_COST_SAFETY_MARGIN=0.02`로 수수료/스프레드를 포함한 실제 비용
  경계에서의 과다지출을 방지 — 두 가지 모두 테스트를 실제로 실행해
  실패를 관찰한 뒤 수정(추측으로 통과시키지 않음, 상세는 커밋 로그).
  Momentum/rule-based 대비 회전율/이해가능성/재현성/비용모델
  호환성/leakage 검증가능성/장기 적합성 기준의 선정 근거는 ADR-0028에
  명시. Phase 2의 `TransactionCostModel`/`SlippageModel`을 변경 없이
  그대로 재사용 — 비용을 0으로 가정하지 않음. 항상 "baseline"으로만
  지칭, "alpha"/"전략" 단독으로 지칭하지 않음.
- **Risk policy 기본값을 실제 설정값으로 채택**(더 보수적, Phase 20
  제안 대비): `max_daily_loss=0.02`(비율, Phase 20과 동일),
  `max_turnover=2.0`(Phase 20 제안 3.0에서 하향), `max_order_
  frequency_per_hour=6`(Phase 20 제안 30에서 하향) — **INITIAL
  CONSERVATIVE SYSTEM DEFAULT**로만 명시, 재무적 진실이 아니며 실
  Live 계좌에 자동 적용되지 않음(`LIVE-RISK-POLICY.md` Phase 22
  섹션).
- **None-semantics Option B 채택**(`src/broker/live/safety_gate.py`)
  — `evaluate_safety_gate`가 `LiveTradingConfig.max_daily_loss`
  또는 `max_order_frequency_per_hour`가 `None`이면 그 자체를 `SAFETY
  GATE FAILURE`로 취급하도록 변경(Phase 17-20에서 미결이던 Option
  A/B 중 이번 Phase 지침이 명시적으로 B를 지시). **`RiskConfig.
  max_turnover`는 범위 밖** — 게이트가 `LiveTradingConfig`만 보고
  별도 config 객체인 `RiskConfig`는 구조적으로 볼 수 없어 여전히
  미결(`LIVE-RISK-POLICY.md`에 명시). 회귀 테스트 5개 신규
  (`TestRiskLimitNoneSemanticsOptionB`) — 이 변경이 기존 ~20개 안전
  게이트 통과 테스트를 깨지 않도록 호출부 하나하나를 실제로 읽고
  필요한 6개만 수정, 불필요한 4개는 건드리지 않음(과잉 수정 방지).
  Paper Trading은 `evaluate_safety_gate`를 호출하지 않으므로 영향
  없음.
- **전체 lineage 재시작 통합 테스트 신규 작성**
  (`tests/integration/test_us_longterm_paper_trading_lineage.py`) —
  TiingoDataProvider(TEST FIXTURE 데이터) → IngestionRunner →
  실제 온디스크 DuckDB → point-in-time `get_bars` → `InMemoryPaper
  MarketDataSource` → Buy & Hold runner → `PaperTradingSession`/
  `PaperBrokerAdapter` → Trade Journal → Monitoring
  (`collect_broker`) → Performance Report(`compute_paper_performance
  _report`) → `engine.close()` 후 재시작 → 원본 raw bar/trade/order가
  변경 없이 그대로 복원됨을 확인. 실제 네트워크 호출 없음, 전부
  TEST FIXTURE/SYNTHETIC로 명시.
- **Data Quality Framework에 timestamp monotonicity 체크 추가**
  (`src/data_infra/quality.py`) — 기존 체크들은 전부 내부적으로
  timestamp 기준 재정렬 후 분석하므로, provider 응답이 시간순이
  아닌 경우를 감지하지 못하던 gap을 신규 체크로 해소(정확한 동일
  timestamp 중복은 기존 `duplicate_records` ERROR가 그대로 담당,
  이 체크는 실제 역전만 WARNING으로 표시).
- **`.gitignore` 강화**: `*.duckdb`/`*.duckdb.wal`/`*.db`/`*.parquet`/
  `*.csv` 패턴 추가(사전 방어 — `git ls-files`로 현재 추적 중인 해당
  확장자 파일이 없음을 먼저 확인 후 추가).
- **신규 문서**: ADR-0028(Phase 22 운영 모델 전체 8개 결정 기록).
  `LIVE-RISK-POLICY.md`(Phase 22 섹션 — 보수적 제안값 + Option B
  적용 기록), `MARKET-DATA-FX-REFERENCE.md`(Phase 22 결정 기록),
  `MARKET-DATA-PROVIDER.md`(16종목 유니버스 갱신).
  README.md/PROJECT_STATUS.md 갱신(이 항목).
- **Toss/Live 활성화 코드는 전혀 건드리지 않음** — `src/broker/toss/*`,
  `LiveTradingSession` 자동 승인, Decision/Risk 로직, 모델 자동
  승인/배포, 실제 broker 주문 제출, credential 저장 전부 이번 Phase
  범위 밖(instruction 명시적 경계).
- 기존 1511개 테스트 전부 삭제/약화 없이 유지 + 신규 36개 추가.
  최종 **1547 passed**.

### In Progress (Session 23 — Phase 22)

없음 — 이번 세션 작업 완료.

### Blocked (Session 23 — Phase 22)

Live Trading 활성화 — 변경 없음. Toss capability 4종이 여전히
`CapabilityStatus.UNKNOWN`인 한 구조적으로 불가(Phase 21과 동일한
사유, 이번 Phase는 Toss 코드를 전혀 수정하지 않음).

### Decision Required (Session 23 — Phase 22)

1. (Phase 17-20에서 이어짐, 이번 Phase가 `max_daily_loss`/
   `max_order_frequency_per_hour` 2개에 한해 Option B로 코드
   차원에서는 해소) `RiskConfig.max_turnover`의 None-semantics
   (Option A vs B) — 안전 게이트가 이 필드를 구조적으로 볼 수 없어
   여전히 미결.
2. (Phase 20에서 이어짐, 이번 Phase가 더 보수적인 값으로 갱신)
   `max_daily_loss=0.02`/`max_turnover=2.0`/
   `max_order_frequency_per_hour=6` 최종 승인 여부 — 여전히 사용자
   승인 대기, 자동 적용되지 않음.
3. (Phase 16에서 이어짐) cancel-on-shutdown 자동화 여부 — 변경 없음
   (Live 기준, Paper는 필요 시 세션 종료 시 시뮬레이션 상태 정리
   가능하나 이번 Phase에서 별도 구현하지 않음).
4. (Phase 18-20에서 이어짐) Walk-Forward/PBO/Deflated Sharpe 채택
   여부 — 변경 없음, DEFER 유지(어떤 trigger 조건도 아직 미발생).
5. (Phase 21에서 이어짐) 실제 Toss 계좌 credential 확보 + 사람의
   운영 검증 — 이번 Phase도 진전시킬 수 없는 유일한 항목(자동화
   세션이 스스로 완료할 수 없음).

### Known Issues (Session 23 — Phase 22)

- Stooq의 실제 네트워크 접근 가능 여부는 이 세션에서 검증 불가
  (`stooq.com`을 포함한 모든 시장 데이터 provider 도메인이 차단됨,
  Tiingo와 동일한 상황) — `UNKNOWN`으로 남김, provider 정확성과
  혼동하지 않음.
- `FallbackDataProvider`는 1차가 실패했을 때만 2차를 호출하는
  fallback 설계이며, 매 호출마다 두 provider를 모두 조회해
  교차검증하는 consensus 설계가 아님 — 두 provider가 같은 심볼/
  날짜에 대해 서로 다른 값을 가지고 있어도 fallback이 발동하지 않는
  한(1차가 성공하는 한) 그 불일치는 감지되지 않는다. 알려진 설계상
  한계로 기록.
- 그 외 Phase 21까지의 Known Issues 전부 유지(client_order_id →
  Toss orderId 매핑 프로세스 재시작 시 유실 등).

### Architecture Changes (Session 23 — Phase 22)

`src/data_infra/providers/stooq*.py`(신규), `src/data_infra/
providers/fallback.py`(신규), `src/broker/paper/us_longterm_*.py`
(신규), `src/broker/live/safety_gate.py`(2개 조건 추가, additive),
`src/data_infra/quality.py`(`timestamp_monotonicity` 체크 추가,
additive) — 전부 기존 호출부에 영향 없는 추가 또는, safety_gate의
경우 지침이 명시적으로 요구한 fail-closed 강화. Toss/Live 활성화/
Decision/Risk/모델 승인 계층은 무수정.

### Toss API Status (Session 23 — Phase 22)

변경 없음(Phase 21 상태 그대로): `submit_order` + 4개 capability
전부 구현/테스트 완료, `CapabilityStatus`는 전부 `UNKNOWN` 유지 —
이번 Phase는 Toss 코드를 전혀 건드리지 않았음.

### Last Validation (Session 23 — Phase 22)

`python -m pytest tests/ -q` — baseline **1511 passed** → 최종
**1547 passed, 0 failed, 0 skipped**. 기존 1511개 테스트 전부
삭제/약화 없이 유지, 신규 36개 추가.

### Next Task (Session 23 — Phase 22)

1. 실제 Toss 계좌 credential 확보 + 사람의 운영 검증(위 Decision
   Required #5) — 여전히 유일하게 남은 Toss 관련 항목.
2. 실 Tiingo/Stooq 네트워크 접근이 확보되면: 실 시세 수집, SPY
   total-return 벤치마크 실제 생성.
3. `RiskConfig.max_turnover`의 None-semantics 결정(위 Decision
   Required #1) — 안전 게이트에 새 plumbing을 추가할지 여부는 별도
   설계 결정 필요.
4. 위 Decision Required 5건에 대한 사람의 판단(risk policy 3개 값
   최종 승인 포함).

## Previous Subtask (Session 22 — Phase 21)

**Phase 21 — Toss Broker Adapter Completion** (Live Trading은 여전히
구조적으로 비활성 — Toss capability가 `CapabilityStatus.UNKNOWN`인 한
활성화 불가, 단 이제는 "미구현"이 아니라 "구현/테스트 완료, 운영
미검증"이 정확한 사유, `docs/operations/PRODUCTION-READINESS-MATRIX.md`
참조)

### Completed (Session 22 — Phase 21)

- **Git/Branch Integrity 선행 확인**: Phase 20 HEAD
  (`2bab1623ecf89b39365f23cb9bbb31e0b0ae4e1f`)를 `git rev-parse`/
  `git log`로 직접 재확인 — `origin/main`은 여전히 Phase 19
  (`1d0003f...`)에 머물러 있음을 확인(Phase 20이 main에 병합되지
  않았음, 이 세션이 통제할 필요 없는 이미 알려진 상태). merge commit
  0개, `2bab1623..HEAD` 0 commits(작업 시작 시점)을 확인 후 새
  `claude/phase-21-toss-broker-completion` 브랜치를 Phase 20 HEAD에서
  직접 생성. Baseline **1448/1448 테스트 통과** 확인(추측하지 않고
  실제 실행).
- **Toss 공식 스펙 Tier 1 근거 재확인**: 이 세션은 원본 OpenAPI JSON
  전문을 다시 갖고 있지 않으므로, Phase 20이 이미 직접 읽고
  `TOSS-API-GAP-ANALYSIS.md`에 추출해 둔 Tier 1 근거(엔드포인트/
  요청·응답 스키마/에러 코드)를 source of truth로 그대로 사용 — 이
  추출 자체가 원본을 직접 읽어 만들어진 것이므로 재추측이 아님.
- **4개 capability 실제 구현**(`src/broker/toss/adapter.py`,
  `endpoints.py`, `mapping.py`): `get_account`(`GET /api/v1/
  buying-power?currency=USD`, 기존 `X-Tossinvest-Account` 헤더 패턴
  재사용, 신규 account-discovery 로직 없음), `get_positions`(`GET
  /api/v1/holdings`, 손상된 항목 하나라도 있으면 부분 목록을 반환하지
  않고 전체를 실패 처리), `get_order_status`(`GET /api/v1/orders/
  {orderId}` 단건 상세 — 목록 엔드포인트 아님, `client_order_id →
  Toss orderId` 매핑은 `submit_order` 시점에 채워지는 어댑터 내부
  in-memory map으로 해결, `MockBrokerAdapter`의 기존 패턴 재사용),
  `cancel_order`(`POST /api/v1/orders/{orderId}/cancel`, 취소 응답의
  새 orderId를 원 주문 id와 절대 혼동하지 않도록 신규 additive 필드
  `BrokerOrderResponse.cancel_reference_id` 추가).
- **`BrokerOrderStatus` 확장**: 공식 스펙의 10개 상태값 중 기존에
  없던 `CANCEL_REJECTED`/`REPLACE_REJECTED` 2종 추가(additive, 기존
  8종 매칭 로직 전부 `==`/`in` 비교라 안전 확인 후 추가).
- **`get_capabilities()`는 의도적으로 변경하지 않음**: 4개 전부
  여전히 `CapabilityStatus.UNKNOWN`. `UNKNOWN`의 정의("연구로 존재는
  확인됐지만 end-to-end 독립 검증 안 됨")가 정확히 이번 Phase의
  결과이므로, `ENABLED`로 바꾸면 `evaluate_safety_gate` 동작을
  조용히 바꾸게 되어 이번 Phase 지침이 명시적으로 금지함(ADR-0027
  decision 5). Live Trading은 동일한 이유로 여전히 구조적 차단.
- **신규 테스트 63개**: mapping 단위 테스트(buying-power/holdings/
  order-detail/cancel 각각 성공/malformed/401/429/5xx/미확인 코드),
  adapter 레벨 테스트(4개 capability + idempotent double-cancel),
  `LiveTradingSession.reconcile_order`를 실제 `TossBrokerAdapter`로
  구동해 MATCHED/MISMATCH/UNKNOWN 3가지 결과를 전부 증명하는
  integration 테스트(`tests/integration/
  test_toss_live_reconciliation_integration.py`) — 전부 stub
  transport만 사용, 실제 네트워크 호출 없음.
- **기존 테스트 4개 갱신(약화 아님)**: `TestUnsupportedOperations`
  (더 이상 사실이 아닌 "미지원" 전제를 실제 구현된 동작 검증으로
  교체), order-status capability-gap 테스트(예외 대신 정직한
  `UNKNOWN` observation을 반환하는, 테스트 이름의 취지에 오히려 더
  부합하는 새 동작으로 갱신), endpoints 상수 테스트(`None` → 실제
  확정된 경로 문자열로 갱신) — 전부 이번 Phase가 의도적으로 만든
  동작 변화의 자연스러운 결과, regression 은폐 아님.
- **AST boundary scan 재실행**: `os.environ`/`os.getenv` 여전히
  `broker/toss/auth.py`/`data_infra/providers/tiingo_auth.py` 2곳
  으로만 제한됨을 재확인. `TossHttpTransport` 실사용 금지 스캔에서
  신규 테스트 파일 2개가 docstring 텍스트로 인한 오탐(false positive)
  이었음을 발견 — scan rule을 바꾸지 않고 docstring 표현만 수정해
  해결(가장 최소한의 수정).
- 기존 1448개 테스트 중 4개(위 언급)를 의도된 동작 변화에 맞춰
  갱신, 나머지 전부 삭제/약화 없이 유지. 최종 **1511 passed**.

### In Progress (Session 22 — Phase 21)

없음 — 이번 세션 작업 완료.

### Blocked (Session 22 — Phase 21)

Live Trading 활성화 — 변경 없음. Toss capability 4종이 여전히
`CapabilityStatus.UNKNOWN`(코드 구현/테스트는 완료됐으나 실제 계좌
대상 운영 검증이 없음)인 한 구조적으로 불가.

### Decision Required (Session 22 — Phase 21)

1. (Phase 17/18/19/20에서 이어짐) Risk policy `None` 값 관련 — 변경
   없음.
2. (Phase 20에서 이어짐) daily loss/turnover/order frequency 제안값
   (2%/3.0/30) 승인 여부 — 변경 없음, 여전히 사용자 승인 대기.
3. (Phase 16에서 이어짐) cancel-on-shutdown 자동화 여부 — 이번
   Phase가 `cancel_order`를 실제로 구현했다고 해서 자동화하지 않음
   (별도 정책 결정, instruction section 22).
4. (Phase 18/19/20에서 이어짐) Walk-Forward/PBO/Deflated Sharpe 채택
   여부 — 변경 없음.
5. **(신규, 이번 Phase가 유일하게 실질적으로 앞당긴 항목)** 실제
   Toss 계좌 credential 확보 + 사람의 운영 검증 — 코드/테스트는
   완료됐으므로, 이제 남은 유일한 단계는 실제 계좌를 가진 사람이
   각 endpoint를 직접 확인하는 것뿐이다. 자동화 세션이 스스로 완료할
   수 없는 단계.

### Known Issues (Session 22 — Phase 21)

- `get_positions()`의 반환 타입(`tuple[BrokerPosition, ...]`)은
  "포지션 0개"와 "조회 실패"를 구조적으로 구분할 수 없다(instruction
  section 7이 이미 알려진 문제로 명시). 이번 Phase는 실패 시 예외를
  발생시켜 이 모호성을 최대한 좁혔으나(성공한 빈 목록만 `()`), 근본
  해결(Protocol 자체 변경)은 이번 Phase 범위 밖.
- `client_order_id → Toss orderId` 매핑이 in-memory 전용이라
  프로세스 재시작 시 유실됨(`TossBrokerAdapter.__init__`의 자체
  docstring에 명시). `broker_responses.broker_order_id`가 이미
  영속화되어 있어 향후 rehydration 구현이 가능하나 이번 Phase는
  만들지 않음.
- `GET /api/v1/accounts`(계좌 목록 조회/discovery)는 Tier 1 문서화만
  되고 연결하지 않음 — 기존 단일 계좌 사전설정 모델(`TOSS_ACCOUNT_ID`)
  을 그대로 재사용했기 때문.
- 그 외 Phase 20까지의 Known Issues 전부 유지.

### Architecture Changes (Session 22 — Phase 21)

`BrokerOrderResponse.cancel_reference_id`(신규 additive optional
필드), `BrokerOrderStatus.CANCEL_REJECTED`/`REPLACE_REJECTED`(신규
additive enum 값) — 둘 다 기존 호출부에 영향 없음(keyword-only 생성,
`==`/`in` 비교만 사용 확인). 그 외 `broker/toss/*.py` 내부 구현
추가만 존재, Protocol/스토리지 스키마 변경 없음.

### Toss API Status (Session 22 — Phase 21)

코드: `submit_order` + 4개 신규(`get_account`/`get_positions`/
`get_order_status`/`cancel_order`) 전부 구현/테스트 완료.
`CapabilityStatus`: 여전히 5개(취소/상태조회/계좌/포지션) 중 4개가
`UNKNOWN`(주문생성만 확인된 상태에서 변화 없음) — **구현 완료가 곧
ENABLED를 의미하지 않는다**는 이번 Phase의 핵심 원칙. 실제 계좌 검증
전까지 이 상태 유지.

### Last Validation (Session 22 — Phase 21)

`python -m pytest tests/ -q` — baseline **1448 passed** → 최종
**1511 passed, 0 failed, 0 skipped**. 기존 테스트 중 의도된 동작
변화를 반영한 4개를 제외하고 전부 삭제/약화 없이 유지.

### Next Task (Session 22 — Phase 21)

1. 실제 Toss 계좌 credential 확보 + 사람의 운영 검증(위 Decision
   Required #5) — 이것이 남은 유일한 Toss 관련 항목이다.
2. 실 Tiingo API 키/네트워크 접근이 확보되면(Phase 20에서 이미 제안):
   실 시세 수집, SPY total-return 벤치마크 실제 생성.
3. 위 Decision Required 5건에 대한 사람의 판단(risk policy 승인 포함).

## Previous Subtask (Session 21 — Phase 20)

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
  **실제 계좌 대상 운영 검증** — Phase 21에서 코드 구현/테스트는
  완료했으나(`ADR-0027`), `CapabilityStatus`는 여전히 4개 전부
  `UNKNOWN`이다. 남은 유일한 단계는 실제 credential을 가진 사람이
  각 endpoint를 직접 검증하는 것뿐이며, 이는 자동화 세션이 스스로
  완료할 수 없다(instruction 상 실제 Toss API를 호출하는 자동 테스트
  자체가 금지됨).

---

## Next Recommended Task

(이 섹션은 Phase 9~10 시점 이후 갱신되지 않고 있던 것을 Phase 18에서
전면 갱신했고, Phase 20/21에서 다시 갱신함. legacy DECISION REQUIRED
항목은 위 "Blocked"/"Current Phase → Decision Required" 섹션에서 계속
추적한다.)

1. **실제 Toss 계좌 credential 확보 + 사람의 운영 검증** — Phase 21이
   4개 capability를 전부 코드로 구현하고 테스트했으므로(ADR-0027),
   남은 유일한 단계는 실제 계좌를 가진 사람이 각 endpoint(계좌조회/
   포지션조회/주문상태조회/취소)를 직접 호출해 확인하고
   `CapabilityStatus`를 `ENABLED`로 승격하는 것뿐이다. 이 저장소의
   자체 원칙상 자동화 세션이 실제 Toss API를 호출하는 것 자체가
   금지되어 있으므로, 이것은 **사람만 완료할 수 있는 유일한 다음
   단계**다.
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
   (`docs/research/walk-forward-pbo-deflated-sharpe.md` §9), (d)
   cancel-on-shutdown 자동화 여부 — Phase 21이 `cancel_order`를
   구현했다고 해서 자동으로 결정되지 않는 별도 정책 질문.
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
   Phase마다 재확인할 것 — Phase 17/18/20/21 모두 이를 저장소 전체
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
