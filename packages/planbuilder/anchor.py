"""Quote -> (block_id, char_start, char_end): THE CRITICAL COMPONENT.

docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §1.2 / §2.6 Stage 5: "an unanchorable
idea does not exist." This module never invents a span — it either finds one
in real source text or returns None, and the caller (validate.py) drops the
idea.

Strategy, in order:
  1. Exact substring match (`str.find`) in each candidate block.
  2. Fuzzy match (rapidfuzz's `partial_ratio_alignment`, which — unlike
     plain `partial_ratio` — returns the *position* of the best-aligned
     substring, not just a score) as a fallback for OCR noise or minor
     whitespace/punctuation drift between the model's "verbatim" quote and
     the stored block text.

Threshold justification (empirical, not guessed — see the conversation that
built this module): tested against real block text, a genuine near-verbatim
quote with light noise (punctuation/case/hyphen drift) scored ~97; a
plausible-sounding PARAPHRASE of real content (same idea, different words —
exactly the "the model paraphrased instead of quoting" failure this
two-tier strategy exists to catch) scored 68; a fully hallucinated quote
about unrelated content scored 43-48. FUZZY_MATCH_THRESHOLD = 85 sits
comfortably above the paraphrase/hallucination band and below the
noisy-but-genuine band, so raising it would reject legitimate OCR noise and
lowering it would start accepting paraphrases as if they were quotes --
exactly the failure mode §1.2 warns about ("prep-time error becomes
runtime error with no detection path").

Anchoring to a `model_generated` block is a hard error here (raises), not a
silent skip: CLAUDE.md invariant #4 makes this a correctness bug in the
caller, not a normal "no match" outcome, if it's ever reached.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from slidevision.planbuilder.slides import CITABLE_PROVENANCE, SourceBlock

FUZZY_MATCH_THRESHOLD = 85.0

# A match below this length is accepted too easily by fuzzy scoring (a short
# common phrase can score >85 against unrelated text purely by chance) and
# is rarely a meaningful "idea" anchor anyway.
MIN_QUOTE_CHARS = 12


class AnchoringToModelGeneratedBlockError(ValueError):
    """A candidate block passed to resolve_anchor() was not verbatim/ocr.
    This must never happen — callers are responsible for filtering
    candidates to CITABLE_PROVENANCE before calling in; reaching this means
    that filter was skipped somewhere, which is a bug to fix, not a case to
    handle gracefully."""

    def __init__(self, block_id: str, provenance: str) -> None:
        self.block_id = block_id
        self.provenance = provenance
        super().__init__(
            f"block {block_id!r} has provenance={provenance!r}, not in {sorted(CITABLE_PROVENANCE)} — "
            "anchoring to a model_generated block is a hard error, not a warning."
        )


@dataclass
class Anchor:
    block_id: str
    char_start: int
    char_end: int
    match_kind: str  # "exact" | "fuzzy"
    score: float  # 100.0 for exact


def _find_exact(quote: str, candidates: list[SourceBlock]) -> Anchor | None:
    for block in candidates:
        idx = block.text.find(quote)
        if idx != -1:
            return Anchor(block_id=block.block_id, char_start=idx, char_end=idx + len(quote), match_kind="exact", score=100.0)
    return None


def _find_fuzzy(quote: str, candidates: list[SourceBlock]) -> Anchor | None:
    best: Anchor | None = None
    for block in candidates:
        if not block.text:
            continue
        result = fuzz.partial_ratio_alignment(quote, block.text)
        if result.score < FUZZY_MATCH_THRESHOLD:
            continue
        if best is None or result.score > best.score:
            best = Anchor(
                block_id=block.block_id,
                char_start=result.dest_start,
                char_end=result.dest_end,
                match_kind="fuzzy",
                score=result.score,
            )
    return best


def resolve_anchor(quote: str, candidate_blocks: list[SourceBlock]) -> Anchor | None:
    """quote: the model's claimed verbatim supporting text for one idea.
    candidate_blocks: verbatim/ocr blocks from the idea's unit to search —
    the caller must have already filtered these to CITABLE_PROVENANCE.

    Returns None (never a guess) if no block clears FUZZY_MATCH_THRESHOLD.
    """
    for block in candidate_blocks:
        if block.provenance not in CITABLE_PROVENANCE:
            raise AnchoringToModelGeneratedBlockError(block.block_id, block.provenance)

    quote = quote.strip()
    if len(quote) < MIN_QUOTE_CHARS:
        return None

    exact = _find_exact(quote, candidate_blocks)
    if exact is not None:
        return exact
    return _find_fuzzy(quote, candidate_blocks)
