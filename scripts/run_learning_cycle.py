#!/usr/bin/env python3
"""Real Experience -> Learning Engine retraining CLI (Session 37, ADR-0113).

Closes the read side of a gap discovered this session: Phase 9's
Learning Engine (`trade_journal.experience.build_experience_records` ->
`learning.pipeline.run_learning_pipeline`) and real Paper/Live Trading
existed as fully-built, fully-tested, but never-connected pieces.
`orchestration.paper_runner.run_cycle` (ADR-0096/ADR-0097, widened this
session by ADR-0113 to also record a real, joinable `DecisionSnapshot`
and real `realized_pnl`/`realized_return`/`holding_period`) and
`scripts/run_paper_trading_cycle.py` are the write side; nothing
previously read the result back out to actually train from. This script
is that missing "read side": it builds real `ExperienceRecord`s from
whatever `--paper-store` a real `scripts/run_paper_trading_cycle.py` run
already populated, runs the full Data Cleaning -> Labeling -> Dataset ->
Training -> Evaluation chain (`learning.pipeline.run_learning_pipeline`),
and persists every stage through the real DuckDB-backed repositories
(`storage.learning_repository`) in the SAME `--paper-store` catalog file
(the same "one catalog file, several tables" pattern
`storage.trade_journal_repository`/`storage.paper_repository` already
share with `storage.data_repository`).

Read-only with respect to the Trade Journal -- this script never calls
`record_decision`/`record_trade` itself; `orchestration.paper_runner.
run_cycle` (via `scripts/run_paper_trading_cycle.py`) remains the only
writer.

**Honest current limitation, not hidden**: no `Strategy`/`DecisionAgent`
in this codebase sets `OrderIntent.features` yet (ADR-0048's own
documented gap), so every real `DecisionSnapshot`/`LabeledSample.features`
this script reads is `None` today -- `--trainer linear_regression`
would therefore always report `fitted=False, train_sample_count=0`
against real data right now, an honest "no real feature-based learning
is possible yet" result, not a bug in this script. The default trainer
is `mean_reward_baseline` for exactly this reason: it needs only
`LabeledSample.label_value` (`realized_return`, real as of ADR-0113's
fix to `orchestration.paper_runner.run_cycle` -- before that fix, EVERY
real Paper Trading `TradeRecord` had `realized_return=None` regardless
of this script, making a COMPLETED training run from real data
impossible no matter which trainer was chosen), so it is the first
trainer that can produce a genuinely non-trivial result from real Paper
Trading data today, in the same "baseline first, prove the pipeline end
to end" spirit `MeanRewardBaselineTrainer`'s own docstring already
documents.

Usage (run after at least one real scripts/run_paper_trading_cycle.py
invocation against the same --paper-store has produced some real
closed/realized trades):
    python3 scripts/run_learning_cycle.py \\
        --paper-store ./data/paper_trading_store \\
        --out ./data/learning_cycle_report.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from learning.linear_trainer import LinearRegressionTrainer  # noqa: E402
from learning.pipeline import run_learning_pipeline  # noqa: E402
from learning.trainer import MeanRewardBaselineTrainer  # noqa: E402

from storage.config import StorageConfig  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.learning_repository import (  # noqa: E402
    DuckDBCandidateModelRepository,
    DuckDBEvaluationRepository,
    DuckDBLearningExperimentRepository,
    DuckDBTrainingDatasetRepository,
)
from storage.trade_journal_repository import DuckDBTradeJournalRepository  # noqa: E402

from trade_journal.enums import TradeProvenance  # noqa: E402
from trade_journal.experience import build_experience_records  # noqa: E402


def _metrics_dict(m) -> dict:
    return {
        "sample_count": m.sample_count, "mean_absolute_error": m.mean_absolute_error,
        "mean_squared_error": m.mean_squared_error, "mean_label": m.mean_label,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--paper-store", required=True, type=Path,
        help="The same --paper-store a real scripts/run_paper_trading_cycle.py run already wrote to",
    )
    parser.add_argument(
        "--provenance", choices=["PAPER_TRADING", "LIVE_TRADING"], default="PAPER_TRADING",
        help="PAPER_TRADING is the default and the only provenance this project's own Live orchestration "
             "currently ever produces real experience for (Live activation remains structurally blocked -- "
             "see docs/operations/PRODUCTION-READINESS-MATRIX.md).",
    )
    parser.add_argument(
        "--trainer", choices=["mean_reward_baseline", "linear_regression"], default="mean_reward_baseline",
        help="See module docstring for why mean_reward_baseline is the honest default against real data today.",
    )
    parser.add_argument(
        "--feature-id", action="append", default=None, dest="feature_ids",
        help="Repeatable; required (at least one) when --trainer linear_regression",
    )
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.trainer == "linear_regression" and not args.feature_ids:
        print("FATAL: --trainer linear_regression requires at least one --feature-id", file=sys.stderr)
        return 1

    provenance = TradeProvenance[args.provenance]
    run_at = datetime.now(timezone.utc)

    engine = StorageEngine(StorageConfig(root_dir=args.paper_store))
    journal = DuckDBTradeJournalRepository(engine)

    records = build_experience_records(journal, provenance=provenance, created_at=run_at)
    print(f"Built {len(records)} real Experience record(s) from {args.paper_store} (provenance={provenance.value}).", flush=True)
    if not records:
        print(
            "FATAL: no real Experience records found for this provenance -- has "
            "scripts/run_paper_trading_cycle.py been run against this --paper-store yet?",
            file=sys.stderr,
        )
        engine.close()
        return 1

    trainer = (
        LinearRegressionTrainer(args.feature_ids) if args.trainer == "linear_regression"
        else MeanRewardBaselineTrainer()
    )

    result = run_learning_pipeline(journal, records, provenance=provenance, trainer=trainer, seed=args.seed, run_at=run_at)

    # Session 37 (ADR-0114): each repository's own `record()` MAY
    # reassign the id it was called with (natural-key idempotency --
    # e.g. DuckDBCandidateModelRepository.record allocates candidate_id
    # from a persistent DB sequence, never trusting the in-process
    # `learning.trainer._IdAllocator` counter that starts at 1 fresh
    # every invocation). The returned object, not the one passed in, is
    # therefore the only one with the REAL, persisted id -- discarding
    # it (as this script did before this fix) silently let every
    # cross-reference below (evaluation.candidate_id/dataset_id,
    # experiment.dataset_id/candidate_id/evaluation_id) point at a
    # dangling in-process id after the very first run whose dataset
    # differs from an already-recorded one, a real database consistency
    # bug an external review found. `dataset_id`/`dataset_version` never
    # change on record() (only `dataset_id` can be reassigned;
    # `dataset_version` is a content hash, identical before and after),
    # so only those two ever need forwarding into the dependent records.
    dataset = DuckDBTrainingDatasetRepository(engine).record(result.dataset_result.dataset)
    candidate = DuckDBCandidateModelRepository(engine).record(
        dataclasses.replace(result.candidate, dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version)
    )
    evaluation = DuckDBEvaluationRepository(engine).record(dataclasses.replace(
        result.evaluation, candidate_id=candidate.candidate_id,
        dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
    ))
    experiment = DuckDBLearningExperimentRepository(engine).record(dataclasses.replace(
        result.experiment, dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
        candidate_id=candidate.candidate_id, evaluation_id=evaluation.evaluation_id,
    ))

    report = {
        "note": (
            "Real Experience -> Training Dataset -> Candidate -> Evaluation chain "
            "(ADR-0113), read from a real --paper-store scripts/run_paper_trading_cycle.py "
            "already populated. Persisted into the same catalog file's own Learning Engine "
            "tables (storage.learning_repository) -- never mutates the Trade Journal itself."
        ),
        "provenance": provenance.value,
        "trainer_version": trainer.version,
        "experience_record_count": len(records),
        "dataset_id": dataset.dataset_id,
        "dataset_version": dataset.dataset_version,
        "dataset_sample_count": dataset.sample_count,
        "dataset_excluded_count": dataset.excluded_count,
        "dataset_quality_status": dataset.quality_status,
        "candidate_id": candidate.candidate_id,
        "candidate_status": candidate.status.value,
        "candidate_parameters": candidate.parameters,
        "evaluation_id": evaluation.evaluation_id,
        "train_metrics": _metrics_dict(evaluation.train_metrics),
        "validation_metrics": _metrics_dict(evaluation.validation_metrics),
        "test_metrics": _metrics_dict(evaluation.test_metrics),
        "baseline_metrics": _metrics_dict(evaluation.baseline_metrics),
        "experiment_id": experiment.experiment_id,
        "experiment_status": experiment.status,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))

    print(f"Dataset: {dataset.dataset_id} ({dataset.sample_count} samples, quality={dataset.quality_status})")
    print(f"Candidate: {candidate.candidate_id} ({trainer.version}) status={candidate.status.value}")
    print(f"Test metrics: {_metrics_dict(evaluation.test_metrics)}")
    print(f"Report written to: {args.out}")
    engine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
