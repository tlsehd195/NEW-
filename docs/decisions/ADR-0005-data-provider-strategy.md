# ADR-0005: Data Provider Strategy for Phase 1

**Status:** Accepted
**Date:** 2026-08-24
**Deciders:** Claude Code (Phase 1 session), pending project owner review
**Related documents:** `PROJECT_MASTER_PLAN.md` §21-22, §40-41,
`docs/specifications/PHASE-1-data-infrastructure.md` §19-20

---

## Context

The Phase 1 initialization instruction is explicit: "이번 Phase에서는
데이터 provider를 무작정 많이 추가하지 않는다" and requires that any real
provider selection weigh official documentation, API limits, licensing,
historical coverage, point-in-time capability, adjusted-data semantics,
cost, and stability — never adopting a provider merely because it is
free or convenient. `PROJECT_MASTER_PLAN.md` §22 additionally requires
that the system not be structurally dependent on any single provider.

## Decision

1. **No real external data provider is integrated in Phase 1.** The
   `DataProvider` interface (`fetch()`, `validate()`, `normalize()`,
   `metadata()`) is defined and is the only contract ingestion code
   depends on. The single implementation shipped in Phase 1 is
   `MockDataProvider`, a deterministic, in-process, fixture-based
   provider used purely for testing and to validate the design (Phase 1
   spec §14.1).
2. **Provider selection is deferred to a dedicated future decision**,
   triggered when Phase 2 (Backtesting) or a later phase actually needs
   real historical market data. That decision must be raised and
   recorded as its own ADR (e.g., `ADR-0006-data-provider-selection`)
   once a specific candidate is evaluated against the criteria in §3
   below — it is explicitly **not** pre-selected here.
3. **Provider independence is structural**: nothing outside
   `src/data_infra/provider.py` and its future real-provider adapters
   knows about a specific vendor's request/response shape. Swapping or
   adding a provider means writing a new `DataProvider` implementation;
   it does not touch `DataRepository`, the domain models, or any
   consumer code (Phase 1 spec §2.2, §12).
4. **Selection criteria for any future real provider** (to be applied,
   not applied now):
   - Official API documentation exists and is current.
   - Rate limits (requests/min, requests/day) are documented and
     enforceable by our `DataProvider` adapter's retry/backoff logic
     (Phase 1 spec ingestion design).
   - License terms for storage, redistribution, and commercial/research
     use are explicit. Any unclear term is recorded as `UNKNOWN` and
     treated as blocking for that use case (`PROJECT_MASTER_PLAN.md`
     §41; Phase 1 spec §20).
   - Historical coverage matches the backtest period the project
     actually intends to use.
   - The provider's data can be reasoned about in point-in-time terms
     (i.e., we can determine or reasonably approximate
     `available_time`/`publication_time` for its records — a provider
     that only exposes "current as of today" snapshots with no
     historical restatement information is a red flag for leakage risk).
   - Adjusted-price semantics (if the provider exposes adjusted data) are
     documented by the vendor clearly enough to satisfy Phase 1 spec
     §5.2's requirement that adjustment be explicit and reproducible.
   - Cost (including what happens beyond any free tier) and stability
     (uptime, deprecation history) are assessed — "free" alone is
     explicitly insufficient justification (`PROJECT_MASTER_PLAN.md`
     §40's closing rule, restated here).
5. **Security**: no provider API key exists in this repository or this
   phase. `.env.example` reserves `MARKET_DATA_API_KEY` as a name
   placeholder only (Phase 1 spec §20).

## Alternatives Considered

- **Integrate one well-known free market data API now** (e.g., to "get
  real data flowing" sooner): Rejected — this is exactly the pattern the
  initialization instruction forbids ("무료라는 이유만으로 핵심 데이터
  provider로 채택하지 않는다"). It would also risk locking in a provider
  before its point-in-time/licensing suitability has been evaluated,
  potentially requiring rework.
- **Integrate two or more providers now for redundancy**
  (`PROJECT_MASTER_PLAN.md` §22 mentions failover): Rejected for Phase
  1 — redundancy/failover across real providers is a legitimate future
  concern, but building it before a single provider has even been
  evaluated is speculative complexity Phase 1 explicitly avoids
  (`PROJECT_MASTER_PLAN.md` §84).
- **Skip building a `DataProvider` interface at all until a real
  provider is chosen**: Rejected — the interface is what makes the
  ingestion reliability properties (retry, idempotency, partial failure,
  checkpointing — Phase 1 spec §14 tests 8-11) testable now, against a
  mock, rather than only testable once a real, rate-limited external
  API exists. Building and testing this now removes risk from whichever
  future session integrates the first real provider.

## Consequences

### Positive

- No premature vendor lock-in; no unreviewed license or point-in-time
  risk is inherited from a hastily chosen "free" provider.
- Ingestion reliability logic (retry/backoff/idempotency/partial
  failure/checkpoint) is already built and tested against a
  deterministic mock, so integrating the first real provider later is a
  smaller, better-isolated task (write one adapter, reuse the tested
  ingestion runner).
- Downstream phases (Backtest, Feature Engine) are shielded from
  provider choice entirely, since they only ever see `DataRepository`.

### Negative / Trade-offs

- Phase 1 cannot validate its design against real-world data
  irregularities (actual missing days, real corporate action feed
  quirks, actual rate-limit behavior) — only against the mock scenarios
  the reference implementation was designed to cover. This is an
  accepted limitation; real-world validation happens once a provider is
  actually selected and integrated (tracked as future work, not silently
  assumed solved).
- No real historical data exists yet, so Phase 2 (Backtesting) cannot
  begin producing real results until a provider decision is made and
  executed. This is expected sequencing, not a defect of this ADR.

## Status of Implementation at Time of This ADR

`DataProvider` protocol and `MockDataProvider` implemented in
`src/data_infra/provider.py`. No real provider adapter exists.
