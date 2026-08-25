"""Category: Boundary Test -- the Learning Engine never creates an
order, calls a broker, mutates a risk/position limit, or auto-approves/
deploys a candidate (instruction section 19, 23).
"""

from __future__ import annotations

import dataclasses
import inspect

from learning_helpers import build_journal_with_closed_trades, utc

from learning.dataset import build_training_dataset
from learning.enums import CandidateModelStatus
from learning.evaluation import Evaluator
from learning.models import CandidateModelArtifact, EvaluationResult, LearningExperimentRecord, TrainingDataset
from learning.trainer import MeanRewardBaselineTrainer

from trade_journal.enums import TradeProvenance

_FORBIDDEN_FIELDS = {
    "order_id", "broker_order", "execution_price", "risk_limit", "position_limit",
    "kill_switch", "broker", "side", "quantity",
}
_FORBIDDEN_METHOD_NAMES = {
    "submit_order", "place_order", "execute", "send_order", "cancel_order", "create_order",
    "call_broker", "call_toss_api", "set_risk_limit", "set_position_limit", "release_kill_switch",
    "activate_live_trading", "approve", "deploy",
}


class TestNoOrderOrBrokerShapedFields:
    def test_no_forbidden_field_on_any_learning_model(self) -> None:
        for cls in (TrainingDataset, CandidateModelArtifact, EvaluationResult, LearningExperimentRecord):
            field_names = {f.name for f in dataclasses.fields(cls)}
            assert field_names.isdisjoint(_FORBIDDEN_FIELDS), f"{cls.__name__} has a forbidden field"


class TestNoOrderOrBrokerOrRiskMutationMethod:
    def test_trainer_has_no_forbidden_method(self) -> None:
        public_attrs = {name for name in dir(MeanRewardBaselineTrainer) if not name.startswith("_")}
        assert public_attrs.isdisjoint(_FORBIDDEN_METHOD_NAMES)

    def test_evaluator_has_no_forbidden_method(self) -> None:
        public_attrs = {name for name in dir(Evaluator) if not name.startswith("_")}
        assert public_attrs.isdisjoint(_FORBIDDEN_METHOD_NAMES)


class TestPipelineSignaturesTakeNoBrokerOrRiskInput:
    def test_build_training_dataset_signature_has_no_broker_or_risk_parameter(self) -> None:
        params = set(inspect.signature(build_training_dataset).parameters)
        assert params.isdisjoint({"broker", "risk_limit", "position_limit", "kill_switch"})

    def test_train_signature_has_no_broker_or_risk_parameter(self) -> None:
        params = set(inspect.signature(MeanRewardBaselineTrainer.train).parameters)
        assert params.isdisjoint({"broker", "risk_limit", "position_limit", "kill_switch"})


class TestCandidateNeverAutoApprovedOrDeployed:
    def test_trainer_only_ever_produces_candidate_status(self) -> None:
        journal, records = build_journal_with_closed_trades(10)
        result = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        assert candidate.status == CandidateModelStatus.CANDIDATE
        assert candidate.status != CandidateModelStatus.APPROVED
        assert candidate.status != CandidateModelStatus.DEPLOYED

    def test_no_code_path_in_learning_module_constructs_an_approved_or_deployed_candidate(self) -> None:
        import ast
        from pathlib import Path

        import learning

        package_dir = Path(learning.__file__).parent
        forbidden = {"APPROVED", "DEPLOYED"}
        for py_file in package_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in forbidden:
                    raise AssertionError(f"{py_file.name} references CandidateModelStatus.{node.attr}")
