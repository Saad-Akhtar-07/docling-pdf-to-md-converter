"""Repository for the learning-plan aggregate (learning_plans, learning_units,
learning_objectives, objective_expected_ideas, objective_misconceptions).

CRUD only — no anchoring/validation logic. That belongs to Module 2's plan
builder (packages/planbuilder).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from slidevision.persistence.enums import PlanStatus
from slidevision.persistence.models import (
    LearningObjective,
    LearningPlan,
    LearningUnit,
    ObjectiveExpectedIdea,
    ObjectiveMisconception,
)


class PlanRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_plan(
        self,
        *,
        document_id: uuid.UUID,
        version: int,
        status: PlanStatus = PlanStatus.DRAFT,
        builder_prompt_version: str | None = None,
        model: str | None = None,
    ) -> LearningPlan:
        plan = LearningPlan(
            document_id=document_id,
            version=version,
            status=status,
            builder_prompt_version=builder_prompt_version,
            model=model,
        )
        self.session.add(plan)
        self.session.flush()
        return plan

    def get_plan(self, plan_id: uuid.UUID) -> LearningPlan | None:
        return self.session.get(LearningPlan, plan_id)

    def latest_version(self, document_id: uuid.UUID) -> LearningPlan | None:
        stmt = (
            select(LearningPlan)
            .where(LearningPlan.document_id == document_id)
            .order_by(LearningPlan.version.desc())
            .limit(1)
        )
        return self.session.scalars(stmt).first()

    def add_unit(self, *, plan_id: uuid.UUID, title: str, order_index: int, summary: str | None = None, slide_ids: list[int] | None = None) -> LearningUnit:
        unit = LearningUnit(
            plan_id=plan_id,
            title=title,
            order_index=order_index,
            summary=summary,
            slide_ids=slide_ids or [],
        )
        self.session.add(unit)
        self.session.flush()
        return unit

    def add_objective(
        self,
        *,
        unit_id: uuid.UUID,
        statement: str,
        order_index: int,
        low_confidence: bool = False,
        prerequisite_objective_ids: list[uuid.UUID] | None = None,
    ) -> LearningObjective:
        objective = LearningObjective(
            unit_id=unit_id,
            statement=statement,
            order_index=order_index,
            low_confidence=low_confidence,
            prerequisite_objective_ids=prerequisite_objective_ids or [],
        )
        self.session.add(objective)
        self.session.flush()
        return objective

    def get_objective(self, objective_id: uuid.UUID) -> LearningObjective | None:
        return self.session.get(LearningObjective, objective_id)

    def update_objective(
        self,
        objective_id: uuid.UUID,
        *,
        low_confidence: bool | None = None,
        prerequisite_objective_ids: list[uuid.UUID] | None = None,
    ) -> LearningObjective:
        """Evidence-card stage (packages/planbuilder/validate.py) sets these
        after the objective row already exists -- low_confidence depends on
        how many of its ideas actually anchor, and prerequisite ids depend
        on resolving the model's picks from a numbered list of prior
        objectives, both only knowable once evidence generation runs."""
        objective = self.session.get(LearningObjective, objective_id)
        if objective is None:
            raise ValueError(f"no learning_objectives row with id={objective_id}")
        if low_confidence is not None:
            objective.low_confidence = low_confidence
        if prerequisite_objective_ids is not None:
            objective.prerequisite_objective_ids = prerequisite_objective_ids
        self.session.flush()
        return objective

    def add_expected_idea(
        self, *, objective_id: uuid.UUID, idea: str, block_id: str, char_start: int, char_end: int
    ) -> ObjectiveExpectedIdea:
        expected_idea = ObjectiveExpectedIdea(
            objective_id=objective_id,
            idea=idea,
            block_id=block_id,
            char_start=char_start,
            char_end=char_end,
        )
        self.session.add(expected_idea)
        self.session.flush()
        return expected_idea

    def add_misconception(self, *, objective_id: uuid.UUID, code: str, text: str) -> ObjectiveMisconception:
        misconception = ObjectiveMisconception(objective_id=objective_id, code=code, text=text)
        self.session.add(misconception)
        self.session.flush()
        return misconception
