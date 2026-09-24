"""Numeric grounding for a "derived" field in a structured AI response.

Batch N (`EXTERNAL_REPO_APPLICABILITY_REPORT.md` priority 4, strongly
recommended): Vibe-Trading's own grounding gate
(`agent/src/agent/grounding/`, ~5,800 lines across 6 files) validates
free-form PROSE numbers a chat model writes inline in a natural-language
answer -- it has to find measurement-shaped numbers among CJK/English
text, classify each by role (observed/derived/proposed/cited/count),
and check each against an evidence pool, because nothing in that
system's response shape tells it which numbers mean what.

**That whole prose-parsing problem does not exist here.** This
project's `AIGateway.generate()` only ever accepts a response when
`response_schema` is set and the content parses as a JSON object with
exactly those named fields (`ai_gateway.validation.
validate_response_content`) -- every numeric value already arrives
labeled by its field name, not embedded in prose. Vibe-Trading's
`figures.py` (1,080 lines: Unicode number-shape detection, CJK date/
currency/magnitude parsing, look-alike-character normalization) and
`identity.py`/`evidence.py`'s Chinese-market source/currency alias
tables solve a problem this project's structured-JSON design already
sidesteps -- porting them would add real complexity to solve nothing.

**What IS genuinely portable, and what this module ports**: the
"derived" role's actual validation logic -- a claimed numeric value is
trustworthy only if (1) it equals the result of a plain arithmetic
formula (no `eval()` of arbitrary code) and (2) every additive/
subtractive term in that formula traces back to at least one value this
session actually observed, not a number the model invented and then
did real arithmetic on to launder it as "derived." This is
Vibe-Trading's own `policies._evaluate_formula`/`policies.
_unanchored_term`, reimplemented independently against this project's
own evidence-pool shape (a plain sequence of observed floats -- e.g.
from `AsOfDataView`/`PredictionOutput` -- rather than Vibe-Trading's
CSV/JSON-quote ingestion pipeline). Simplified from the original in one
disclosed way: the "1 +/- c used as a multiplicative discount factor"
special case (an idiom from Chinese financial prose, e.g. "0.666 x
(1 - 0.03)") is dropped -- there is no prose here for that idiom to
appear in; a derived field's formula is a plain expression string a
schema asks the model for directly.

**Not wired into `AIGateway`/`decision.agent` in this batch.** Using
this for real requires a prompt/schema design decision this session
should not make unilaterally: which decision-agent fields count as
"derived," and requiring the model's response schema to carry an
accompanying formula string for each one (e.g. `expected_return_
formula: "past_close * (1 + momentum_pct)"` alongside `expected_
return`). That is real, separate design work -- adding the validation
engine itself, independently tested against this project's own evidence
shape, is what this batch does; wiring it into a live prompt template is
follow-up work, per this project's own ADR-0151 "adopt now, wire in
later" precedent."""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

#: Relative band a value must fall in to count as matching evidence --
#: same tolerance Vibe-Trading's own `policies._TOLERANCE` uses.
EVIDENCE_TOLERANCE = 0.005

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)


@dataclass(frozen=True)
class FormulaEvaluation:
    result: float
    operands: tuple[float, ...]


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def evaluate_formula(expression: str) -> Optional[FormulaEvaluation]:
    """Evaluate a `+ - * /` arithmetic expression over numeric constants
    without ever calling `eval()` -- the AST is parsed and walked node
    by node, and any node that is not a numeric constant, a unary +/-,
    or one of the four arithmetic binary operators makes the whole
    expression invalid (`None`), not partially evaluated. Requires at
    least two numeric operands (a bare constant is not a "formula").
    Never raises -- a malformed expression, a division by zero, or a
    non-finite result all return `None`."""
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None

    operands: list[float] = []

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and _is_finite_number(node.value):
            value = float(node.value)
            operands.append(value)
            return value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if right == 0:
                raise ValueError("division by zero")
            return left / right
        raise ValueError("unsupported expression node")

    try:
        result = visit(tree)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError, RecursionError):
        return None
    if len(operands) < 2 or not math.isfinite(result):
        return None
    return FormulaEvaluation(result=result, operands=tuple(operands))


def matches_evidence(value: float, evidence: Sequence[float], *, tolerance: float = EVIDENCE_TOLERANCE) -> bool:
    """Whether `value` agrees with at least one real observed value in
    `evidence`, inside a relative tolerance band (the "observed" role's
    own check: a value the model claims to have read off real data must
    actually be close to something real)."""
    return any(abs(value - target) <= max(abs(target) * tolerance, 1e-9) for target in evidence)


def _split_additive_terms(node: ast.AST) -> list[ast.AST]:
    """Flatten a chain of top-level `+`/`-` into its terms (e.g.
    `a - b + c` -> `[a, b, c]`, sign discarded -- only term identity
    matters for anchoring, not which side of a `-` it sits on)."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        return _split_additive_terms(node.left) + _split_additive_terms(node.right)
    return [node]


def _term_is_anchored(node: ast.AST, is_observed: Callable[[float], bool]) -> bool:
    return any(
        isinstance(item, ast.Constant) and _is_finite_number(item.value) and is_observed(float(item.value))
        for item in ast.walk(node)
    )


@dataclass(frozen=True)
class DerivedValidation:
    valid: bool
    reason: str  # "ok" | "not_a_formula" | "result_mismatch" | "unanchored_term"
    evaluation: Optional[FormulaEvaluation]


def validate_derived_value(
    claimed_value: float, formula: str, evidence: Sequence[float], *, tolerance: float = EVIDENCE_TOLERANCE,
) -> DerivedValidation:
    """The full "derived" role check (Vibe-Trading's own `policies.
    _check_derived`, reimplemented against this project's own plain
    evidence-pool shape): `formula` must evaluate cleanly via
    `evaluate_formula`, its result must match `claimed_value` within
    `tolerance`, and every additive/subtractive term in it must be
    anchored to a real observed value in `evidence` -- a formula like
    `2.5 + 9999` is NOT trustworthy just because `2.5` is real, if
    `9999` was invented and the model did real arithmetic on it to make
    the result look derived. A purely multiplicative/divisive
    expression with no top-level `+`/`-` is treated as one term, so a
    free multiplier (e.g. a percentage rate) beside one real anchored
    operand is fine -- only an ADDED or SUBTRACTED term with no anchor
    at all fails this check, matching the original's own scope."""
    evaluation = evaluate_formula(formula)
    if evaluation is None:
        return DerivedValidation(valid=False, reason="not_a_formula", evaluation=None)

    if not matches_evidence(claimed_value, [evaluation.result], tolerance=tolerance):
        return DerivedValidation(valid=False, reason="result_mismatch", evaluation=evaluation)

    def is_observed(value: float) -> bool:
        return matches_evidence(value, evidence, tolerance=tolerance)

    # evaluate_formula's own success above guarantees this re-parse
    # succeeds too -- its operands list is flat and loses the tree
    # shape _split_additive_terms needs, so the tree is rebuilt here
    # rather than threaded through FormulaEvaluation.
    try:
        tree = ast.parse(formula.strip(), mode="eval")
        terms = _split_additive_terms(tree.body)
        fully_anchored = all(_term_is_anchored(term, is_observed) for term in terms)
    except RecursionError:
        return DerivedValidation(valid=False, reason="not_a_formula", evaluation=evaluation)
    if not fully_anchored:
        return DerivedValidation(valid=False, reason="unanchored_term", evaluation=evaluation)

    return DerivedValidation(valid=True, reason="ok", evaluation=evaluation)
