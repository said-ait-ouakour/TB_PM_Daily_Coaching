"""
Live MongoDB: fetch the first 5 advisor documents from `users` (same query as the app).

Enable with:
  set RUN_MONGO_ADVISORS_TEST=1
  set MONGO_URI (or MONGO_URL)
  set MONGO_DB_NAME (or MONGO_DB)

Optional:
  set INTEGRATION_CONCEPT=people_manager   # or t_and_b — picks mongo_users_collection + advisor_query from concepts

Run:
  pytest tests/test_mongo_real_advisors.py -v -s -m mongo_live

The project `tests/conftest.py` loads `.env` via python-dotenv in `pytest_configure`.
Use MONGO_DB_NAME (or MONGO_DB, TB_MONGO_DB, PM_MONGO_DB). Do not use a single line like
MONGO_URI=MONGO_URL=... (invalid; use MONGO_URI=mongodb+srv://... only).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pymongo import MongoClient

from concepts import get_concept_definition
from workflow_engine import _shared_mongo_uri_and_db


requires_mongo_live = pytest.mark.skipif(
    os.environ.get("RUN_MONGO_ADVISORS_TEST", "").strip().lower() not in ("1", "true", "yes"),
    reason="Set RUN_MONGO_ADVISORS_TEST=1 and MONGO_URI + MONGO_DB_NAME to hit real MongoDB.",
)


_LIVE_FETCH_LIMIT = 5


@pytest.mark.mongo_live
@requires_mongo_live
def test_fetch_first_advisors_from_mongo_users_collection() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    except ImportError:
        pass

    concept_id = (os.environ.get("INTEGRATION_CONCEPT") or "people_manager").strip()
    raw = get_concept_definition(concept_id)
    collection_name = raw["mongo_users_collection"]
    query = dict(raw["advisor_query"])
    uri, db_name = _shared_mongo_uri_and_db()
    print("DB name ", db_name)
    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    try:
        client.admin.command("ping")
        col = client[db_name][collection_name]
        advisors = list(col.find(query).limit(_LIVE_FETCH_LIMIT))
        assert isinstance(advisors, list)
        assert len(advisors) <= _LIVE_FETCH_LIMIT
        for doc in advisors:
            assert "_id" in doc

        # Visible with pytest -s
        print(
            f"\n[Mongo live] concept={concept_id} db={db_name} "
            f"collection={collection_name} query={query} "
            f"documents_fetched={len(advisors)} (limit {_LIVE_FETCH_LIMIT})"
        )
        for i, doc in enumerate(advisors):
            email = (doc.get("email") or "").strip()
            name = (doc.get("name") or "").strip()
            print(f"  [{i + 1}] _id={doc['_id']} email={email!r} name={name!r}")
            # print(doc)
    finally:
        client.close()
