from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app import etl
from app.ai import features as ai_features
from app.dependencies import require_etl, require_etl_write

router = APIRouter(prefix="/etl", tags=["etl"])

RUN_STATUSES = {"running", "succeeded", "failed"}


class RunIn(BaseModel):
    table: Optional[str] = None


class ExplainIn(BaseModel):
    allow_cloud_once: bool = False


def _visible(user) -> list[str]:
    return [p.key for p in etl.pipelines().values() if p.can_view(user)]


@router.get("/pipelines")
def pipelines(user=Depends(require_etl)):
    return {"pipelines": etl.pipeline_overview(user)}


@router.get("/runs")
def runs(
    pipeline: Optional[str] = None,
    run_status: Optional[str] = Query(default=None, alias="status"),
    trigger: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
    user=Depends(require_etl),
):
    if run_status and run_status not in RUN_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown status.")
    if trigger and trigger not in etl.TRIGGERS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown trigger.")
    return etl.list_runs(_visible(user), pipeline, run_status, trigger, limit, offset)


@router.get("/runs/{run_id}")
def run(run_id: int, user=Depends(require_etl)):
    found = etl.get_run(run_id)
    if not found or found["pipeline"] not in _visible(user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That run does not exist.")
    return found


@router.post("/runs/{run_id}/explain")
def explain(run_id: int, body: ExplainIn, user=Depends(require_etl)):
    """A failed run's error messages in plain words: what happened, the likely cause, what to try."""
    found = etl.get_run(run_id)
    if not found or found["pipeline"] not in _visible(user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That run does not exist.")
    errors = [found.get("error") or ""]
    for step in found.get("steps") or []:
        if isinstance(step, dict) and step.get("error"):
            errors.append(f"{step.get('name') or step.get('target_table') or 'a step'}: {step['error']}")
    label = next((p.label for p in etl.pipelines().values() if p.key == found["pipeline"]), found["pipeline"])
    result = ai_features.explain_failed_load(user, label=label, errors=errors, allow_cloud_once=body.allow_cloud_once)
    if result.get("status") == "invalid":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["message"])
    return result


@router.post("/pipelines/{key}/run", status_code=status.HTTP_202_ACCEPTED)
def start(key: str, body: RunIn, user=Depends(require_etl_write)):
    """Start a pipeline, or one table of it. It runs in the background: follow it with GET /runs/{id}."""
    try:
        pipeline = etl.get_pipeline(key)
    except etl.EtlError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not pipeline.can_view(user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That pipeline does not exist.")
    if not pipeline.can_run(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You can see {pipeline.label}, but you do not have permission to run it.",
        )
    try:
        run_id = etl.start_run(key, body.table or etl.FULL, "manual", user["id"])
    except etl.EtlBusy as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except etl.EtlError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"run_id": run_id}
