"""
Live VAPI (opt-in): one real HTTP POST to `{VAPI_BASE_URL}/call` via `ConceptWorkflow.call_vapi_advisor`.

**This test places a real outbound phone call** to `VAPI_TEST_CUSTOMER_E164` when enabled.

Enable:
  set RUN_VAPI_LIVE_CALL_TEST=1
  set VAPI_TEST_CUSTOMER_E164=+1xxxxxxxxxx    # E.164 you control (or VAPI-approved test destination)

Requires the same env as resolving `t_and_b` + VAPI:
  MONGO_URI, MONGO_DB_NAME
  TB_SUPABASE_URL, TB_SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_* fallback)
  OPENAI_API_KEY, VAPI_API_KEY
  VAPI_TB_ASSISTANT_ID
  VAPI_TB_PHONE_NUMBER_ID and/or VAPI_PHONE_NUMBER_ID if your assistant requires a caller ID

`.env` is loaded from the project root via `tests/conftest.py`.

Run:
  RUN_VAPI_LIVE_CALL_TEST=1 pytest tests/test_vapi_call_live.py -v -s -m vapi_live
"""

from __future__ import annotations

import os
from unittest.mock import patch

import mongomock
import pytest

from workflow_engine import AdvisorRecord, ConceptWorkflow, SharedServiceConfig, resolve_concept_from_env


requires_vapi_live = pytest.mark.skipif(
    os.environ.get("RUN_VAPI_LIVE_CALL_TEST", "").strip().lower() not in ("1", "true", "yes"),
    reason="Set RUN_VAPI_LIVE_CALL_TEST=1 and VAPI_TEST_CUSTOMER_E164 to place a real VAPI call.",
)


# def _tb_test_customer_e164() -> str:
#     return (os.environ.get("VAPI_TEST_CUSTOMER_E164") or "").strip()


@requires_vapi_live
@pytest.mark.vapi_live
@patch("workflow_engine.MongoClient", lambda *_a, **_k: mongomock.MongoClient())
def test_live_tb_vapi_call_create_returns_success() -> None:
    """Resolve t_and_b from env; POST real create-call; assert 2xx and an id when present."""
    # customer = _tb_test_customer_e164()
    # if not customer:
    #     pytest.skip("Set VAPI_TEST_CUSTOMER_E164 (E.164) for live VAPI call test.")

    concept = resolve_concept_from_env("t_and_b")
    wf = ConceptWorkflow(concept, SharedServiceConfig())

    advisor = AdvisorRecord(
        mongo_user_id="507f191e810c19729de860ea",
        advisor_name="Live VAPI Test Advisor",
        email="vapi-live-test@example.invalid",
        e164_phone="+212609889372",
        peoplemanager_id="507f191e810c19729de860ea",
        supabase_advisor_id="live-test-supabase-id",
        mongo_document={"_id": "507f191e810c19729de860ea", "email": "vapi-live-test@example.invalid"},
    )

    daily_payload = {
        "Advisor Name": "Live VAPI Test Advisor",
        "Performance Tier": "LOW",
        "Calls yesterday": 0,
        "Meetings yesterday": 0,
        "Feedback Summary": "Ayoub was not able to answer the questions as expected, needs skills on rejection handling and lead qualification",
        "Coaching Context": "CRM TB",
        "Memory": "the assistant asked Ayoub to take a breath before answering the questions",
    }

    try:
        status, text, vapi_id = wf.call_vapi_advisor(advisor, daily_payload)
    finally:
        wf.close()

    assert status in (200, 201), f"Unexpected status={status} body={text[:2000]}"
    # Successful create responses usually include an id (shape varies by API version).
    if vapi_id is not None:
        assert str(vapi_id).strip() != ""
