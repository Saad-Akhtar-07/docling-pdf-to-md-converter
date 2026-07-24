"""Groups extracted blocks into one summary per slide.

Deliberately decoupled from packages/persistence's ORM models (same
boundary style as packages/extraction's Block / packages/llm's messages):
apps/api's job glue converts DocumentBlock rows into SourceBlock here, so
segment.py / objectives.py stay testable without a database.

`model_generated` content (vision-model slide descriptions) is kept
separate from `citable_text` and explicitly labeled when included in a
prompt — it may inform segmentation/objective wording but, per CLAUDE.md
invariant #4, nothing may ever anchor a citation to it. Evidence-card
anchoring is out of scope for this module anyway (deferred), but keeping
the two texts apart now avoids that mistake being easy to make later.
"""

from __future__ import annotations

from pydantic import BaseModel

CITABLE_PROVENANCE = {"verbatim", "ocr"}
TITLE_MAX_CHARS = 120


class SourceBlock(BaseModel):
    block_id: str
    slide_no: int
    order_index: int
    text: str
    provenance: str


class SlideSummary(BaseModel):
    slide_no: int
    title: str
    citable_text: str
    visual_notes: str | None = None


def _first_line(text: str, max_chars: int = TITLE_MAX_CHARS) -> str:
    first_line = text.strip().splitlines()[0].strip() if text.strip() else ""
    return first_line[:max_chars]


def build_slide_summaries(blocks: list[SourceBlock]) -> list[SlideSummary]:
    by_slide: dict[int, list[SourceBlock]] = {}
    for block in blocks:
        by_slide.setdefault(block.slide_no, []).append(block)

    summaries: list[SlideSummary] = []
    for slide_no in sorted(by_slide):
        slide_blocks = sorted(by_slide[slide_no], key=lambda b: b.order_index)
        citable = [b.text for b in slide_blocks if b.provenance in CITABLE_PROVENANCE]
        visual = [b.text for b in slide_blocks if b.provenance not in CITABLE_PROVENANCE]

        citable_text = "\n".join(citable)
        title = _first_line(citable_text) or _first_line("\n".join(visual)) or f"Slide {slide_no}"

        summaries.append(
            SlideSummary(
                slide_no=slide_no,
                title=title,
                citable_text=citable_text,
                visual_notes="\n".join(visual) or None,
            )
        )
    return summaries
