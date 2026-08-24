"""Baseline experiment runner.

See docs/specifications/PHASE-4-baseline-models-and-storage.md sections
9-12 (Part B). Wires a baseline Strategy (Phase 2's `BuyAndHoldStrategy`
or `SimpleMomentumStrategy` -- no new strategy code is introduced here,
per this phase's "AI 이전에 신뢰할 수 있는 Baseline" mandate: the strategies
already exist and already share `BacktestEngine`; what Phase 4 adds is
running them through the same engine on equal terms, persisting the
result, and reporting it against the benchmark without picking a winner
by return alone) through:

    BacktestEngine.run()
        -> trade_journal.backtest_adapter.ingest_backtest_result()
        -> (optional) ExperimentRepository.record()
        -> (optional) ExperienceRepository.record_many()

This module does not modify BacktestEngine, TradeJournalRepository, or
any Phase 2/3 type -- it only calls their existing, already-tested public
interfaces in sequence (the same "read-only with respect to prior phases"
discipline `ingest_backtest_result` itself follows, ADR-0009).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from data_infra.repository import DataRepository

from backtest.engine import BacktestConfig, BacktestEngine, BacktestResult
from backtest.experiment import ExperimentTracker
from backtest.strategy import Strategy

from storage.experiment_repository import ExperimentRepository
from storage.experience_repository import ExperienceRepository

from trade_journal.backtest_adapter import IngestSummary, ingest_backtest_result
from trade_journal.enums import TradeProvenance
from trade_journal.experience import build_experience_records
from trade_journal.models import ExperienceRecord
from trade_journal.repository import TradeJournalRepository


@dataclass(frozen=True)
class BaselineRunResult:
    label: str
    backtest_result: BacktestResult
    ingest_summary: IngestSummary
    experience_records: tuple[ExperienceRecord, ...]


def run_baseline(
    strategy: Strategy,
    label: str,
    repository: DataRepository,
    config: BacktestConfig,
    *,
    journal: TradeJournalRepository,
    experiment_repo: Optional[ExperimentRepository] = None,
    experience_repo: Optional[ExperienceRepository] = None,
    experiment_tracker: Optional[ExperimentTracker] = None,
) -> BaselineRunResult:
    """Runs one baseline strategy end-to-end and, when the optional
    persistence arguments are given, durably records the experiment and
    the experience records it produced. Omitting `experiment_repo`/
    `experience_repo` (both default None) still runs and journals the
    backtest -- persistence to those two registries is additive, not a
    precondition for the backtest or the journal itself to work (mirrors
    how Phase 2/3 already run fully in-process without a durable store).

    `experiment_tracker`: `BacktestEngine` defaults to a *fresh*
    `ExperimentTracker` per instance (Phase 2 spec section 13), which
    allocates ids starting at "BT-000001" every time. Comparing more than
    one baseline (the whole point of this module) therefore requires
    passing the **same** `ExperimentTracker` instance across every
    `run_baseline` call in a comparison run -- otherwise two different
    strategies' results collide on the same experiment_id and the second
    one silently fails to persist (ExperimentRepository.record is
    idempotent on experiment_id, by design, so a collision looks like
    "nothing happened" rather than an error). `run_multiple_baselines`
    below does this automatically; call this function directly only when
    you are deliberately managing tracker sharing yourself.
    """
    engine = BacktestEngine(repository, config, strategy, experiment_tracker=experiment_tracker)
    result = engine.run()

    summary = ingest_backtest_result(
        journal, result, config, provenance=TradeProvenance.HISTORICAL_SIMULATION
    )

    if experiment_repo is not None:
        experiment_repo.record(result.experiment)

    trade_ids_this_run = {
        trade.trade_id
        for trade in journal.list_trades(provenance=TradeProvenance.HISTORICAL_SIMULATION)
        if trade.experiment_id == result.experiment.experiment_id
    }
    all_records = build_experience_records(journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
    records_this_run = tuple(r for r in all_records if r.trade_id in trade_ids_this_run)

    if experience_repo is not None and records_this_run:
        experience_repo.record_many(records_this_run)

    return BaselineRunResult(
        label=label,
        backtest_result=result,
        ingest_summary=summary,
        experience_records=records_this_run,
    )


def run_multiple_baselines(
    strategies: dict,
    repository: DataRepository,
    config: BacktestConfig,
    *,
    journal: TradeJournalRepository,
    experiment_repo: Optional[ExperimentRepository] = None,
    experience_repo: Optional[ExperienceRepository] = None,
) -> list[BaselineRunResult]:
    """Runs every ``{label: strategy}`` entry against the *same*
    ``BacktestConfig``/``DataRepository`` (same period, capital, cost
    model, benchmark) with a single shared ``ExperimentTracker``, so the
    resulting experiment_ids are distinct and every run is directly
    comparable (Phase 4 spec section 10 -- baselines are compared on
    equal terms, not cherry-picked configurations)."""
    tracker = ExperimentTracker()
    return [
        run_baseline(
            strategy, label, repository, config,
            journal=journal, experiment_repo=experiment_repo, experience_repo=experience_repo,
            experiment_tracker=tracker,
        )
        for label, strategy in strategies.items()
    ]
