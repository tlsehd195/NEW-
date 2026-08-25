"""Category: Integration Test -- Model Evolution's full chain
(TrainingDataset -> multiple CandidateModelArtifacts -> EvaluationResults
-> ModelStatusTransitions -> ModelLineageRecords), persisted through the
same DuckDB catalog Phase 4-10 already use, SQL-joinable end to end
(docs/specifications/PHASE-11-model-evolution.md section 9, 11). Also
proves the candidate-alternative counterfactual (section 8) composes
with Phase 10's (HOLD, CASH) record without modifying it, and that the
result still flows into the Learning Engine's Experience Dataset with
zero code changes to `trade_journal`/`learning` (the same "no code
change needed" property Phase 10's own integration test established for
its own additions).
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta

from counterfactual_helpers import make_bars_repo, utc as cf_utc
from evolution_helpers import build_dataset, utc
from storage_helpers import new_engine

from backtest.portfolio import PortfolioView

from decision.agent import BaselineRuleDecisionAgent
from decision.config import DecisionConfig

from evolution.comparison import compare_candidates
from evolution.config import PromotionConfig
from evolution.counterfactual import append_candidate_alternatives, compute_candidate_decision_alternative
from evolution.criteria import evaluate_transition
from evolution.lineage import derive_lineage
from evolution.pipeline import evaluate_candidate_batch, generate_candidate_batch
from evolution.trainer import TrailingWindowMeanTrainer

from learning.enums import CandidateModelStatus
from learning.trainer import MeanRewardBaselineTrainer

from predict.predictor import DriftPredictor

from storage.evolution_repository import DuckDBModelLineageRepository, DuckDBModelStatusTransitionRepository
from storage.learning_repository import DuckDBCandidateModelRepository, DuckDBEvaluationRepository, DuckDBTrainingDatasetRepository

from trade_journal.enums import DecisionAction
from trade_journal.experience import build_experience_records
from trade_journal.models import CounterfactualRecord
from trade_journal.repository import InMemoryTradeJournalRepository


class TestModelEvolutionLineageEndToEnd:
    def test_dataset_candidates_evaluations_transitions_lineage_are_all_joinable_and_survive_restart(
        self, tmp_path
    ) -> None:
        result = build_dataset(30)
        trainers = [MeanRewardBaselineTrainer(), TrailingWindowMeanTrainer(window=4), TrailingWindowMeanTrainer(window=10)]
        candidates = generate_candidate_batch(result.dataset, result.labeled_samples, trainers, trained_at=utc(2024, 3, 1))
        evaluations = evaluate_candidate_batch(candidates, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1))
        comparison = compare_candidates(evaluations, comparison_id="CMP-000001", compared_at=utc(2024, 3, 1))
        assert set(comparison.candidate_ids) == {c.candidate_id for c in candidates}

        engine = new_engine(tmp_path)
        dataset_repo = DuckDBTrainingDatasetRepository(engine)
        candidate_repo = DuckDBCandidateModelRepository(engine)
        eval_repo = DuckDBEvaluationRepository(engine)
        transition_repo = DuckDBModelStatusTransitionRepository(engine)
        lineage_repo = DuckDBModelLineageRepository(engine)

        stored_dataset = dataset_repo.record(result.dataset)
        stored_candidates = []
        stored_evaluations = []
        stored_lineages = []
        stored_transitions = []
        parent_lineage = None
        config = PromotionConfig(min_validation_sample_count=1, min_test_sample_count=1)

        for i, (candidate, evaluation) in enumerate(zip(candidates, evaluations)):
            stored_candidate = candidate_repo.record(candidate)
            stored_evaluation = eval_repo.record(dataclasses.replace(evaluation, candidate_id=stored_candidate.candidate_id))
            stored_candidates.append(stored_candidate)
            stored_evaluations.append(stored_evaluation)

            lineage = derive_lineage(
                stored_candidate, parent=parent_lineage,
                lineage_basis="initial" if parent_lineage is None else "hyperparameter_variation",
            )
            stored_lineages.append(lineage_repo.record(lineage))
            parent_lineage = lineage  # a synthetic chain -- not claiming a real evolutionary relationship, just exercising depth > 0

            t1 = evaluate_transition(
                stored_candidate, stored_evaluation, CandidateModelStatus.CANDIDATE, config,
                transition_id=f"TRANS-{i * 3 + 1:06d}", evaluated_at=utc(2024, 3, 1),
            )
            transition_repo.record(t1)
            t2 = evaluate_transition(
                stored_candidate, stored_evaluation, t1.to_status, config,
                transition_id=f"TRANS-{i * 3 + 2:06d}", evaluated_at=utc(2024, 3, 1),
            )
            transition_repo.record(t2)
            stored_transitions.extend([t1, t2])

        assert all(t.passed for t in stored_transitions)
        assert stored_lineages[1].generation == 1
        assert stored_lineages[2].generation == 2

        # -- SQL joinability: dataset <-> candidate <-> evaluation <-> lineage <-> transition --
        rows = engine.connection.execute(
            "SELECT cm.candidate_id, cm.dataset_id, er.evaluation_id, ml.generation, "
            "COUNT(mst.transition_id) as transition_count "
            "FROM candidate_models cm "
            "JOIN training_datasets td ON cm.dataset_id = td.dataset_id "
            "JOIN evaluation_results er ON er.candidate_id = cm.candidate_id "
            "JOIN model_lineage ml ON ml.candidate_id = cm.candidate_id "
            "JOIN model_status_transitions mst ON mst.candidate_id = cm.candidate_id "
            "GROUP BY cm.candidate_id, cm.dataset_id, er.evaluation_id, ml.generation "
            "ORDER BY ml.generation"
        ).fetchall()
        assert len(rows) == 3
        assert [r[3] for r in rows] == [0, 1, 2]
        assert all(r[4] == 2 for r in rows)  # two transitions recorded per candidate
        assert all(r[1] == stored_dataset.dataset_id for r in rows)

        engine.close()

        # -- restart: reopen the same catalog file, everything is still there --
        engine2 = new_engine(tmp_path)
        reloaded_current_status = DuckDBModelStatusTransitionRepository(engine2).get_current_status(
            stored_candidates[0].candidate_id
        )
        assert reloaded_current_status == CandidateModelStatus.VALIDATED
        reloaded_lineage = DuckDBModelLineageRepository(engine2).get(stored_candidates[2].candidate_id)
        assert reloaded_lineage.generation == 2
        engine2.close()


class TestCandidateAlternativeComposesWithPhase10Counterfactual:
    def test_candidate_alternative_appends_onto_hold_cash_without_modifying_them(self) -> None:
        from counterfactual.counterfactual import build_counterfactual_record

        closes = {}
        d = date(2024, 1, 2)
        price = 100.0
        for i in range(120):
            closes[d + timedelta(days=i)] = price
            price *= 1.005
        repo = make_bars_repo(closes)

        decision_time = cf_utc(2024, 3, 20)
        evaluation_time = cf_utc(2024, 4, 1)

        journal = InMemoryTradeJournalRepository()
        from backtest.enums import OrderSide
        from journal_helpers import make_fill, make_order

        decision = journal.record_decision(
            decision_time=decision_time, security_id="AAA", decision=DecisionAction.BUY,
            order=make_order("ORD-0001", side=OrderSide.BUY, decision_time=decision_time),
        )
        trade = journal.record_trade(
            decision_id=decision.snapshot_id,
            fill=make_fill("ORD-0001", side=OrderSide.BUY, decision_time=decision_time, execution_time=decision_time),
            position_after=10.0, realized_pnl=50.0, realized_return=0.02,
        )

        base_record = build_counterfactual_record(repo, trade, DecisionAction.BUY, decision_time, evaluation_time)
        assert [a.action for a in base_record.alternatives] == ["HOLD", "CASH"]

        portfolio = PortfolioView(as_of_time=decision_time, cash=100_000.0, positions={}, portfolio_value=100_000.0)
        candidate_alt = compute_candidate_decision_alternative(
            repo, "AAA", decision_time, evaluation_time, portfolio,
            DriftPredictor(), BaselineRuleDecisionAgent(DecisionConfig(min_confidence=0.0, min_expected_return=-1.0)),
            candidate_id="CAND-000001",
        )
        extended_record = append_candidate_alternatives(base_record, [candidate_alt])

        assert isinstance(extended_record, CounterfactualRecord)
        assert extended_record.alternatives[:2] == base_record.alternatives  # HOLD/CASH untouched
        assert extended_record.alternatives[2].action == candidate_alt.action
        assert len(extended_record.alternatives) == 3

        journal.record_counterfactual(
            extended_record.trade_id, extended_record.selected_action, extended_record.alternatives,
        )
        assert journal.get_counterfactual(trade.trade_id).alternatives == extended_record.alternatives

        # flows into the Learning Engine's Experience Dataset with zero
        # code changes to trade_journal/learning (same property Phase 10
        # already established for its own additions).
        records = build_experience_records(journal, created_at=evaluation_time + timedelta(days=1))
        assert len(records[0].counterfactual_results) == 3
