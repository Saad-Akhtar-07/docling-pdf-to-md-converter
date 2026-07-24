"""POST /documents/{id}/plans, GET /plans/{id} (Module 2), plus Module 3's
review/approval surface: PATCH/DELETE /objectives/{id}, POST
/plans/{id}/approve, GET /plans/{id}/edits.

Single-user MVP: no authentication, matching apps/api/routers/documents.py.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.deps import get_db
from apps.api.jobs.plan_build import is_incomplete, run_plan_build_job
from apps.api.schemas import (
    ObjectiveOut,
    ObjectivePatch,
    PlanBuildResponse,
    PlanEditOut,
    PlanOut,
    UnitOut,
)
from slidevision.persistence.enums import DocumentStatus, PlanEditAction
from slidevision.persistence.errors import PlanNotEditableError
from slidevision.persistence.models import LearningObjective, LearningPlan
from slidevision.persistence.repositories import DocumentRepository, PlanRepository

router = APIRouter(tags=["plans"])


def _objective_snapshot(objective: LearningObjective) -> dict:
    """Full recoverable state for one objective, used as plan_edits'
    before/after payload -- includes expected_ideas and misconceptions so a
    DELETE's audit row alone is enough to reconstruct what was removed."""
    return {
        "statement": objective.statement,
        "order_index": objective.order_index,
        "low_confidence": objective.low_confidence,
        "reviewed": objective.reviewed,
        "prerequisite_objective_ids": [str(pid) for pid in objective.prerequisite_objective_ids],
        "expected_ideas": [
            {
                "id": str(idea.id),
                "idea": idea.idea,
                "block_id": idea.block_id,
                "char_start": idea.char_start,
                "char_end": idea.char_end,
            }
            for idea in objective.expected_ideas
        ],
        "misconceptions": [
            {"id": str(m.id), "code": m.code, "text": m.text} for m in objective.misconceptions
        ],
    }


def _serialize_plan(plan: LearningPlan) -> PlanOut:
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
    return _serialize_plan(plan)


@router.patch("/objectives/{objective_id}", response_model=ObjectiveOut)
def update_objective(
    objective_id: uuid.UUID, body: ObjectivePatch, db: Session = Depends(get_db)
) -> ObjectiveOut:
    repo = PlanRepository(db)
    objective = repo.get_objective(objective_id)
    if objective is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objective not found.")

    plan_id = objective.unit.plan_id
    before = _objective_snapshot(objective)

    try:
        if body.statement is not None or body.reviewed is not None:
            repo.edit_objective(objective_id, statement=body.statement, reviewed=body.reviewed)
        if body.expected_ideas is not None:
            repo.replace_expected_ideas(
                objective_id,
                [idea.model_dump() for idea in body.expected_ideas],
            )
    except PlanNotEditableError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.flush()
    after = _objective_snapshot(objective)
    repo.record_edit(plan_id=plan_id, objective_id=objective_id, action=PlanEditAction.UPDATE, before=before, after=after)
    db.commit()

    return ObjectiveOut.model_validate(objective)


@router.delete("/objectives/{objective_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_objective(objective_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    repo = PlanRepository(db)
    objective = repo.get_objective(objective_id)
    if objective is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objective not found.")

    plan_id = objective.unit.plan_id
    before = _objective_snapshot(objective)

    try:
        repo.delete_objective(objective_id)
    except PlanNotEditableError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    repo.record_edit(plan_id=plan_id, objective_id=objective_id, action=PlanEditAction.DELETE, before=before, after=None)
    db.commit()


@router.post("/plans/{plan_id}/approve", response_model=PlanOut)
def approve_plan(plan_id: uuid.UUID, db: Session = Depends(get_db)) -> PlanOut:
    repo = PlanRepository(db)
    plan = repo.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found.")

    before = {"status": plan.status.value}
    try:
        repo.approve_plan(plan_id)
    except PlanNotEditableError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    repo.record_edit(plan_id=plan_id, objective_id=None, action=PlanEditAction.APPROVE, before=before, after={"status": "approved"})
    db.commit()

    return _serialize_plan(plan)


@router.get("/plans/{plan_id}/edits", response_model=list[PlanEditOut])
def get_plan_edits(plan_id: uuid.UUID, db: Session = Depends(get_db)) -> list[PlanEditOut]:
    repo = PlanRepository(db)
    if repo.get_plan(plan_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found.")
    return [PlanEditOut.model_validate(edit) for edit in repo.get_edits(plan_id)]
