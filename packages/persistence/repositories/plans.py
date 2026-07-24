"""Repository for the learning-plan aggregate (learning_plans, learning_units,
learning_objectives, objective_expected_ideas, objective_misconceptions,
plan_edits).

CRUD only — no anchoring/validation logic. That belongs to Module 2's plan
builder (packages/planbuilder). The one exception is the draft/approved
guard on Module 3's mutation methods (edit_objective, delete_objective,
replace_expected_ideas, approve_plan): CLAUDE.md invariant requires "approved
plans REJECT all edits with 409, enforced in the repository layer, not just
the router" — a router-only check would be bypassed by any other caller
(scripts, a future job), so the guard lives here.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from slidevision.persistence.enums import PlanEditAction, PlanStatus
from slidevision.persistence.errors import PlanNotEditableError
from slidevision.persistence.models import (
    LearningObjective,
    LearningPlan,
    LearningUnit,
    ObjectiveExpectedIdea,
    ObjectiveMisconception,
    PlanEdit,
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

    # --- Module 3: plan review (draft-only mutation guard + audit trail) ---

    @staticmethod
    def _require_draft(plan: LearningPlan) -> None:
        if plan.status != PlanStatus.DRAFT:
            raise PlanNotEditableError(
                f"plan {plan.id} is {plan.status.value}; only draft plans accept edits"
            )

    def edit_objective(
        self, objective_id: uuid.UUID, *, statement: str | None = None, reviewed: bool | None = None
    ) -> LearningObjective:
        """Reviewer edits to an objective's own fields (Module 3). Distinct
        from `update_objective` above, which the plan-builder job (Module 2)
        uses to set evidence-derived fields (`low_confidence`,
        `prerequisite_objective_ids`) during the initial build — that path
        runs before a human ever sees the plan and has nothing to guard."""
        objective = self.session.get(LearningObjective, objective_id)
        if objective is None:
            raise ValueError(f"no learning_objectives row with id={objective_id}")
        self._require_draft(objective.unit.plan)
        if statement is not None:
            objective.statement = statement
        if reviewed is not None:
            objective.reviewed = reviewed
        self.session.flush()
        return objective

    def delete_objective(self, objective_id: uuid.UUID) -> None:
        objective = self.session.get(LearningObjective, objective_id)
        if objective is None:
            raise ValueError(f"no learning_objectives row with id={objective_id}")
        self._require_draft(objective.unit.plan)
        self.session.delete(objective)
        self.session.flush()

    def replace_expected_ideas(
        self, objective_id: uuid.UUID, ideas: list[dict]
    ) -> list[ObjectiveExpectedIdea]:
        """Full-replace semantics for one objective's expected ideas: an
        entry carrying an existing idea's `id` updates that row in place
        (covers re-anchoring — idea/block_id/char_start/char_end can all
        change); an entry with no `id` inserts a new idea; any existing row
        whose id isn't present in `ideas` is deleted. This is how the review
        API supports "add/edit/remove expected ideas" through one PATCH
        field rather than three separate endpoints."""
        objective = self.session.get(LearningObjective, objective_id)
        if objective is None:
            raise ValueError(f"no learning_objectives row with id={objective_id}")
        self._require_draft(objective.unit.plan)

        # Mutated through the `expected_ideas` collection itself (append /
        # remove), not raw session.add()/delete() -- the objective instance
        # returned here is the same one the router re-reads afterward
        # (before/after audit snapshot, response body) within the same
        # session, and a collection already loaded into memory doesn't pick
        # up rows added/deleted only at the session level.
        existing_by_id = {row.id: row for row in objective.expected_ideas}
        keep_ids: set[uuid.UUID] = set()
        result: list[ObjectiveExpectedIdea] = []
        for entry in ideas:
            idea_id = entry.get("id")
            if idea_id is not None and idea_id in existing_by_id:
                row = existing_by_id[idea_id]
                row.idea = entry["idea"]
                row.block_id = entry["block_id"]
                row.char_start = entry["char_start"]
                row.char_end = entry["char_end"]
                keep_ids.add(idea_id)
                result.append(row)
            else:
                row = ObjectiveExpectedIdea(
                    idea=entry["idea"],
                    block_id=entry["block_id"],
                    char_start=entry["char_start"],
                    char_end=entry["char_end"],
                )
                objective.expected_ideas.append(row)
                result.append(row)
        for idea_id, row in existing_by_id.items():
            if idea_id not in keep_ids:
                objective.expected_ideas.remove(row)
        self.session.flush()
        return result

    def approve_plan(self, plan_id: uuid.UUID) -> LearningPlan:
        plan = self.session.get(LearningPlan, plan_id)
        if plan is None:
            raise ValueError(f"no learning_plans row with id={plan_id}")
        self._require_draft(plan)
        plan.status = PlanStatus.APPROVED
        self.session.flush()
        return plan

    def record_edit(
        self,
        *,
        plan_id: uuid.UUID,
        action: PlanEditAction,
        before: dict | None,
        after: dict | None,
        objective_id: uuid.UUID | None = None,
    ) -> PlanEdit:
        edit = PlanEdit(plan_id=plan_id, objective_id=objective_id, action=action, before=before, after=after)
        self.session.add(edit)
        self.session.flush()
        return edit

    def get_edits(self, plan_id: uuid.UUID) -> list[PlanEdit]:
        stmt = select(PlanEdit).where(PlanEdit.plan_id == plan_id).order_by(PlanEdit.created_at)
        return list(self.session.scalars(stmt))
