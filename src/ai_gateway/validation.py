"""Response validation: schema/JSON/missing-field/invalid-value
detection for a provider's raw output, per PROJECT_MASTER_PLAN.md
section 5.3: "schema validation, JSON validation, missing field
detection, invalid value detection ... AI가 잘못된 형식/값의 데이터를
반환해도 주문 시스템으로 직접 전달되지 않는다."

See docs/specifications/PHASE-12-ai-gateway.md section 7.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    parsed: Optional[dict]
    reason: str  # "ok" | "empty_content" | "not_valid_json" | "not_a_json_object" | "missing_field:<name>" | "empty_field:<name>"


def validate_response_content(content: Optional[str], response_schema: Optional[tuple[str, ...]]) -> ValidationResult:
    """When `response_schema` is `None`, only checks the content is a
    non-empty string -- the caller did not ask for structured output, so
    the Gateway does not invent a schema requirement. When
    `response_schema` is set, the content must parse as a JSON object
    containing every named key with a non-empty (non-null, non-empty-string)
    value -- an empty string or `null` for a required field is treated
    the same as a missing field (a provider that returns `{"action":
    ""}` has not actually answered)."""
    if content is None or content == "":
        return ValidationResult(valid=False, parsed=None, reason="empty_content")

    if response_schema is None:
        return ValidationResult(valid=True, parsed=None, reason="ok")

    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return ValidationResult(valid=False, parsed=None, reason="not_valid_json")

    if not isinstance(parsed, dict):
        return ValidationResult(valid=False, parsed=None, reason="not_a_json_object")

    for field_name in response_schema:
        if field_name not in parsed:
            return ValidationResult(valid=False, parsed=None, reason=f"missing_field:{field_name}")
        value = parsed[field_name]
        if value is None or value == "":
            return ValidationResult(valid=False, parsed=None, reason=f"empty_field:{field_name}")

    return ValidationResult(valid=True, parsed=parsed, reason="ok")
