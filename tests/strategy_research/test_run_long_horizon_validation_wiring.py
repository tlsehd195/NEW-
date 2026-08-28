"""Phase 27 structural regression tests for
`scripts/run_long_horizon_validation.py` (instruction section 28,
categories B/C/D/F/I/J).

This script is deliberately never imported or executed by the
automated test suite (it reads a real, already-ingested DuckDB catalog
the suite never has, per its own module docstring). These tests
therefore work entirely on its SOURCE TEXT/AST -- never `import` it,
never call `main()` -- the same discipline
`tests/strategy_research/test_security_boundary.py` already uses for
`src/strategy_research/`.

Category I is the concrete bug this file exists to regression-test:
`classify_evidence_level(..., is_real_data=True, ...)` was hardcoded
regardless of what `--db-path` actually held -- a synthetic dry run
would have produced an `EvidenceAssessment` structurally
indistinguishable from a real one. Fixed by a required `--data-status
{REAL,SYNTHETIC}` argument gating `is_real_data` directly.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_long_horizon_validation.py"


def _source() -> str:
    return _SCRIPT_PATH.read_text()


def _tree() -> ast.Module:
    return ast.parse(_source(), filename=str(_SCRIPT_PATH))


def _find_calls(tree: ast.Module, func_name: str) -> list[ast.Call]:
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == func_name
    ]


class TestDataStatusWiring:
    """Category I: real/synthetic status must never be confused in the
    report -- and, more fundamentally, `is_real_data` must never be a
    hardcoded literal (the actual bug this phase found and fixed)."""

    def test_data_status_argument_is_required_with_real_and_synthetic_choices(self) -> None:
        tree = _tree()
        add_argument_calls = _find_calls(tree, "add_argument")
        data_status_calls = [
            c for c in add_argument_calls
            if c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value == "--data-status"
        ]
        assert len(data_status_calls) == 1, "expected exactly one --data-status argparse argument"
        call = data_status_calls[0]
        kwargs = {kw.arg: kw.value for kw in call.keywords}
        assert "required" in kwargs and getattr(kwargs["required"], "value", None) is True
        assert "choices" in kwargs
        choices_value = kwargs["choices"]
        assert isinstance(choices_value, ast.Tuple)
        choice_values = {elt.value for elt in choices_value.elts if isinstance(elt, ast.Constant)}
        assert choice_values == {"REAL", "SYNTHETIC"}

    def test_is_real_data_is_never_a_hardcoded_boolean_literal(self) -> None:
        """The actual bug: `is_real_data=True`/`is_real_data=False`
        anywhere in the script would mean the evidence classification
        no longer reflects what --data-status the caller actually
        passed."""
        tree = _tree()
        classify_calls = _find_calls(tree, "classify_evidence_level")
        assert len(classify_calls) == 1, "expected exactly one classify_evidence_level call"
        call = classify_calls[0]
        kwargs = {kw.arg: kw.value for kw in call.keywords}
        assert "is_real_data" in kwargs
        assert not isinstance(kwargs["is_real_data"], ast.Constant), (
            "is_real_data must be derived from args.data_status, never a hardcoded literal"
        )

    def test_report_dict_carries_data_status_experiment_id_and_data_version(self) -> None:
        """Category J: experiment_id/data_version must survive into the
        actual report, not just be computed and discarded."""
        source = _source()
        # The report dict is built as a literal with these exact keys --
        # a plain substring check is sufficient and avoids over-fitting
        # to the dict's exact AST shape.
        assert '"data_status": args.data_status,' in source
        assert '"experiment_id": experiment_id,' in source
        assert '"data_version": data_version,' in source

    def test_experiment_id_hash_input_includes_data_status(self) -> None:
        """A REAL and a SYNTHETIC run of an otherwise-identical
        configuration must never collide into the same experiment_id
        (section 27's explicit namespace-separation requirement)."""
        tree = _tree()
        compute_calls = _find_calls(tree, "compute_data_version")
        assert len(compute_calls) == 2, "expected exactly two compute_data_version calls (experiment_id, data_version)"
        # The first positional dict argument to at least one call must
        # reference args.data_status as one of its values.
        found = False
        for call in compute_calls:
            if not call.args or not isinstance(call.args[0], ast.Dict):
                continue
            for value in call.args[0].values:
                if isinstance(value, ast.Attribute) and value.attr == "data_status":
                    found = True
        assert found, "compute_data_version's payload for experiment_id must include args.data_status"


class TestChronologicalBoundaryWiring:
    """Category B: the walk-forward region and the held-out TEST region
    must never overlap at the CLI's own call-site level (not just at
    the underlying split-construction level, already covered by
    tests/strategy_research/test_evidence.py)."""

    def test_walk_forward_uses_train_start_to_validation_end_only(self) -> None:
        tree = _tree()
        calls = _find_calls(tree, "run_walk_forward_evaluation")
        assert len(calls) == 1
        kwargs = {kw.arg: kw.value for kw in calls[0].keywords}
        assert isinstance(kwargs["overall_start"], ast.Attribute) and kwargs["overall_start"].attr == "train_start"
        assert isinstance(kwargs["overall_end"], ast.Attribute) and kwargs["overall_end"].attr == "validation_end"

    def test_held_out_test_uses_test_start_to_test_end_only(self) -> None:
        tree = _tree()
        calls = _find_calls(tree, "run_gross_and_net")
        assert len(calls) == 1
        kwargs = {kw.arg: kw.value for kw in calls[0].keywords}
        start_call = kwargs["start_date"]
        end_call = kwargs["end_date"]
        assert isinstance(start_call, ast.Call) and start_call.func.value.attr == "test_start"
        assert isinstance(end_call, ast.Call) and end_call.func.value.attr == "test_end"


class TestEqualBenchmarkConditions:
    """Category D: every strategy must be evaluated against the same
    benchmark_id -- both calls inside the per-strategy loop reference
    the single, shared `benchmark_id` variable, never a per-strategy
    literal or a second, differently-computed value."""

    def test_both_evaluation_calls_reference_the_same_benchmark_id_variable(self) -> None:
        tree = _tree()
        wf_calls = _find_calls(tree, "run_walk_forward_evaluation")
        gn_calls = _find_calls(tree, "run_gross_and_net")
        wf_kwargs = {kw.arg: kw.value for kw in wf_calls[0].keywords}
        gn_kwargs = {kw.arg: kw.value for kw in gn_calls[0].keywords}
        assert isinstance(wf_kwargs["benchmark_id"], ast.Name) and wf_kwargs["benchmark_id"].id == "benchmark_id"
        assert isinstance(gn_kwargs["benchmark_id"], ast.Name) and gn_kwargs["benchmark_id"].id == "benchmark_id"


class TestNoFabricatedBenchmarkFallback:
    """Category F: benchmark_id must stay None (BENCHMARK_UNAVAILABLE)
    whenever no real SPY bars are present -- no fallback literal value
    is ever assigned to it."""

    def test_benchmark_id_only_ever_assigned_none_or_from_the_spy_bars_branch(self) -> None:
        tree = _tree()
        assignments = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "benchmark_id" for t in node.targets)
        ]
        assert len(assignments) == 2, "expected exactly two assignments to benchmark_id"
        # One is the initial `benchmark_id = None`.
        none_assignments = [a for a in assignments if isinstance(a.value, ast.Constant) and a.value.value is None]
        assert len(none_assignments) == 1
        # The other is the conditional expression gated on benchmark_points,
        # never a bare string literal fallback.
        other = [a for a in assignments if a not in none_assignments][0]
        assert isinstance(other.value, ast.IfExp), "the second benchmark_id assignment must be a conditional, not an unconditional literal"


class TestNoWallClockOrRandomInStrategyDeterminism:
    """Category C (partial): the reproducibility fields themselves must
    not depend on wall-clock time or randomness -- the full determinism
    property of the underlying walk-forward computation is already
    covered by tests/strategy_research/test_walk_forward_evaluation.py::TestDeterministicReplay."""

    def test_script_never_calls_datetime_now_or_random(self) -> None:
        """AST-based, not a raw substring search -- the module's own
        docstrings and comments legitimately mention these forbidden
        names when explaining why they are avoided, which a naive text
        search would misfire on."""
        tree = _tree()
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("now", "utcnow") and isinstance(node.func.value, ast.Name) and node.func.value.id == "datetime":
                    violations.append("datetime.now()/utcnow() call")
            if isinstance(node, ast.Import):
                if any(alias.name == "random" for alias in node.names):
                    violations.append("import random")
            if isinstance(node, ast.ImportFrom) and node.module == "random":
                violations.append("from random import ...")
        assert violations == [], violations
