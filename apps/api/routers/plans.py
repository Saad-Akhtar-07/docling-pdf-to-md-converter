"""POST /documents/{id}/plans, GET /plans/{id}.

Single-user MVP: no authentication, matching apps/api/routers/documents.py.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.deps import get_db
from apps.api.jobs.plan_build import is_incomplete, run_plan_build_job
from apps.api.schemas import ObjectiveOut, PlanBuildResponse, PlanOut, UnitOut
from slidevision.persistence.enums import DocumentStatus
from slidevision.persistence.repositories import DocumentRepository, PlanRepository

router = APIRouter(tags=["plans"])


@router.post("/documents/{document_id}/plans", response_model=PlanBuildResponse, status_code=status.HTTP_202_ACCEPTED)
def build_plan(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> PlanBuildResponse:
    document = DocumentRepository(db).get(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    if document.status != DocumentStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document is not ready for plan building (status={document.status.value}).",
        )

    plan_repo = PlanRepository(db)
    latest = plan_repo.latest_version(document_id)

    # A latest plan that's still mid-build (no units yet, or a unit with no
    # objectives yet) is resumed in place rather than starting a new
    # version -- see apps/api/jobs/plan_build.py's module docstring.
    if latest is not None and is_incomplete(latest):
        plan = latest
    else:
        next_version = (latest.version + 1) if latest is not None else 1
        plan = plan_repo.create_plan(document_id=document_id, version=next_version)
        db.commit()

    background_tasks.add_task(run_plan_build_job, plan.id)

    return PlanBuildResponse(job_id=plan.id, plan_id=plan.id, status=plan.status)


@router.get("/plans/{plan_id}", response_model=PlanOut)
def get_plan(plan_id: uuid.UUID, db: Session = Depends(get_db)) -> PlanOut:
    plan = PlanRepository(db).get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found.")

    units = sorted(plan.units, key=lambda unit: unit.order_index)
    return PlanOut(
        id=plan.id,
        document_id=plan.document_id,
        version=plan.version,
        status=plan.status,
        builder_prompt_version=plan.builder_prompt_version,
        model=plan.model,
        created_at=plan.created_at,
        units=[
            UnitOut(
                id=unit.id,
                title=unit.title,
                order_index=unit.order_index,
                summary=unit.summary,
                slide_ids=unit.slide_ids,
                objectives=[
                    ObjectiveOut.model_validate(objective)
                    for objective in sorted(unit.objectives, key=lambda o: o.order_index)
                ],
            )
            for unit in units
        ],
    )
