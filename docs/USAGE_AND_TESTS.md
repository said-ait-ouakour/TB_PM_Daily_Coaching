# Advisor outreach automation — usage, execution, and tests

This document explains **how to run** the automation (HTTP API, CLI, scheduler), **what happens** during a run (data flow and decisions), and **which tests** exist and how to run them.

For a lower-level call graph, see [`EXECUTION_FLOW.md`](EXECUTION_FLOW.md) (note: this file is kept more current for API routes and subset runs).

---

## 1. What this project does

The pipeline connects:

- **MongoDB** — shared database; `users` (and related collections) hold advisors and call/NAC/coaching data.
- **Supabase** — **two** projects: **People Manager (PM)** and **T&B**; each concept uses one project for phone lookup and meetings counts.
- **VAPI** — outbound phone calls with a structured **`daily_payload`** passed into the assistant.

**Concepts** (`concepts.py`): `people_manager` and `t_and_b`. Each has its own Supabase credentials and VAPI assistant IDs, but shares the same Mongo URI/DB.

---

## 2. Configuration

1. Copy `.env.example` to `.env` and fill in real values.
2. **Required for a full run:** `MONGO_URI`, `MONGO_DB_NAME`, per-concept Supabase URL + service role key, `OPENAI_API_KEY`, `VAPI_API_KEY`, `VAPI_PM_ASSISTANT_ID`, `VAPI_TB_ASSISTANT_ID` (and optional per-concept `VAPI_*_PHONE_NUMBER_ID` or shared `VAPI_PHONE_NUMBER_ID`).
3. **`pytest`** loads `.env` automatically via `tests/conftest.py` (when `python-dotenv` is installed).

**Run date:** Business “yesterday” is **yesterday in `Europe/London`**, as `YYYY-MM-DD`, unless you set `OVERRIDE_RUN_DATE=YYYY-MM-DD` for debugging.

---

## 3. How to run the script

### 3.1 FastAPI server (recommended for production)

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Liveness check. |
| `POST /run/{concept}` | Run **one** concept (`people_manager` or `t_and_b`) for **all** Mongo advisors matching that concept’s `advisor_query`. |
| `POST /run-all` | Run **every** concept in sequence (same as looping `list_concept_ids()`). |
| `POST /run/{concept}/advisors` | Run **one** concept for **only** the listed Mongo `users._id` values. **Body:** `{"mongo_user_ids": ["<24-char hex>", ...]}`. |
| `GET /runs/{run_id}` | Status of a run started via POST (in-memory registry; **per process**). |

**Scheduler (optional):** Set `ENABLE_SCHEDULER=1` (or `true`/`yes`). On startup, APScheduler runs `_scheduled_daily()` at `DAILY_CRON` (default `30 9 * * *` → 09:30) in `SCHEDULER_TZ` (default `Europe/London`). That job runs **all concepts** with `process_concept` (no HTTP `run_id`; logs only).

### 3.2 Command line (`advisor_daily_workflow.py`)

Same pipeline as the API, without HTTP:

```bash
# Default: one concept (people_manager), all matching advisors
python -m advisor_daily_workflow

python -m advisor_daily_workflow --concept t_and_b

# All concepts, full advisor lists
python -m advisor_daily_workflow --all-concepts

# One concept, subset of Mongo user ids (comma-separated ObjectId hex strings)
python -m advisor_daily_workflow --concept people_manager --mongo-user-ids 507f1f77bcf86cd799439011,507f191e810c19729de860ea
```

Legacy: if only `VAPI_ASSISTANT_ID` is set, the CLI maps it to `VAPI_PM_ASSISTANT_ID` for PM runs.

### 3.3 Programmatic

```python
from workflow_engine import process_concept, default_run_date

batch_id, metrics = process_concept("people_manager", run_date=default_run_date())
batch_id, metrics = process_concept(
    "people_manager",
    mongo_user_ids=["507f1f77bcf86cd799439011"],
)
```

`metrics` is a count dict: `processed`, `success`, `skipped`, `failed`.

---

## 4. Execution process (step by step)

### 4.1 Entry

`process_concept(concept_id, …)` → loads env → `resolve_concept_from_env` → `ConceptWorkflow.run(run_date, batch_run_id, mongo_user_ids=…)`.

### 4.2 Load advisors from Mongo

- **`get_advisors_from_mongo(mongo_user_ids)`** — `find` on `mongo_users_collection` with `advisor_query` (e.g. `role: advisor`). If `mongo_user_ids` is set, adds `_id: { $in: [...] }` (ObjectId for 24-char hex strings).

### 4.3 Merge with Supabase (phone + Supabase user id)

**`map_advisors_to_supabase_phone`** — For each Mongo advisor:

- **`people_manager`:** Supabase `users` row where `peoplemanager_id` = `str(Mongo users._id)`.
- **`t_and_b`:** Supabase `users` row matched by **email**.

Requires valid **phone** and Supabase **`id`** (used as `supabase_advisor_id`). Advisors without a match or valid E.164 phone are skipped (not counted as VAPI failures).

### 4.4 Per advisor (`process_single_advisor`)

Runs in parallel up to `VAPI_MAX_CONCURRENT_PER_CONCEPT` (default 3).

1. **Optional audit** — If `ADVISOR_OUTREACH_AUDIT_TABLE` is set, inserts/updates rows; idempotent skip if prior **success** for same `run_date` + email.

2. **Mongo “calls yesterday”** — `customernacfeedbacks` (name from `mongo_calls_collection`): `userId` = advisor’s Mongo id, and **`date` field** in the **London-yesterday UTC half-open interval** `[start, end)` (`yesterday_london_utc_bounds()`). Count = **calls yesterday**.

3. **Supabase meetings yesterday** — `meetings` table in **that concept’s** Supabase: filter by `advisor_id` (or configured FK column) = Supabase user `id`, and **`meeting_date`** in the same yesterday window (see `meetings_date_match_mode` in `concepts.py`; default is range, not plain calendar string equality).

4. **Gate** — If **both** calls count and meetings count are **zero**, the advisor is **skipped** (no VAPI call).

5. **NAC + coaching** — Latest NAC row (`mongo_nac_collection`) and latest coaching row (`mongo_coaching_collection`) by `userId`, for payload text (e.g. nested `areasForImprovement.reportText`, `previous_call_summary`).

6. **`daily_payload`** — Built with display keys, including **Performance Tier** (LOW / INTERMEDIATE / HIGH from calls + meetings), **Coaching Context** (`CRM PM` or `CRM TB`), etc.

7. **VAPI** — `POST {VAPI_BASE_URL}/call/phone` with `assistantId`, optional `phoneNumberId`, `customer.number` = E.164, and `assistantOverrides.variableValues.daily_payload` = the payload object.

**Note on Mongo call dates:** The query expects the **`date`** field to participate in a **datetime range** comparison. If your data stores only a **string** `YYYY-MM-DD` without matching that range semantics, you may get zero calls until the data model or query is aligned (see team notes / migration).

---

## 5. Tests

Tests live under `tests/`. Run everything:

```bash
python -m pytest tests/ -v
```

### 5.1 Markers (`pytest.ini`)

| Marker | Meaning |
|--------|---------|
| `integration` | Can hit **real** Mongo + Supabase; gated by env (see below). |
| `mongo_live` | Can hit **real** Mongo only; gated by env. |

### 5.2 Default (offline / mocked)

These run in CI without real databases:

| File | What it covers |
|------|----------------|
| `test_data_fetches.py` | Mongo advisor query + Supabase phone mapping (mongomock); **calls yesterday** (datetime range); NAC/coaching reads; **`build_daily_payload`** shape; **meetings count** (fake Supabase); performance tier rules. |
| `test_nac_feedback.py` | Extracting text snippets from call-shaped rows (`nac_feedback.py`). |
| `test_tb_phone_mapping.py` | TB vs PM Supabase env resolution and TB email → phone mapping. |

### 5.3 Integration tests (real services)

Enable with:

```bash
set RUN_DATA_INTEGRATION_TESTS=1
```

| File | What it does |
|------|----------------|
| `test_integration_data.py` | Loads real Mongo advisors and merges against PM and/or TB Supabase (phone + id). |
| `test_supabase_fetch.py` | Live read of `users` in PM and TB; optional **meetings** rows where FK = Supabase user `id` (`SUPABASE_MEETINGS_USER_FK_COL` overrides column name if needed). |

Requires valid `.env` with PM/TB Supabase, Mongo, VAPI/OpenAI keys as documented in each file’s docstring.

### 5.4 Mongo-only live tests

**Advisors list:**

```bash
set RUN_MONGO_ADVISORS_TEST=1
pytest tests/test_mongo_real_advisors.py -v -s -m mongo_live
```

**Calls / NAC / coaching smoke (workflow methods):**

```bash
set RUN_MONGO_OTHER_COLLECTIONS_TEST=1
pytest tests/test_mongo_real_other_collections.py -v -s -m mongo_live
```

Optional: `INTEGRATION_CONCEPT=people_manager` or `t_and_b`.

---

## 6. Quick troubleshooting

| Symptom | Things to check |
|--------|-------------------|
| No advisors processed | `advisor_query` in `concepts.py`, Mongo URI/DB, subset ids valid. |
| All skipped after mapping | Supabase keys, lookup mode (PM vs TB), phone + `id` on `users`. |
| Skipped “no calls or meetings yesterday” | Data for **London yesterday**; Mongo `date` type vs range query; Supabase `meeting_date` + `meetings_date_match_mode`. |
| VAPI errors | `VAPI_API_KEY`, `VAPI_*_ASSISTANT_ID`, `phoneNumberId` if required. |
| `run_id` not found | `GET /runs/...` is **in-memory** for that server process only. |

---

## 7. File map

| File | Role |
|------|------|
| `main.py` | FastAPI app, routes, optional scheduler. |
| `advisor_daily_workflow.py` | CLI entrypoint. |
| `workflow_engine.py` | `process_concept`, `ConceptWorkflow`, Mongo/Supabase/VAPI. |
| `concepts.py` | Concept definitions and `ResolvedConcept` fields. |
| `dates_london.py` | London yesterday date and UTC bounds. |
| `.env.example` | Environment variable template. |
