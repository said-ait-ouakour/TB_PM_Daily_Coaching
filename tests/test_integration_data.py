"""
Integration: first 5 Mongo `users` advisors merged against **both** Supabase projects.

- **people_manager** → PM Supabase (`PM_SUPABASE_*`): lookup by **`peoplemanager_id`** = `str(Mongo users._id)`.
- **t_and_b** → TB Supabase (`TB_SUPABASE_*`): lookup by **`email`**.

Requires:
  RUN_DATA_INTEGRATION_TESTS=1
  MONGO_URI, MONGO_DB_NAME
  PM_SUPABASE_URL, PM_SUPABASE_SERVICE_ROLE_KEY
  TB_SUPABASE_URL, TB_SUPABASE_SERVICE_ROLE_KEY
  OPENAI_API_KEY, VAPI_API_KEY, VAPI_PM_ASSISTANT_ID, VAPI_TB_ASSISTANT_ID

Run: pytest tests/test_integration_data.py -v -s -m integration
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

import pytest

from workflow_engine import AdvisorRecord, ConceptWorkflow, SharedServiceConfig, resolve_concept_from_env


requires_integration = pytest.mark.skipif(
    os.environ.get("RUN_DATA_INTEGRATION_TESTS", "").strip().lower() not in ("1", "true", "yes"),
    reason="Set RUN_DATA_INTEGRATION_TESTS=1 and real env vars to run integration tests.",
)

_MERGE_BATCH = 40

_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def _merged_printable(adv: AdvisorRecord) -> Dict[str, Any]:
    """Mongo advisor document + Supabase linkage after map_advisors_to_supabase_phone."""
    return {
        "mongo_users": adv.mongo_document,
        "supabase_users_id": adv.supabase_advisor_id,
        "phone_number_e164": adv.e164_phone,
        "email": adv.email,
        "name": adv.advisor_name,
        "mongo_users_id_str": adv.mongo_user_id,
    }


@requires_integration
@pytest.mark.integration
def test_first_five_advisors_merge_pm_and_tb_supabase() -> None:
    """Same 5 Mongo advisors: merge via PM (peoplemanager_id) and T&B (email); print combined JSON output."""
    shared = SharedServiceConfig()
    wf_pm: ConceptWorkflow | None = None
    wf_tb: ConceptWorkflow | None = None
    try:
        wf_pm = ConceptWorkflow(resolve_concept_from_env("people_manager"), shared)
        advisors = wf_pm.get_advisors_from_mongo()
        # print("advisors", advisors)
        assert isinstance(advisors, list)
        if not advisors:
            pytest.skip("No Mongo advisors for configured advisor_query (empty collection or query).")

        mongo_batch = advisors[:_MERGE_BATCH]
        merged_pm: List[AdvisorRecord] = wf_pm.map_advisors_to_supabase_phone(mongo_batch)

        wf_tb = ConceptWorkflow(resolve_concept_from_env("t_and_b"), shared)
        merged_tb: List[AdvisorRecord] = wf_tb.map_advisors_to_supabase_phone(mongo_batch)

        result: Dict[str, Any] = {
            "mongo_batch_count": len(mongo_batch),
            "people_manager": {
                "lookup_mode": "peoplemanager_id",
                "supabase_env": "PM_SUPABASE_URL",
                "merged_count": len(merged_pm),
                "merged_advisors": [_merged_printable(a) for a in merged_pm],
            }
            ,
            "t_and_b": {
                "lookup_mode": "email",
                "supabase_env": "TB_SUPABASE_URL",
                "merged_count": len(merged_tb),
                "merged_advisors": [_merged_printable(a) for a in merged_tb],
            },
        }

        print("\n=== Integration merge: first Mongo batch → PM Supabase + TB Supabase ===\n")
        print(json.dumps(result, indent=2, default=str))

        for label, merged in (("people_manager (PM)", merged_pm), ("t_and_b (TB)", merged_tb)):
            for adv in merged:
                assert adv.mongo_document and isinstance(adv.mongo_document, dict)
                assert adv.supabase_advisor_id and str(adv.supabase_advisor_id).strip()
                assert adv.e164_phone and _E164_RE.match(adv.e164_phone), (
                    f"{label}: phone must be E.164 after formatting; got {adv.e164_phone!r}"
                )
    finally:
        if wf_pm is not None:
            wf_pm.close()
        if wf_tb is not None:
            wf_tb.close()
