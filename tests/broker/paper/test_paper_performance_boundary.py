"""Category: Boundary Test (Phase 18, instruction section 15: "Paper
Trading는 학습 시스템이 아니다"). `broker.paper.performance` computes a
report about Paper Trading's own execution/accounting quality -- it
must never import `learning.*`/`evolution.*`, never reference
`CandidateModelStatus`, and never itself decide anything about model
approval or training-dataset eligibility. A good (or bad) Paper
Performance Report is never sufficient, by construction, to move a
Candidate anywhere."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import broker.paper.performance as perf_module


class TestPerformanceModuleNeverTouchesLearningOrEvolution:
    def test_no_import_of_learning_or_evolution_packages(self) -> None:
        tree = ast.parse(Path(perf_module.__file__).read_text())
        forbidden_prefixes = ("learning", "evolution")
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.split(".")[0] in forbidden_prefixes, f"imports {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.split(".")[0] in forbidden_prefixes, f"imports {alias.name}"

    def test_no_attribute_reference_to_candidate_model_status(self) -> None:
        tree = ast.parse(Path(perf_module.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("APPROVED", "DEPLOYED", "CandidateModelStatus"):
                raise AssertionError(f"performance module references {node.attr}")

    def test_no_function_named_approve_or_deploy_or_promote(self) -> None:
        forbidden_names = {"approve", "deploy", "promote", "approved", "deployed", "promoted"}
        for name, obj in vars(perf_module).items():
            if inspect.isfunction(obj):
                assert name.lower() not in forbidden_names

    def test_compute_paper_performance_report_signature_has_no_candidate_or_model_approval_parameter(self) -> None:
        params = set(inspect.signature(perf_module.compute_paper_performance_report).parameters)
        assert params.isdisjoint({"candidate", "candidate_id", "approve", "approval", "deploy"})
