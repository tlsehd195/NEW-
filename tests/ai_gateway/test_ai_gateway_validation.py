"""Category: Response Validation Test -- schema/JSON/missing-field/
invalid-value detection (PROJECT_MASTER_PLAN.md section 5.3)."""

from __future__ import annotations

from ai_gateway.validation import validate_response_content


class TestNoSchemaRequired:
    def test_non_empty_content_is_valid(self) -> None:
        result = validate_response_content("plain text response", None)
        assert result.valid is True
        assert result.parsed is None
        assert result.reason == "ok"

    def test_empty_content_is_invalid(self) -> None:
        assert validate_response_content("", None).valid is False
        assert validate_response_content(None, None).valid is False


class TestWithSchema:
    def test_valid_json_with_all_fields_passes(self) -> None:
        result = validate_response_content('{"action": "BUY", "confidence": "0.8"}', ("action", "confidence"))
        assert result.valid is True
        assert result.parsed == {"action": "BUY", "confidence": "0.8"}

    def test_not_valid_json_fails(self) -> None:
        result = validate_response_content("{not json", ("action",))
        assert result.valid is False
        assert result.reason == "not_valid_json"

    def test_json_array_is_not_a_json_object(self) -> None:
        result = validate_response_content("[1, 2, 3]", ("action",))
        assert result.valid is False
        assert result.reason == "not_a_json_object"

    def test_missing_field_fails(self) -> None:
        result = validate_response_content('{"action": "BUY"}', ("action", "confidence"))
        assert result.valid is False
        assert result.reason == "missing_field:confidence"

    def test_null_field_value_treated_as_missing(self) -> None:
        result = validate_response_content('{"action": null}', ("action",))
        assert result.valid is False
        assert result.reason == "empty_field:action"

    def test_empty_string_field_value_treated_as_missing(self) -> None:
        result = validate_response_content('{"action": ""}', ("action",))
        assert result.valid is False
        assert result.reason == "empty_field:action"

    def test_empty_content_fails_before_json_parsing(self) -> None:
        result = validate_response_content("", ("action",))
        assert result.valid is False
        assert result.reason == "empty_content"
