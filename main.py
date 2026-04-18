"""FastAPI orchestration service: multi-tenant concepts.

Execution modes:
- **Scheduler** (optional): `ENABLE_SCHEDULER=1` — daily job at `DAILY_CRON` in `SCHEDULER_TZ` (default 09:30 Europe/London)
  runs **all concepts** for London yesterday.
- **POST /run-all**: same as scheduler batch — all concepts, all Mongo advisors matching each concept.
- **POST /run/{concept}**: one concept, all matching Mongo advisors.
- **POST /run/{concept}/advisors**: one concept, only Mongo `users._id` values listed in the JSON body.

"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from concepts import list_concept_ids
from workflow_engine import default_run_date, process_concept

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("advisor-api")

app = FastAPI(title="Advisor outreach orchestration", version="1.0.0")

_runs_lock = threading.Lock()
# In-memory run registry (per task). With multiple ECS tasks, prefer ADVISOR_OUTREACH_AUDIT_TABLE + batch_run_id.
_RUNS: Dict[str, Dict[str, Any]] = {}


class RunAdvisorsSubsetBody(BaseModel):
    """Mongo `users` document `_id` values (24-char hex ObjectId strings)."""

    mongo_user_ids: List[str] = Field(..., min_length=1)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_run_record(concept_ids: List[str], run_date: str) -> str:
    run_id = str(uuid.uuid4())
    with _runs_lock:
        _RUNS[run_id] = {
            "run_id": run_id,
            "status": "running",
            "concepts": concept_ids,
            "run_date": run_date,
            "started_at": _utc_now_iso(),
            "finished_at": None,
            "results": {},
            "error": None,
        }
    return run_id


def _finish_run(run_id: str, results: Dict[str, Any], error: Optional[str] = None) -> None:
    with _runs_lock:
        if run_id not in _RUNS:
            return
        _RUNS[run_id]["status"] = "failed" if error else "completed"
        _RUNS[run_id]["finished_at"] = _utc_now_iso()
        _RUNS[run_id]["results"] = results
        _RUNS[run_id]["error"] = error


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> Dict[str, Any]:
    with _runs_lock:
        if run_id not in _RUNS:
            raise HTTPException(status_code=404, detail="Unknown run_id (in-memory registry is per task).")
        return dict(_RUNS[run_id])


@app.post("/run/{concept}")
def run_concept(concept: str) -> Dict[str, Any]:
    if concept not in list_concept_ids():
        raise HTTPException(status_code=404, detail=f"Unknown concept. Valid: {list_concept_ids()}")

    run_date = default_run_date()
    run_id = _new_run_record([concept], run_date)
    try:
        _batch_id, metrics = process_concept(concept, run_date=run_date, batch_run_id=run_id)
        _finish_run(run_id, {concept: {"batch_run_id": _batch_id, "metrics": metrics}})
    except Exception as exc:  # noqa: BLE001
        logger.exception("Run failed for %s", concept)
        _finish_run(run_id, {}, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    with _runs_lock:
        return dict(_RUNS[run_id])


@app.post("/run/{concept}/advisors")
def run_concept_advisors(concept: str, body: RunAdvisorsSubsetBody) -> Dict[str, Any]:
    """Run a single concept for only the given Mongo advisor ids (`userId` = `users._id`)."""
    if concept not in list_concept_ids():
        raise HTTPException(status_code=404, detail=f"Unknown concept. Valid: {list_concept_ids()}")

    run_date = default_run_date()
    run_id = _new_run_record([concept], run_date)
    try:
        _batch_id, metrics = process_concept(
            concept,
            run_date=run_date,
            batch_run_id=run_id,
            mongo_user_ids=body.mongo_user_ids,
        )
        _finish_run(run_id, {concept: {"batch_run_id": _batch_id, "metrics": metrics}})
    except Exception as exc:  # noqa: BLE001
        logger.exception("Run failed for %s (subset)", concept)
        _finish_run(run_id, {}, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    with _runs_lock:
        return dict(_RUNS[run_id])


@app.post("/run-all")
def run_all() -> Dict[str, Any]:
    concepts = list_concept_ids()
    run_date = default_run_date()
    run_id = _new_run_record(concepts, run_date)
    results: Dict[str, Any] = {}
    try:
        for cid in concepts:
            batch_id, metrics = process_concept(cid, run_date=run_date, batch_run_id=f"{run_id}:{cid}")
            results[cid] = {"batch_run_id": batch_id, "metrics": metrics}
        _finish_run(run_id, results)
    except Exception as exc:  # noqa: BLE001
        logger.exception("run-all failed")
        _finish_run(run_id, results, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    with _runs_lock:
        return dict(_RUNS[run_id])


def _scheduled_daily() -> None:
    run_date = default_run_date()
    for cid in list_concept_ids():
        try:
            _, metrics = process_concept(cid, run_date=run_date)
            logger.info("Scheduled run complete %s: %s", cid, metrics)
        except Exception:  # noqa: BLE001
            logger.exception("Scheduled run failed for %s", cid)


_scheduler: Optional[BackgroundScheduler] = None


@app.on_event("startup")
def _startup() -> None:
    global _scheduler
    if os.environ.get("ENABLE_SCHEDULER", "").strip().lower() in ("1", "true", "yes"):
        cron = os.environ.get("DAILY_CRON", "30 9 * * *")
        parts = cron.split()
        if len(parts) != 5:
            logger.warning("Invalid DAILY_CRON %r; expected 5 fields", cron)
            return
        minute, hour, day, month, dow = parts
        _scheduler = BackgroundScheduler(timezone=os.environ.get("SCHEDULER_TZ", "Europe/London"))
        _scheduler.add_job(
            _scheduled_daily,
            CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=dow),
            id="daily_all_concepts",
            replace_existing=True,
        )
        _scheduler.start()
        logger.info("APScheduler started: %s (%s)", cron, os.environ.get("SCHEDULER_TZ", "Europe/London"))


@app.on_event("shutdown")
def _shutdown() -> None:
    if _scheduler:
        _scheduler.shutdown(wait=False)
