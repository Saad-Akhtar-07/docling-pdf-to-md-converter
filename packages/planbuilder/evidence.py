"""Objective -> EvidenceCard draft: docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md
§2.6 Stage 4.

This module only makes the LLM call and returns the model's claims —
expected ideas paired with claimed-verbatim quotes, misconceptions, and
prerequisite references. It does not touch anchoring (anchor.py) or the
accept/drop gate (validate.py): a quote here is unverified until anchor.py
either finds it in real source text or doesn't.

`prerequisite_indices` references a caller-supplied numbered list of prior
objectives (id, statement) rather than objective UUIDs directly — asking a
model to reliably reproduce a UUID is asking for trouble; asking it to pick
from a short numbered list is not.
"""

from __future__ import annotations

from pydantic import BaseModel

from slidevision.llm import complete
from slidevision.llm.prompts import load_prompt
from slidevision.planbuilder.slides import SlideSummary, format_slide_entries

PROMPT_ID = "build_evidence"
PROMPT_VERSION = "v1"

MAX_EXPECTED_IDEAS = 5
MAX_MISCONCEPTIONS = 3

# Same rationale as objectives.py's OBJECTIVES_MAX_TOKENS (reasoning-token
# overhead on this gateway's models), sized up further: this call's output
# includes full verbatim quotes for up to 5 ideas plus misconceptions plus
# prerequisite indices, which is more output text than objectives.py
# produces from a similarly-sized input.
EVIDENCE_MAX_TOKENS = 4096


class ExpectedIdeaDraft(BaseModel):
    idea: str
    quote: str


class MisconceptionDraft(BaseModel):
    code: str
    text: str


class EvidenceCardDraft(BaseModel):
    expected_ideas: list[ExpectedIdeaDraft]
    known_misconceptions: list[MisconceptionDraft]
    prerequisite_indices: list[int]


def _format_prior_objectives(prior_objectives: list[tuple[int, str]]) -> str:
    if not prior_objectives:
        return "No prior objectives (this is the first objective in the course)."
    lines = [f"{index}: {statement}" for index, statement in prior_objectives]
    return "Prior objectives already covered in this course:\n" + "\n".join(lines)


def build_evidence_card(
    objective_statement: str,
    unit_slides: list[SlideSummary],
    prior_objectives: list[tuple[int, str]],
    *,
    prompt_id: str = PROMPT_ID,
    prompt_version: str = PROMPT_VERSION,
) -> EvidenceCardDraft:
    if not unit_slides:
        raise ValueError(f"objective {objective_statement!r} has no unit slides to build evidence from")

    system_prompt = load_prompt(prompt_id, prompt_version)
    user_content = (
        f"Objective: {objective_statement}\n\n"
        f"Slides:\n\n{format_slide_entries(unit_slides)}\n\n"
        f"{_format_prior_objectives(prior_objectives)}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    result = complete(
        purpose="plan",
        messages=messages,
        schema=EvidenceCardDraft,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        max_tokens=EVIDENCE_MAX_TOKENS,
    )
    draft = result.parsed
    return EvidenceCardDraft(
        expected_ideas=draft.expected_ideas[:MAX_EXPECTED_IDEAS],
        known_misconceptions=draft.known_misconceptions[:MAX_MISCONCEPTIONS],
        prerequisite_indices=draft.prerequisite_indices,
    )
