"""LangGraph nodes 4-5 (docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §2.7):
`assess_response` (LLM) and `consistency_check` (pure). Turns a free-text
student answer into a validated, grounded `ObjectiveAssessment`.

Split matches the node table exactly: `assess_response_node` owns the one
LLM call and everything DB-shaped (building the evidence card, gathering
source text and recent turns) -- the repair step itself
(`repair_assessment`) is pure and lives in `slidevision.tutor_core`, called
unchanged by `consistency_check_node` here.

On StructuredOutputError (repair retry already exhausted inside
`packages/llm/structured.py`), `call_assess_llm` degrades to a safe default
(`verdict=confused`) rather than raising -- §2.13: "the session never
breaks because a model returned bad JSON."
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session as DbSession

from slidevision.graph.state import TurnState
from slidevision.llm import complete
from slidevision.llm.errors import StructuredOutputError
from slidevision.llm.prompts import load_prompt
from slidevision.persistence.models import DocumentBlock, LearningObjective, Turn
from slidevision.persistence.repositories import PlanRepository, SessionRepository
from slidevision.tutor_core import (
    EvidenceCard,
    EvidenceIdea,
    EvidenceMisconception,
    ObjectiveAssessment,
    ObjectiveState,
)
from slidevision.tutor_core.consistency import repair_assessment

PROMPT_ID = "assess_response"
PROMPT_VERSION = "v1"

# Structured schema + up to ~5 ideas/misconceptions of reasoning-model
# output; sized the same way packages/planbuilder's prompts were (see
# evidence.py's EVIDENCE_MAX_TOKENS docstring) rather than left at
# complete()'s 1024 default.
ASSESS_MAX_TOKENS = 1536

SAFE_DEFAULT_ASSESSMENT = ObjectiveAssessment(
    verdict="confused",
    objective_met=False,
    reasoning_depth="shallow",
)


def build_evidence_card(objective: LearningObjective) -> EvidenceCard:
    """objective (with its expected_ideas/misconceptions loaded) -> the pure
    EvidenceCard the assessment prompt and repair_assessment() both use.
    Idea order (and therefore the "idea_N" id each idea gets) is sorted by
    (block_id, char_start, id) rather than relationship insertion order, so
    the same objective always produces the same card -- required for the
    turn contract's reproducibility rule (§2.5 rule 3)."""
    ideas = sorted(objective.expected_ideas, key=lambda idea: (idea.block_id, idea.char_start, str(idea.id)))
    expected_ideas = [EvidenceIdea(id=f"idea_{n}", idea=idea.idea) for n, idea in enumerate(ideas, start=1)]
    misconceptions = sorted(objective.misconceptions, key=lambda m: m.code)
    known_misconceptions = [EvidenceMisconception(code=m.code, text=m.text) for m in misconceptions]
    return EvidenceCard(
        objective_id=str(objective.id),
        expected_ideas=expected_ideas,
        known_misconceptions=known_misconceptions,
    )


def _format_source_blocks(db: DbSession, objective: LearningObjective) -> str:
    block_ids = sorted({idea.block_id for idea in objective.expected_ideas})
    if not block_ids:
        return "(no anchored source text available for this objective)"
    blocks = [db.get(DocumentBlock, block_id) for block_id in block_ids]
    lines = [f"[{block.id}] (slide {block.slide_no}): {block.text}" for block in blocks if block is not None]
    return "\n".join(lines) if lines else "(no anchored source text available for this objective)"


def _last_tutor_question(db: DbSession, session_id: uuid.UUID) -> str | None:
    turns: list[Turn] = SessionRepository(db).get_turns(session_id)
    if not turns:
        return None
    return turns[-1].tutor_message


def _format_recent_turns(db: DbSession, session_id: uuid.UUID, *, limit: int = 3) -> str:
    turns = SessionRepository(db).get_turns(session_id)[-limit:]
    if not turns:
        return "(no prior turns)"
    lines: list[str] = []
    for turn in turns:
        if turn.tutor_message:
            lines.append(f"Tutor: {turn.tutor_message}")
        if turn.student_message:
            lines.append(f"Student: {turn.student_message}")
    return "\n".join(lines)


def _format_objective_state(state: ObjectiveState | None) -> str:
    if state is None:
        return "status=unseen, attempts=0"
    return f"status={state.status.value}, attempts={state.attempts}, hint_level={state.hint_level}"


def build_messages(
    *,
    objective_statement: str,
    card: EvidenceCard,
    source_text: str,
    question: str,
    answer: str,
    recent_turns_text: str,
    objective_state_summary: str,
) -> list[dict]:
    system_prompt = load_prompt(PROMPT_ID, PROMPT_VERSION)
    ideas_block = "\n".join(f"- {idea.id}: {idea.idea}" for idea in card.expected_ideas) or "(none)"
    misconceptions_block = (
        "\n".join(f"- {m.code}: {m.text}" for m in card.known_misconceptions) or "(none)"
    )
    user_content = (
        f"Objective: {objective_statement}\n\n"
        f"Expected ideas:\n{ideas_block}\n\n"
        f"Known misconceptions:\n{misconceptions_block}\n\n"
        f"Source text:\n{source_text}\n\n"
        f"Recent conversation:\n{recent_turns_text}\n\n"
        f"Student's current progress on this objective: {objective_state_summary}\n\n"
        f"Question asked: {question}\n\n"
        f"Student's answer: {answer}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def call_assess_llm(
    messages: list[dict],
    *,
    session_id: uuid.UUID | None = None,
    turn_id: uuid.UUID | None = None,
) -> tuple[ObjectiveAssessment, bool]:
    """Returns (assessment, used_safe_default)."""
    try:
        result = complete(
            purpose="assess",
            messages=messages,
            schema=ObjectiveAssessment,
            prompt_id=PROMPT_ID,
            prompt_version=PROMPT_VERSION,
            session_id=session_id,
            turn_id=turn_id,
            max_tokens=ASSESS_MAX_TOKENS,
        )
        return result.parsed, False
    except StructuredOutputError:
        return SAFE_DEFAULT_ASSESSMENT.model_copy(deep=True), True


def assess_and_repair(
    *,
    objective_statement: str,
    card: EvidenceCard,
    source_text: str,
    question: str,
    answer: str,
    recent_turns_text: str = "(no prior turns)",
    objective_state_summary: str = "status=unseen, attempts=0",
    session_id: uuid.UUID | None = None,
    turn_id: uuid.UUID | None = None,
):
    """The full node-4 + node-5 pipeline as one call, independent of
    LangGraph/DB state -- what tests/fixture evaluation drive directly."""
    messages = build_messages(
        objective_statement=objective_statement,
        card=card,
        source_text=source_text,
        question=question,
        answer=answer,
        recent_turns_text=recent_turns_text,
        objective_state_summary=objective_state_summary,
    )
    raw, used_safe_default = call_assess_llm(messages, session_id=session_id, turn_id=turn_id)
    final, repairs = repair_assessment(raw, card=card, student_answer=answer)
    return final, repairs, used_safe_default


def assess_response_node(state: TurnState) -> dict:
    """Node 4 (§2.7): no-op (nothing to assess) on turn zero or once the
    session is already complete -- both carry `message is None` /
    `current_objective_id is None`."""
    db: DbSession = state["db"]
    message = state["message"]
    objective_id = state["current_objective_id"]
    if message is None or objective_id is None:
        return {
            "raw_assessment": None,
            "evidence_card": None,
            "assessed_objective_id": None,
            "assessment_used_safe_default": False,
        }

    plan_repo = PlanRepository(db)
    objective = plan_repo.get_objective(objective_id)
    card = build_evidence_card(objective)
    source_text = _format_source_blocks(db, objective)
    question = _last_tutor_question(db, state["session_id"]) or objective.statement
    recent_turns_text = _format_recent_turns(db, state["session_id"])
    objective_state_summary = _format_objective_state(state["objective_states"].get(str(objective_id)))

    messages = build_messages(
        objective_statement=objective.statement,
        card=card,
        source_text=source_text,
        question=question,
        answer=message,
        recent_turns_text=recent_turns_text,
        objective_state_summary=objective_state_summary,
    )
    raw, used_safe_default = call_assess_llm(messages, session_id=state["session_id"])

    return {
        "raw_assessment": raw,
        "evidence_card": card,
        "assessed_objective_id": objective_id,
        "assessment_used_safe_default": used_safe_default,
    }


def consistency_check_node(state: TurnState) -> dict:
    """Node 5 (§2.7): pure, no LLM/DB -- entirely `tutor_core.repair_assessment`."""
    raw = state.get("raw_assessment")
    card = state.get("evidence_card")
    if raw is None or card is None:
        return {"assessment": None, "assessment_repairs": []}
    final, repairs = repair_assessment(raw, card=card, student_answer=state["message"])
    return {"assessment": final, "assessment_repairs": repairs}
