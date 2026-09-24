"""Category: normalized_entropy correctness (Batch L, decision.entropy).
Pure function, no fixtures needed."""

from __future__ import annotations

import math

import pytest

from decision.entropy import normalized_entropy


class TestBoundaryValues:
    def test_a_fully_certain_two_outcome_distribution_is_zero(self) -> None:
        assert normalized_entropy([1.0, 0.0]) == pytest.approx(0.0, abs=1e-9)

    def test_a_uniform_two_outcome_distribution_is_one(self) -> None:
        assert normalized_entropy([0.5, 0.5]) == pytest.approx(1.0)

    def test_a_uniform_four_outcome_distribution_is_also_one(self) -> None:
        assert normalized_entropy([0.25, 0.25, 0.25, 0.25]) == pytest.approx(1.0)

    def test_a_single_outcome_is_zero_without_dividing_by_zero(self) -> None:
        # ln(1) == 0 would make an unguarded max_entropy divide by zero;
        # the ln(max(n, 2)) guard must prevent that.
        assert normalized_entropy([1.0]) == pytest.approx(0.0)


class TestKnownValue:
    def test_matches_the_formula_computed_by_hand(self) -> None:
        probs = [0.7, 0.2, 0.1]
        expected_entropy = -sum(p * math.log(p) for p in probs)
        expected = expected_entropy / math.log(3)
        assert normalized_entropy(probs) == pytest.approx(expected)


class TestUnnormalizedInput:
    def test_raw_unnormalized_weights_give_the_same_result_as_normalized(self) -> None:
        normalized = normalized_entropy([0.7, 0.2, 0.1])
        unnormalized = normalized_entropy([7.0, 2.0, 1.0])
        assert unnormalized == pytest.approx(normalized)


class TestValidation:
    def test_empty_sequence_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            normalized_entropy([])

    def test_a_negative_probability_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            normalized_entropy([0.5, -0.5, 1.0])

    def test_all_zero_probabilities_raises(self) -> None:
        with pytest.raises(ValueError, match="positive value"):
            normalized_entropy([0.0, 0.0, 0.0])
