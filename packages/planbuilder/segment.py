"""Blocks -> LearningUnit[]: docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §2.6 Stage 2.

structured.py (packages/llm) already guarantees a well-formed
UnitSegmentationResult -- but "well-formed JSON matching the schema" says
nothing about whether the proposed units actually partition the deck. That
domain rule is asserted here, in code, and is allowed exactly one retry of
the whole segmentation call before giving up (CLAUDE.md: "do not trust the
model -- assert it in code and retry once on failure").
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel

from slidevision.llm import complete
from slidevision.llm.prompts import load_prompt
from slidevision.planbuilder.errors import PartitionError
from slidevision.planbuilder.slides import SlideSummary, format_slide_entries

PROMPT_ID = "segment_units"
PROMPT_VERSION = "v1"

# client.py's complete() defaults max_tokens=1024, sized for small structured
# calls. Segmenting a full deck is a large structured response (title +
# summary + every slide_id, times up to ~15 units) on top of these models'
# own hidden reasoning tokens (packages/llm/structured.py's module docstring
# / docs/BACKLOG.md: observed 100-250+ reasoning tokens even on tiny
# prompts) -- 1024 was observed to starve a 40-slide segmentation into empty
# content on BOTH the primary and repair attempt. Generous, not tuned per
# deck size: undershooting here fails the whole plan build, overshooting
# just costs a bit more.
SEGMENTATION_MAX_TOKENS = 4096


class UnitDraft(BaseModel):
    title: str
    summary: str
    slide_ids: list[int]


class UnitSegmentationResult(BaseModel):
    units: list[UnitDraft]


def _suggested_unit_range(num_slides: int) -> tuple[int, int]:
    """Guidance only, passed into the prompt -- never enforced in code. A
    40-slide deck should land around 8-14 units per the roadmap; this scales
    that ratio (~1 unit per 3-5 slides) to whatever deck size is given."""
    low = max(3, round(num_slides / 5))
    high = max(low + 1, round(num_slides / 2.5))
    return low, high


def _build_messages(slides: list[SlideSummary], system_prompt: str) -> list[dict]:
    low, high = _suggested_unit_range(len(slides))
    user_content = (
        f"This deck has {len(slides)} slides. As guidance only (the hard rules above take "
        f"priority), aim for roughly {low}-{high} units.\n\n{format_slide_entries(slides)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def validate_partition(units: list[UnitDraft], expected_slide_ids: list[int]) -> None:
    """Raises PartitionError unless every expected slide id appears in
    exactly one unit's slide_ids -- no gaps, no overlaps, no hallucinated
    slide numbers."""
    expected = set(expected_slide_ids)
    seen: Counter[int] = Counter()
    got: set[int] = set()
    for unit in units:
        for slide_id in unit.slide_ids:
            seen[slide_id] += 1
            got.add(slide_id)

    missing = sorted(expected - got)
    unknown = sorted(got - expected)
    duplicated = sorted(slide_id for slide_id, count in seen.items() if count > 1 and slide_id in expected)
    if missing or unknown or duplicated:
        raise PartitionError(missing=missing, duplicated=duplicated, unknown=unknown)


def build_units(
    slides: list[SlideSummary],
    *,
    prompt_id: str = PROMPT_ID,
    prompt_version: str = PROMPT_VERSION,
) -> tuple[list[UnitDraft], str]:
    """Returns (units, model_used). One retry of the full call on an invalid
    partition; a second failure propagates PartitionError to the caller."""
    if not slides:
        raise ValueError("no slides to segment")

    expected_slide_ids = [slide.slide_no for slide in slides]
    system_prompt = load_prompt(prompt_id, prompt_version)
    messages = _build_messages(slides, system_prompt)

    result = complete(
        purpose="plan",
        messages=messages,
        schema=UnitSegmentationResult,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        max_tokens=SEGMENTATION_MAX_TOKENS,
    )
    try:
        validate_partition(result.parsed.units, expected_slide_ids)
        return result.parsed.units, result.model
    except PartitionError as first_error:
        retry_messages = [
            *messages,
            {"role": "assistant", "content": result.content},
            {
                "role": "user",
                "content": (
                    f"That segmentation is invalid: {first_error}. Return a corrected set of "
                    f"units where every slide number in {expected_slide_ids} appears in exactly "
                    "one unit's slide_ids, with no omissions and no duplicates."
                ),
            },
        ]
        retry_result = complete(
            purpose="plan",
            messages=retry_messages,
            schema=UnitSegmentationResult,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            max_tokens=SEGMENTATION_MAX_TOKENS,
        )
        validate_partition(retry_result.parsed.units, expected_slide_ids)  # raises again -> propagates
        return retry_result.parsed.units, retry_result.model
