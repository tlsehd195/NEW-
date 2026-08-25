"""Category: Reproducibility Test -- identical inputs produce identical
outputs everywhere in `evolution.*`, and no module uses `random` or a
wall-clock call (the same discipline `learning`/`counterfactual` already
established, Phase 9/10)."""

from __future__ import annotations

import ast
from pathlib import Path

import evolution

from evolution_helpers import build_dataset, utc

from evolution.comparison import compare_candidates
from evolution.config import PromotionConfig
from evolution.criteria import evaluate_transition
from evolution.lineage import derive_lineage
from evolution.pipeline import evaluate_candidate_batch, generate_candidate_batch
from evolution.trainer import TrailingWindowMeanTrainer

from learning.enums import CandidateModelStatus
from learning.trainer import MeanRewardBaselineTrainer


class TestNoRandomOrWallClockCalls:
    def test_no_random_import_anywhere_in_evolution(self) -> None:
        package_dir = Path(evolution.__file__).parent
        for py_file in package_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name != "random", f"{py_file.name} imports random"
                if isinstance(node, ast.ImportFrom) and node.module == "random":
                    raise AssertionError(f"{py_file.name} imports from random")

    def test_no_now_or_utcnow_call_anywhere_in_evolution(self) -> None:
        package_dir = Path(evolution.__file__).parent
        for py_file in package_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in ("now", "utcnow"):
                    raise AssertionError(f"{py_file.name} calls datetime.{node.attr}()")


class TestDeterministicEndToEnd:
    def test_full_generate_compare_validate_lineage_chain_is_deterministic(self) -> None:
        def run_once():
            result = build_dataset(20)
            trainers = [MeanRewardBaselineTrainer(), TrailingWindowMeanTrainer(window=3), TrailingWindowMeanTrainer(window=8)]
            candidates = generate_candidate_batch(result.dataset, result.labeled_samples, trainers, trained_at=utc(2024, 3, 1))
            evaluations = evaluate_candidate_batch(candidates, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1))
            comparison = compare_candidates(evaluations, comparison_id="CMP-000001", compared_at=utc(2024, 3, 1))
            transitions = [
                evaluate_transition(
                    c, e, CandidateModelStatus.CANDIDATE, PromotionConfig(),
                    transition_id=f"TRANS-{i:06d}", evaluated_at=utc(2024, 3, 1),
                )
                for i, (c, e) in enumerate(zip(candidates, evaluations), start=1)
            ]
            lineages = [derive_lineage(c) for c in candidates]
            return (
                tuple(c.parameters.get("predicted_value") for c in candidates),
                comparison.ranked_candidate_ids,
                tuple((t.passed, t.reason) for t in transitions),
                tuple((l.generation, l.parent_candidate_id) for l in lineages),
            )

        run1 = run_once()
        run2 = run_once()
        assert run1 == run2
