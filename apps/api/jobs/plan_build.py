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

Both the objective stage and the evidence-card stage (§2.6 Stage 4-5) run
concurrently across their unit of work (bounded by LLM_MAX_CONCURRENCY, the
same limiter packages/llm/client.py already enforces on outbound HTTP
calls) -- sequentially, a dozen-plus calls at ~20-40s each cannot fit the
module's own "under 3 minutes" target for objectives, and evidence cards
are one call *per objective* (more calls, not fewer). Each call happens in
a worker thread with no DB access; results are persisted back on the main
thread/session afterward, so SQLAlchemy's one-session-per-thread rule is
never at risk. A single unit/objective failing (this gateway's reasoning
models empty-content on roughly 1/6-1/8 calls -- docs/BACKLOG.md -- so
two-in-a-row, while individually unlikely, happens regularly across a
couple dozen calls) is logged and skipped rather than aborting the whole
job: that unit/objective is simply left without objectives/evidence, which
`is_incomplete` already treats as resumable.

Evidence-card resumability signal: an objective counts as "done" once it
has *any* persisted expected idea or misconception. Misconceptions aren't
subject to the anchor-drop gate (they're persisted whenever the LLM call
succeeds, unlike ideas), so a genuinely-zero-idea-and-zero-misconception
"done" objective is vanishingly rare in practice -- and even if it
happens, re-running evidence generation for it on the next resume is
harmless, not a correctness bug.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from slidevision.llm.config import MAX_CONCURRENCY
from slidevision.persistence.db import SessionLocal
from slidevision.persistence.models import LearningObjective, LearningPlan
from slidevision.persistence.repositories import DocumentRepository, PlanRepository
from slidevision.planbuilder import (
    AnchoredIdea,
    EvidenceBuildReport,
    MisconceptionDraft,
    ObjectiveEvidenceResult,
    PriorObjectiveRef,
    build_and_validate_evidence,
    build_objectives,
    build_slide_summaries,
    build_units,
    citable_blocks_for_slides,
)
from slidevision.planbuilder.objectives import ObjectiveDraft
from slidevision.planbuilder.slides import SlideSummary, SourceBlock

logger = logging.getLogger(__name__)


def is_incomplete(plan: LearningPlan) -> bool:
    """A plan with no units yet, any unit with no objectives yet, or any
    objective with no evidence (ideas/misconceptions) yet, is still
    mid-build -- safe (and correct) to resume rather than starting a new
    version."""
    if not plan.units:
        return True
    for unit in plan.units:
        if not unit.objectives:
            return True
        for objective in unit.objectives:
            if not objective.expected_ideas and not objective.misconceptions:
                return True
    return False


def _result_from_persisted(objective: LearningObjective) -> ObjectiveEvidenceResult:
    """Reconstructs a report entry for an objective whose evidence was
    already built (this run or an earlier partial one). Dropped ideas
    aren't persisted, so a resumed objective's `dropped_ideas` is always
    empty here -- the cumulative build report undercounts historical drops
    across resumes; only ideas dropped in the *current* process are visible
    in that detail. The summary counts that matter for the acceptance gate
    (anchored ideas, low_confidence, zero_ideas) are unaffected, since those
    come from what's actually persisted, not from the drop log."""
    return ObjectiveEvidenceResult(
        objective_id=objective.id,
        objective_statement=objective.statement,
        anchored_ideas=[
            AnchoredIdea(idea=i.idea, block_id=i.block_id, char_start=i.char_start, char_end=i.char_end)
            for i in objective.expected_ideas
        ],
        dropped_ideas=[],
        misconceptions=[MisconceptionDraft(code=m.code, text=m.text) for m in objective.misconceptions],
        prerequisite_objective_ids=list(objective.prerequisite_objective_ids or []),
    )


def run_plan_build_job(plan_id: uuid.UUID) -> EvidenceBuildReport | None:
    """Returns the evidence build report on success (also useful for
    scripting -- see scripts/build_plan_demo.py), or None if the plan was
    deleted mid-flight or the job failed (already logged either way).
    apps/api/routers/plans.py schedules this via BackgroundTasks, which
    ignores the return value; that's fine, it's optional plumbing."""
    session = SessionLocal()
    plan_repo = PlanRepository(session)
    doc_repo = DocumentRepository(session)
    try:
        plan = plan_repo.get_plan(plan_id)
        if plan is None:
            return None  # deleted between being scheduled and running

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
                # `low_confidence` is set by the evidence-card stage below,
                # once it's known how many of this objective's ideas actually
                # anchor -- not knowable yet at objective-creation time.
                # `draft.is_recall_only` has no column of its own to land in,
                # so it's used only for filter_recall_only()'s in-memory
                # decision and isn't persisted here.
                plan_repo.add_objective(
                    unit_id=unit["id"],
                    statement=draft.statement,
                    order_index=order_index,
                )
                session.commit()

        logger.info("plan %s objectives built: %d units", plan.id, len(persisted_units))

        # --- Stage 4-5: evidence cards, anchored (packages/planbuilder/
        # evidence.py, anchor.py, validate.py) ---
        session.expire_all()  # pick up the objectives just committed above
        plan = plan_repo.get_plan(plan_id)
        all_units = sorted(plan.units, key=lambda unit: unit.order_index)

        # Curriculum order: unit order, then objective order within unit.
        # Built from *every* objective (done or pending), so prerequisite
        # indices stay consistent across resumes regardless of what this
        # particular run happens to (re)process.
        ordered_objectives: list[tuple[uuid.UUID, LearningObjective]] = [
            (unit.id, objective)
            for unit in all_units
            for objective in sorted(unit.objectives, key=lambda o: o.order_index)
        ]
        objective_refs = [
            PriorObjectiveRef(index=index, objective_id=objective.id, statement=objective.statement)
            for index, (_unit_id, objective) in enumerate(ordered_objectives)
        ]
        unit_slides_by_id = {
            unit.id: [slides_by_no[sid] for sid in unit.slide_ids if sid in slides_by_no] for unit in all_units
        }
        unit_citable_blocks_by_id = {
            unit.id: citable_blocks_for_slides(source_blocks, set(unit.slide_ids)) for unit in all_units
        }

        evidence_results: list[ObjectiveEvidenceResult] = []
        pending_evidence = []
        for index, (unit_id, objective) in enumerate(ordered_objectives):
            if objective.expected_ideas or objective.misconceptions:
                evidence_results.append(_result_from_persisted(objective))
                continue
            pending_evidence.append(
                {"objective_id": objective.id, "statement": objective.statement, "unit_id": unit_id, "index": index}
            )

        def _build_evidence_for(entry: dict) -> ObjectiveEvidenceResult:
            prior_refs = [ref for ref in objective_refs if ref.index < entry["index"]]
            return build_and_validate_evidence(
                entry["objective_id"],
                entry["statement"],
                unit_slides_by_id[entry["unit_id"]],
                unit_citable_blocks_by_id[entry["unit_id"]],
                prior_refs,
            )

        results_by_objective_id: dict[uuid.UUID, ObjectiveEvidenceResult] = {}
        if pending_evidence:
            worker_count = max(1, min(MAX_CONCURRENCY, len(pending_evidence)))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_to_entry = {executor.submit(_build_evidence_for, entry): entry for entry in pending_evidence}
                for future in as_completed(future_to_entry):
                    entry = future_to_entry[future]
                    try:
                        results_by_objective_id[entry["objective_id"]] = future.result()
                    except Exception:
                        logger.exception(
                            "evidence generation failed for objective %s (%r) -- leaving it without "
                            "evidence; a later resume will retry just this objective",
                            entry["objective_id"],
                            entry["statement"],
                        )

        # Persist sequentially, back on the main thread's session.
        for entry in pending_evidence:
            result = results_by_objective_id.get(entry["objective_id"])
            if result is None:
                continue  # this objective's evidence generation failed -- resumable, not fatal

            for idea in result.anchored_ideas:
                plan_repo.add_expected_idea(
                    objective_id=result.objective_id,
                    idea=idea.idea,
                    block_id=idea.block_id,
                    char_start=idea.char_start,
                    char_end=idea.char_end,
                )
                session.commit()

            seen_codes: set[str] = set()
            for misconception in result.misconceptions:
                if misconception.code in seen_codes:
                    continue  # objective_misconceptions has a unique(objective_id, code) constraint
                seen_codes.add(misconception.code)
                plan_repo.add_misconception(
                    objective_id=result.objective_id, code=misconception.code, text=misconception.text
                )
                session.commit()

            plan_repo.update_objective(
                result.objective_id,
                low_confidence=result.low_confidence,
                prerequisite_objective_ids=result.prerequisite_objective_ids,
            )
            session.commit()
            evidence_results.append(result)

        report = EvidenceBuildReport(results=evidence_results)
        logger.info("plan %s evidence built: %s", plan.id, "; ".join(report.summary_lines()))
        return report

    except Exception:
        session.rollback()
        logger.exception("plan build failed for plan %s", plan_id)
        return None
    finally:
        session.close()
