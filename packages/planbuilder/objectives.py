"""Unit -> LearningObjective[]: docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §2.6 Stage 3.

"Reject objectives that are pure recall of a definition when the unit
supports a reasoning-level objective" is enforced twice, per CLAUDE.md:
once as an explicit prompt constraint (prompts/generate_objectives/v1.md),
and once as a code-level post-check here (`looks_like_pure_recall`) that
doesn't just trust the model's own self-reported `is_recall_only` flag.
"""

from __future__ import annotations

from pydantic import BaseModel

from slidevision.llm import complete
from slidevision.llm.prompts import load_prompt
from slidevision.planbuilder.slides import SlideSummary, format_slide_entries

PROMPT_ID = "generate_objectives"
PROMPT_VERSION = "v1"

MAX_OBJECTIVES = 4

# See segment.py's SEGMENTATION_MAX_TOKENS for why this isn't left at
# complete()'s 1024 default -- smaller task (one unit) than segmentation,
# but still comfortably above the observed reasoning-token overhead. Bumped
# from 2048 after a real run: the largest unit in a 40-slide demo deck (5
# slides) hit empty-content on 3 consecutive build attempts (2048 was
# apparently still not enough headroom for its reasoning + output on that
# much source text) while every smaller unit succeeded first try.
OBJECTIVES_MAX_TOKENS = 3072

RECALL_VERBS = ("define", "list", "name", "state", "recall", "identify", "recite", "label")
REASONING_CUES = (
    "explain",
    "compare",
    "apply",
    "predict",
    "justify",
    "distinguish",
    "evaluate",
    "analyze",
    "analyse",
    "derive",
    "design",
    "critique",
    "argue",
    "diagnose",
    "why",
)


class ObjectiveDraft(BaseModel):
    statement: str
    is_recall_only: bool


class UnitObjectivesResult(BaseModel):
    objectives: list[ObjectiveDraft]


def looks_like_pure_recall(statement: str) -> bool:
    """Heuristic cross-check: a "Student can ..." statement that opens on a
    recall verb (define/list/name/...) and contains no reasoning cue word
    anywhere is treated as recall-only regardless of what the model claimed."""
    body = statement.strip().lower()
    prefix = "student can "
    if body.startswith(prefix):
        body = body[len(prefix) :]
    if not any(body.startswith(verb) for verb in RECALL_VERBS):
        return False
    return not any(cue in body for cue in REASONING_CUES)


def filter_recall_only(objectives: list[ObjectiveDraft]) -> list[ObjectiveDraft]:
    """Drops recall-only objectives, but only when doing so still leaves at
    least 2 -- i.e. only "when the unit supports a reasoning-level
    objective" as an actual alternative already present in the response,
    per the module's explicit instruction."""
    flags = [obj.is_recall_only or looks_like_pure_recall(obj.statement) for obj in objectives]
    non_recall = [obj for obj, recall in zip(objectives, flags) if not recall]
    if any(flags) and len(non_recall) >= 2:
        return non_recall[:MAX_OBJECTIVES]
    return objectives[:MAX_OBJECTIVES]


def _format_unit_block(unit_title: str, unit_summary: str, unit_slides: list[SlideSummary]) -> str:
    header = f"Unit: {unit_title}\nSummary: {unit_summary}\n\nSlides:"
    return f"{header}\n\n{format_slide_entries(unit_slides)}"


def build_objectives(
    unit_title: str,
    unit_summary: str | None,
    unit_slides: list[SlideSummary],
    *,
    prompt_id: str = PROMPT_ID,
    prompt_version: str = PROMPT_VERSION,
) -> list[ObjectiveDraft]:
    if not unit_slides:
        raise ValueError(f"unit {unit_title!r} has no slides to generate objectives from")

    system_prompt = load_prompt(prompt_id, prompt_version)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _format_unit_block(unit_title, unit_summary or "", unit_slides)},
    ]
    result = complete(
        purpose="plan",
        messages=messages,
        schema=UnitObjectivesResult,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        max_tokens=OBJECTIVES_MAX_TOKENS,
    )
    return filter_recall_only(result.parsed.objectives)
