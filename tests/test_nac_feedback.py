"""NAC feedback text extraction from customernacfeedbacks-shaped rows."""

from nac_feedback import NAC_TEXT_FIELD_KEYS, extract_nac_feedback_texts


def test_extract_prefers_first_matching_key_in_order() -> None:
    row = {"other": "x", "feedback": "NAC body", "summary": "ignored second"}
    assert extract_nac_feedback_texts([row]) == ["NAC body"]


def test_extract_skips_empty_strings() -> None:
    row = {"feedback": "   ", "summary": "real"}
    assert extract_nac_feedback_texts([row]) == ["real"]


def test_extract_multiple_calls_one_snippet_each() -> None:
    calls = [
        {"advisor_phone_e164": "+15551234567", "feedback": "call A"},
        {"summary": "call B"},
        {},
    ]
    assert extract_nac_feedback_texts(calls) == ["call A", "call B"]


def test_keys_tuple_is_stable() -> None:
    assert "feedback" in NAC_TEXT_FIELD_KEYS
    assert "summary" in NAC_TEXT_FIELD_KEYS
