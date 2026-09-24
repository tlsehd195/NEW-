"""Category: ai_gateway.grounding correctness (Batch N). Pure functions,
no fixtures needed."""

from __future__ import annotations

import pytest

from ai_gateway.grounding import (
    evaluate_formula,
    matches_evidence,
    validate_derived_value,
)


class TestEvaluateFormula:
    def test_a_simple_sum_evaluates_correctly(self) -> None:
        result = evaluate_formula("100 + 5.5")
        assert result is not None
        assert result.result == pytest.approx(105.5)
        assert result.operands == (100.0, 5.5)

    def test_operator_precedence_is_respected(self) -> None:
        result = evaluate_formula("100 + 2 * 3")
        assert result is not None
        assert result.result == pytest.approx(106.0)

    def test_unary_minus_is_supported(self) -> None:
        result = evaluate_formula("-5 + 10")
        assert result is not None
        assert result.result == pytest.approx(5.0)

    def test_a_bare_constant_is_not_a_formula(self) -> None:
        # Only one operand -- nothing to "derive."
        assert evaluate_formula("42") is None

    def test_division_by_zero_returns_none_not_an_exception(self) -> None:
        assert evaluate_formula("1 / 0") is None

    def test_malformed_syntax_returns_none(self) -> None:
        assert evaluate_formula("1 + ") is None

    def test_a_power_operator_is_rejected_not_evaluated(self) -> None:
        # ast.Pow is not in the allowed binop set -- must not silently
        # compute 2**1000000 (or anything else) for an unsupported node.
        assert evaluate_formula("2 ** 1000000") is None

    def test_function_calls_are_rejected(self) -> None:
        # No eval() of arbitrary code -- a Call node must never execute.
        assert evaluate_formula("__import__('os').system('echo pwned') + 1") is None

    def test_a_deeply_nested_expression_does_not_crash(self) -> None:
        deeply_nested = "(" * 2000 + "1 + 1" + ")" * 2000
        # Either a clean rejection (RecursionError caught) or a real
        # result -- never an unhandled exception escaping this call.
        evaluate_formula(deeply_nested)


class TestMatchesEvidence:
    def test_an_exact_match_is_within_tolerance(self) -> None:
        assert matches_evidence(100.0, [100.0])

    def test_a_value_within_half_a_percent_matches(self) -> None:
        assert matches_evidence(100.4, [100.0])

    def test_a_value_beyond_the_tolerance_band_does_not_match(self) -> None:
        assert not matches_evidence(110.0, [100.0])

    def test_matches_against_any_one_of_several_evidence_values(self) -> None:
        assert matches_evidence(50.0, [10.0, 20.0, 50.1])

    def test_empty_evidence_never_matches(self) -> None:
        assert not matches_evidence(100.0, [])


class TestValidateDerivedValue:
    def test_a_correct_formula_anchored_to_real_evidence_is_valid(self) -> None:
        # 100 is a real observed close price; 1.05 is a free multiplier.
        result = validate_derived_value(105.0, "100 * 1.05", evidence=[100.0])
        assert result.valid
        assert result.reason == "ok"

    def test_an_unparseable_formula_is_rejected(self) -> None:
        result = validate_derived_value(105.0, "not a formula", evidence=[100.0])
        assert not result.valid
        assert result.reason == "not_a_formula"

    def test_a_formula_whose_result_does_not_match_the_claim_is_rejected(self) -> None:
        result = validate_derived_value(999.0, "100 * 1.05", evidence=[100.0])
        assert not result.valid
        assert result.reason == "result_mismatch"

    def test_an_added_term_with_no_anchor_at_all_is_rejected(self) -> None:
        # 2.5 is real evidence, but 9999 is fabricated and additively
        # combined -- the whole formula must be rejected, not accepted
        # because SOME part of it happens to be real.
        result = validate_derived_value(10001.5, "2.5 + 9999", evidence=[2.5])
        assert not result.valid
        assert result.reason == "unanchored_term"

    def test_a_free_multiplier_beside_one_anchored_operand_is_accepted(self) -> None:
        # No top-level +/- at all -- purely multiplicative, so the
        # unanchored 1.1 multiplier does not trigger unanchored_term.
        result = validate_derived_value(110.0, "100 * 1.1", evidence=[100.0])
        assert result.valid

    def test_a_subtracted_term_with_no_anchor_is_rejected(self) -> None:
        result = validate_derived_value(-9897.5, "2.5 - 9900", evidence=[2.5])
        assert not result.valid
        assert result.reason == "unanchored_term"

    def test_every_additive_term_anchored_separately_is_accepted(self) -> None:
        # 100 and 5 are both real observed values, added together.
        result = validate_derived_value(105.0, "100 + 5", evidence=[100.0, 5.0])
        assert result.valid
