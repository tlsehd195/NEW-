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


class TestRealProvenancePlausibilityCheck:
    """Phase 28 addition (instruction section 5, items B/C): --data-status
    REAL is the caller's own claim and must be cross-checked against the
    data's own recorded provenance, not simply trusted. Manually
    verified at runtime this phase (not just statically): the same
    synthetic-fixture catalog Phase 25/26/27 used for dry runs (bars
    carrying provenance.source="test_source") is now correctly REFUSED
    (exit code 1) when --data-status REAL is passed, and still runs
    correctly to completion when --data-status SYNTHETIC is passed
    against the identical catalog."""

    def test_known_real_provider_sources_matches_actual_provider_implementations(self) -> None:
        tree = _tree()
        assignments = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_KNOWN_REAL_PROVIDER_SOURCES" for t in node.targets)
        ]
        assert len(assignments) == 1
        value = assignments[0].value
        assert isinstance(value, ast.Set)
        sources = {elt.value for elt in value.elts if isinstance(elt, ast.Constant)}
        # Must match the exact Provenance.source strings the real
        # provider implementations actually stamp -- verified directly
        # against their source rather than assumed.
        tiingo_source = (Path(__file__).resolve().parents[2] / "src" / "data_infra" / "providers" / "tiingo.py").read_text()
        stooq_source = (Path(__file__).resolve().parents[2] / "src" / "data_infra" / "providers" / "stooq.py").read_text()
        assert 'source="tiingo"' in tiingo_source
        assert 'source="stooq"' in stooq_source
        assert sources == {"tiingo", "stooq"}

    def test_unexpected_provenance_source_under_real_status_refuses_not_warns(self) -> None:
        """The check must actually stop execution (return a non-zero
        exit code), not just print a warning and continue -- a warning
        alone would still let a mislabeled report reach `results`."""
        tree = _tree()
        main_func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main")
        # Find the `if unexpected_sources:` block inside main() and
        # confirm its body actually returns non-zero.
        if_blocks = [
            n for n in ast.walk(main_func)
            if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "unexpected_sources"
        ]
        assert len(if_blocks) == 1, "expected exactly one `if unexpected_sources:` guard"
        return_stmts = [n for n in ast.walk(if_blocks[0]) if isinstance(n, ast.Return)]
        assert len(return_stmts) == 1
        assert isinstance(return_stmts[0].value, ast.Constant) and return_stmts[0].value.value != 0

    def test_provenance_check_runs_before_any_strategy_is_evaluated(self) -> None:
        """The refusal must happen before `run_walk_forward_evaluation`
        is ever called -- never let a single strategy's evaluation
        start against data that fails the REAL provenance check."""
        tree = _tree()
        main_func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main")
        if_blocks = [
            n for n in ast.walk(main_func)
            if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "unexpected_sources"
        ]
        wf_calls = _find_calls(main_func, "run_walk_forward_evaluation")
        assert if_blocks[0].lineno < wf_calls[0].lineno


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


class TestPboDsrActuallyAppliedNotJustPrinted:
    """The bug this class regression-tests: `assess_pbo_dsr_applicability`
    was previously computed AFTER the per-strategy loop that calls
    `classify_evidence_level`, so its result was never fed back in --
    every real run's evidence was hardcoded `pbo_dsr_applied=False`
    regardless of what applicability found. Fixed by restructuring into
    two passes: collect all strategies' walk-forward results first,
    THEN check applicability and (if real data + applicable) actually
    compute PBO/DSR, THEN classify evidence using those real numbers."""

    def test_classify_evidence_level_is_never_called_with_a_hardcoded_false(self) -> None:
        tree = _tree()
        calls = _find_calls(tree, "classify_evidence_level")
        assert len(calls) == 1
        call = calls[0]
        kwargs = {kw.arg: kw.value for kw in call.keywords}
        assert "pbo_dsr_applied" in kwargs
        # Must not be the literal constant False -- must be computed
        # (an expression referencing whether pbo_result was actually produced).
        assert not (isinstance(kwargs["pbo_dsr_applied"], ast.Constant) and kwargs["pbo_dsr_applied"].value is False)

    def test_classify_evidence_level_call_passes_pbo_probability_and_dsr(self) -> None:
        tree = _tree()
        [call] = _find_calls(tree, "classify_evidence_level")
        kwargs = {kw.arg: kw.value for kw in call.keywords}
        assert "pbo_probability" in kwargs
        assert "deflated_sharpe_ratio" in kwargs

    def test_applicability_check_happens_before_pbo_computation(self) -> None:
        source = _source()
        applicability_idx = source.index("assess_pbo_dsr_applicability(")
        compute_pbo_idx = source.index("compute_pbo(")
        assert applicability_idx < compute_pbo_idx

    def test_pbo_computation_happens_before_evidence_classification(self) -> None:
        source = _source()
        compute_pbo_idx = source.index("compute_pbo(")
        classify_idx = source.index("classify_evidence_level(")
        assert compute_pbo_idx < classify_idx


class TestConcentrationReportWiring:
    """Per-security P&L contribution/concentration analysis (added
    following the master instruction's "Symbol Contribution" /
    "Leave-One-Out / Concentration Check" requirement,
    `backtest.contribution`), wired into the held-out TEST result --
    the single full-period backtest, the most decision-relevant target
    for "did a handful of symbols drive this whole result." Must be
    computed from `held_out_result.net.fills` (the NET fills, matching
    every other held-out TEST field already being the net-of-costs one)
    and stored inside the `held_out_test` dict, never silently omitted."""

    def test_compute_contribution_report_from_fills_is_imported(self) -> None:
        source = _source()
        assert "compute_contribution_report_from_fills" in source
        assert "from backtest.contribution import compute_contribution_report_from_fills" in source

    def test_concentration_is_computed_from_net_fills_not_gross(self) -> None:
        tree = _tree()
        calls = _find_calls(tree, "compute_contribution_report_from_fills")
        assert len(calls) == 1
        call = calls[0]
        first_arg = call.args[0]
        # held_out_result.net.fills -- an attribute chain ending in "fills"
        # off of something ending in "net", never "gross".
        assert isinstance(first_arg, ast.Attribute) and first_arg.attr == "fills"
        assert isinstance(first_arg.value, ast.Attribute) and first_arg.value.attr == "net"

    def test_concentration_result_is_stored_in_held_out_test_dict(self) -> None:
        source = _source()
        held_out_test_block_start = source.index("held_out_test = {")
        held_out_test_block_end = source.index("}", held_out_test_block_start)
        block = source[held_out_test_block_start:held_out_test_block_end]
        assert '"concentration"' in block

    def test_concentration_computed_before_held_out_test_dict_is_built(self) -> None:
        source = _source()
        concentration_call_idx = source.index("compute_contribution_report_from_fills(")
        held_out_test_dict_idx = source.index("held_out_test = {")
        assert concentration_call_idx < held_out_test_dict_idx

    def test_pbo_dsr_computation_gated_on_is_real_data(self) -> None:
        """PBO/DSR must never be computed against synthetic fixture
        data -- that would answer "is this noise" about a result this
        project already knows is not real evidence (is_real_data=False
        already forces INSUFFICIENT_EVIDENCE regardless)."""
        tree = _tree()
        compute_pbo_calls = _find_calls(tree, "compute_pbo")
        assert len(compute_pbo_calls) == 1
        call_lineno = compute_pbo_calls[0].lineno

        # Find the nearest enclosing `if` whose test references
        # is_real_data, walking up from the call.
        found_gate = False
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                test_names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
                if "is_real_data" in test_names:
                    body_linenos = [n.lineno for n in ast.walk(node) if hasattr(n, "lineno")]
                    if call_lineno in body_linenos:
                        found_gate = True
                        break
        assert found_gate, "compute_pbo call must be inside an `if ... is_real_data ...:` block"

    def test_pbo_dsr_result_written_to_report(self) -> None:
        source = _source()
        assert '"pbo_dsr_result"' in source

    def test_ast_bug_comment_documents_the_fix(self) -> None:
        """Not load-bearing on its own, but a cheap guard that the
        explanatory comment describing the fix (so a future edit does
        not silently reintroduce it) has not been deleted."""
        source = _source()
        assert "was never fed" in source
        assert "back into `classify_evidence_level`" in source
