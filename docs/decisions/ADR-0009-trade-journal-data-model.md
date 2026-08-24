# ADR-0009: Trade Journal Data Model, Reuse, and Immutability

**Status:** Accepted
**Date:** 2026-08-24
**Deciders:** Claude Code (Phase 3 session), pending project owner review
**Related documents:** `PROJECT_MASTER_PLAN.md` §30-36, §92,
`docs/specifications/PHASE-3-trade-journal.md`, Phase 2
`src/backtest/{orders,fills,portfolio}.py`

---

## Context

`PROJECT_MASTER_PLAN.md` §92 states the Trade Journal must be "경험
메모리," not a log table — meaning every field a future Learning Engine
(Phase 9), Counterfactual/Attribution module (Phase 10), or Model
Evolution process (Phase 11) might need should already have a place in
the schema, even if it cannot be populated yet. At the same time,
Phase 2 already produces immutable `Order`, `Fill`, and `PortfolioView`
types that carry most of the trade-level detail the Journal needs. This
ADR fixes three intertwined decisions: how much of Phase 2's types to
reuse versus redefine, how to guarantee immutability, and how to keep
Journal records honest about what is and is not really known.

## Decision

### 1. Embed Phase 2 types directly; do not redefine them

`DecisionSnapshot.order: Optional[Order]` and `TradeRecord.fill: Fill`
hold the actual Phase 2 objects, not field-by-field copies. Both `Order`
and `Fill` are already `@dataclass(frozen=True)`, so embedding them adds
no mutability risk, and any future Phase 2 field addition (e.g., a
richer rejection taxonomy) becomes visible to the Journal automatically
rather than requiring a parallel schema update.

### 2. Every Journal record type is `@dataclass(frozen=True)`

Immutability (`PROJECT_MASTER_PLAN.md` §11, applied to the Journal
itself) is enforced by the Python language (`FrozenInstanceError` on
assignment), not by a documented convention. This is the same choice
Phase 1 (`data_infra.models`) and Phase 2 (`backtest.orders.Order`,
`backtest.fills.Fill`, `backtest.portfolio.PortfolioView`) already made
for their own domain types — Phase 3 continues the pattern rather than
introducing a different one.

### 3. Corrections are additive records, never in-place edits

`TradeJournalRepository` has no `update_*`/`delete_*` method at all —
the interface itself makes silent mutation structurally unreachable. A
correction is `record_correction(target_type, target_id, reason,
corrected_fields, ...)`, appended alongside the original. This mirrors
`PROJECT_MASTER_PLAN.md` §11's Raw-layer immutability pattern
(RAW → validation → corrected/normalized version, never an overwrite),
applied one layer up, to the Journal's own records rather than to
market data.

### 4. Unknown fields are `None`, never estimated

Every field that requires a module not yet built (Prediction, Regime
Detection, Risk Engine, sector/factor data) is `Optional` and populated
`None` by every builder in this phase. Nothing in `src/trade_journal/`
computes a plausible-looking placeholder for `prediction_error`,
`market_regime`, `expected_return`, etc. The two exceptions —
`execution_error` (Post Trade Analysis) and the `execution` component of
`AttributionResult` — are populated because they are genuinely
computable from data Phase 3 already has (Fill/Portfolio arithmetic),
not because a plausible guess was available.

### 5. Two honestly-documented reconstruction limitations, not silent approximations

`BacktestResult` (Phase 2) does not expose per-decision data-version or
per-step portfolio-state snapshots. Rather than either (a) modifying
`BacktestEngine` to expose them — a Phase 2 architectural change outside
this phase's mandate — or (b) silently approximating them and presenting
the result as exact, Phase 3's `ingest_backtest_result` reconstructs
`portfolio_state` by replaying fills (exact with respect to fills,
documented as excluding corporate-action effects between fills) and
leaves per-decision `data_version` as `None` (only the trade-level
`Fill.data_version` is populated). Both limitations are stated in the
Phase 3 spec (§13.2-13.3) and raised as `DECISION REQUIRED` candidates
for a future Phase 2 follow-up, rather than resolved unilaterally here.

## Alternatives Considered

- **Redefine Order/Fill/Portfolio-equivalent types inside
  `trade_journal.models`** (fully decoupling the Journal from Phase 2):
  Rejected — this would duplicate Phase 2's already-correct,
  already-tested fields, create two sources of truth for the same
  execution facts, and require the Journal to be updated every time
  Phase 2's types evolve. Direct embedding removes that duplication at
  the cost of a Journal-side dependency on `backtest.*` for the
  Phase 2-specific adapter only (`backtest_adapter.py`) — the core
  models (`models.py`, `repository.py`) still only depend on the
  embedded types' presence via `Optional`/duck-typed usage, not on
  `backtest` internals otherwise (`data_infra` is the only hard
  dependency of the core Journal package, per the Phase 3 spec's module
  layout, §3.1).
- **Mutable Journal records with an explicit `updated_at` field instead
  of a separate `CorrectionRecord`**: Rejected — this reintroduces
  exactly the "silently changes what the AI is understood to have known"
  risk `PROJECT_MASTER_PLAN.md` §11 and this project's fail-closed
  philosophy exist to prevent. An append-only correction trail is
  strictly more auditable at a small storage cost.
- **Extending `BacktestEngine` now to expose per-decision data-version
  and portfolio-state events**: Rejected for this phase — it is a
  legitimate improvement, but it is Phase 2 architecture, and changing
  it unilaterally inside a Phase 3 session would violate this project's
  change-management discipline (`PROJECT_MASTER_PLAN.md` §19.1: raise,
  don't silently resolve, a cross-phase architecture question). Flagged
  as `DECISION REQUIRED` instead.
- **Approximating per-decision `data_version` from repository state at
  ingestion time** (re-querying "what was the data version around that
  date"): Rejected — this is precisely the "재구성이 아니라 보존" failure
  mode the Point-in-Time principle (Phase 3 spec §4) exists to prevent;
  a re-derived value could silently answer a different question than
  "what version actually priced this decision."

## Consequences

### Positive

- Zero duplication of Phase 2's execution facts; Phase 2's own
  correctness and test coverage (reproducibility, execution timing,
  cost/slippage accuracy) transfers directly to whatever the Journal
  stores about a trade, since it stores the *same objects*.
- The correction-record pattern gives the Journal the same auditable,
  tamper-evident history property Phase 1 already established for
  market data — consistent behavior across the whole system's
  historical record, not a special case for trades.
- Every "not yet known" field is visibly `None` rather than plausible-
  looking, preventing a future Learning Engine from accidentally
  training on fabricated signal.

### Negative / Trade-offs

- `DecisionSnapshot.data_version` is `None` for every Phase 2-sourced
  record today — a real gap for any future analysis that needs
  per-decision data lineage precision, not just per-trade or per-run.
  Accepted as an explicit, visible limitation rather than a fabricated
  value.
- `portfolio_state` reconstruction via fill-replay is silently wrong
  (not merely imprecise) for a backtest window containing a corporate
  action between fills, until Phase 2 is extended to expose those
  events. Mitigated by documentation, not by code, in this phase.

## Status of Implementation at Time of This ADR

Implemented in `src/trade_journal/models.py`, `repository.py`,
`analysis.py`, `experience.py`, `backtest_adapter.py`, exercised by
`tests/trade_journal/`.
