"""Unit tests: VAPI outbound call creation for t_and_b (mocked HTTP, no real VAPI)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import mongomock

from workflow_engine import AdvisorRecord, ConceptWorkflow, SharedServiceConfig


@patch("workflow_engine.MongoClient", lambda *_a, **_k: mongomock.MongoClient())
def test_t_and_b_call_vapi_advisor_posts_expected_body_and_returns_call_id(tb_concept) -> None:
    """Single advisor: fake E.164 + fake daily_payload → POST `/call/phone` with T&B assistant id."""
    wf = ConceptWorkflow(tb_concept, SharedServiceConfig())

    advisor = AdvisorRecord(
        mongo_user_id="507f1f77bcf86cd799439011",
        advisor_name="Test TB Advisor",
        email="tb.advisor.test@example.com",
        e164_phone="+15555550100",
        peoplemanager_id="507f1f77bcf86cd799439011",
        supabase_advisor_id="tb-supabase-user-1",
        mongo_document={
            "_id": "507f1f77bcf86cd799439011",
            "email": "tb.advisor.test@example.com",
            "role": "advisor",
        },
    )

    daily_payload = {
        "Advisor Name": "Test TB Advisor",
        "Performance Tier": "INTERMEDIATE",
        "Calls yesterday": 2,
        "Meetings yesterday": 1,
        "Feedback Summary": "Synthetic feedback for test.",
        "Coaching Context": "CRM TB",
        "Memory": "Synthetic coaching memory.",
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"id":"fake-vapi-call-id"}'
    mock_resp.json.return_value = {"id": "fake-vapi-call-id"}

    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    wf._tls.http = mock_session  # type: ignore[attr-defined]

    try:
        status, text, vapi_id = wf.call_vapi_advisor(advisor, daily_payload)
    finally:
        wf.close()

    assert status == 200
    assert vapi_id == "fake-vapi-call-id"
    mock_session.post.assert_called_once()
    call_args = mock_session.post.call_args
    endpoint = call_args[0][0]
    assert endpoint == f"{wf.shared.vapi_base_url}/call/phone"
    body = call_args[1]["json"]
    assert body["assistantId"] == tb_concept.vapi_assistant_id
    assert body["customer"]["number"] == "+15555550100"
    assert body["assistantOverrides"]["variableValues"]["daily_payload"] == daily_payload
    assert call_args[1]["timeout"] == 30
    # Fixture has no VAPI phone id; body still includes key with null (see workflow_engine.call_vapi_advisor)
    assert body.get("phoneNumberId") is None
