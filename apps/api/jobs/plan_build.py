"""Background plan-build job: a READY document's blocks become a draft
learning plan (units + objectives). Runs via FastAPI BackgroundTasks (see
apps/api/routers/plans.py). Offline, never in a session's request path
(docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md Module 2).

Resumable by construction, not by a status flag: the plan row is created
(and committed) before any LLM call, each unit is committed as soon as it's
produced, and each unit's objectives are committed as soon as they're
produced. If the process dies at any point, `plan.status` stays DRAFT and
whatever units/objectives already exist stay exactly as they are — nothing
is left half-written mid-row. `find_resumable_plan` (used by the router)
detects such a plan and re-runs this job against the same plan_id instead
of starting a new version: segmentation is skipped if units already exist
(re-running it could produce a different partition and orphan the existing
units), and objective generation is skipped per-unit if that unit already
has objectives.

Objective generation runs concurrently across units (bounded by
LLM_MAX_CONCURRENCY, the same limiter packages/llm/client.py already
enforces on outbound HTTP calls) -- sequentially, a 12-unit deck at
~25-40s/call cannot fit the module's own "under 3 minutes" target. Each
unit's LLM call happens in a worker thread with no DB access; results are
persisted back on the main thread/session afterward, so SQLAlchemy's
one-session-per-thread rule is never at risk. A single unit failing (this
gateway's reasoning models empty-content on roughly 1/6-1/8 calls --
docs/BACKLOG.md -- so two-in-a-row on one unit, while individually
unlikely, happens regularly across a dozen units) is logged and skipped
rather than aborting the whole job: that unit is simply left with zero
objectives, which `is_incomplete` already treats as resumable.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from slidevision.llm.config import MAX_CONCURRENCY
from slidevision.persistence.db import SessionLocal
from slidevision.persistence.models import LearningPlan
from slidevision.persistence.repositories import DocumentRepository, PlanRepository
from slidevision.planbuilder import build_objectives, build_slide_summaries, build_units
from slidevision.planbuilder.objectives import ObjectiveDraft
from slidevision.planbuilder.slides import SlideSummary, SourceBlock

logger = logging.getLogger(__name__)


def is_incomplete(plan: LearningPlan) -> bool:
    """A plan with no units yet, or with any unit that has no objectives
    yet, is still mid-build -- safe (and correct) to resume rather than
    starting a new version."""
    if not plan.units:
        return True
    return any(not unit.objectives for unit in plan.units)


def run_plan_build_job(plan_id: uuid.UUID) -> None:
    session = SessionLocal()
    plan_repo = PlanRepository(session)
    doc_repo = DocumentRepository(session)
    try:
        plan = plan_repo.get_plan(plan_id)
        if plan is None:
            return  # deleted between being scheduled and running

        blocks = doc_repo.get_blocks(plan.document_id)
        source_blocks = [
            SourceBlock(
                block_id=block.id,
                slide_no=block.slide_no,
                order_index=block.order_index,
                text=block.text,
                provenance=block.provenance.value,
            )
            for block in blocks
        ]
        slides = build_slide_summaries(source_blocks)
        slides_by_no = {slide.slide_no: slide for slide in slides}

        existing_units = sorted(plan.units, key=lambda unit: unit.order_index)
        if not existing_units:
            unit_drafts, model_used = build_units(slides)
            plan.model = model_used
            plan.builder_prompt_version = "segment_units/v1"
            session.commit()

            ordered_drafts = sorted(unit_drafts, key=lambda draft: min(draft.slide_ids))
            persisted_units = []
            for order_index, draft in enumerate(ordered_drafts):
                unit = plan_repo.add_unit(
                    plan_id=plan.id,
                    title=draft.title,
                    order_index=order_index,
                    summary=draft.summary,
                    slide_ids=sorted(draft.slide_ids),
                )
                session.commit()
                persisted_units.append(unit)
        else:
            persisted_units = existing_units

        # Extract plain data before handing anything to worker threads --
        # ORM objects are tied to `session`, which stays main-thread-only.
        pending_units = [
            {"id": unit.id, "title": unit.title, "summary": unit.summary, "slide_ids": unit.slide_ids}
            for unit in persisted_units
            if not unit.objectives
        ]

        def _build_for_unit(unit_title: str, unit_summary: str | None, slide_ids: list[int]) -> list[ObjectiveDraft]:
            unit_slides: list[SlideSummary] = [slides_by_no[sid] for sid in slide_ids if sid in slides_by_no]
            return build_objectives(unit_title, unit_summary, unit_slides)

        objectives_by_unit_id: dict[uuid.UUID, list[ObjectiveDraft]] = {}
        if pending_units:
            worker_count = max(1, min(MAX_CONCURRENCY, len(pending_units)))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_to_unit = {
                    executor.submit(_build_for_unit, u["title"], u["summary"], u["slide_ids"]): u
                    for u in pending_units
                }
                for future in as_completed(future_to_unit):
                    unit = future_to_unit[future]
                    try:
                        objectives_by_unit_id[unit["id"]] = future.result()
                    except Exception:
                        logger.exception(
                            "objective generation failed for unit %s (%r) -- leaving it without "
                            "objectives; a later resume will retry just this unit",
                            unit["id"],
                            unit["title"],
                        )

        # Persist sequentially, back on the main thread's session -- worker
        # threads only made LLM calls, no DB access, so this is the only
        # place these results touch `session`.
        for unit in pending_units:
            objective_drafts = objectives_by_unit_id.get(unit["id"])
            if objective_drafts is None:
                continue  # this unit's generation failed -- resumable, not fatal
            for order_index, draft in enumerate(objective_drafts):
                # `low_confidence` is reserved for the evidence-anchoring stage
                # (Module 2's anchor resolver, deferred -- see docs/BACKLOG.md);
                # `draft.is_recall_only` has no column of its own to land in
                # yet, so it's used only for filter_recall_only()'s in-memory
                # decision and isn't persisted here.
                plan_repo.add_objective(
                    unit_id=unit["id"],
                    statement=draft.statement,
                    order_index=order_index,
                )
                session.commit()

        logger.info("plan %s built: %d units", plan.id, len(persisted_units))

    except Exception:
        session.rollback()
        logger.exception("plan build failed for plan %s", plan_id)
    finally:
        session.close()
