"""Offline unit tests for packages/planbuilder/anchor.py + validate.py:
the anchoring gate that makes "an unanchorable idea does not exist" a real,
enforced invariant rather than a prompt instruction.

No network, no DB: evidence.py's `complete()` is monkeypatched at the point
validate.py's call chain reaches it, so these never touch packages/llm's
transport layer.
"""

from __future__ import annotations

import uuid

import pytest

from slidevision.llm.client import CompleteResult
from slidevision.planbuilder.anchor import (
    MIN_QUOTE_CHARS,
    AnchoringToModelGeneratedBlockError,
    resolve_anchor,
)
from slidevision.planbuilder.evidence import EvidenceCardDraft, ExpectedIdeaDraft, MisconceptionDraft
from slidevision.planbuilder.slides import SlideSummary, SourceBlock
from slidevision.planbuilder.validate import PriorObjectiveRef, build_and_validate_evidence, citable_blocks_for_slides

BLOCK_A = SourceBlock(
    block_id="b_a",
    slide_no=1,
    order_index=0,
    text="Merge sort splits the input in half recursively.",
    provenance="verbatim",
)
BLOCK_B = SourceBlock(
    block_id="b_b",
    slide_no=1,
    order_index=1,
    text="Merge sort is stable and runs in O(n log n) time in all cases.",
    provenance="ocr",
)
BLOCK_MODEL_GENERATED = SourceBlock(
    block_id="b_c",
    slide_no=1,
    order_index=2,
    text="Figure: a recursive split-and-merge diagram.",
    provenance="model_generated",
)

CITABLE_BLOCKS = [BLOCK_A, BLOCK_B]

# build_evidence_card() only needs unit_slides to be non-empty when
# complete() is mocked (it never actually reads slide content in these
# tests) -- a minimal stand-in slide is enough to pass that guard.
UNIT_SLIDES = [SlideSummary(slide_no=1, title="Merge Sort", citable_text=f"{BLOCK_A.text}\n{BLOCK_B.text}")]


# --- resolve_anchor: exact match, fuzzy match, no match, hard-error -------


def test_exact_quote_resolves_and_round_trips():
    quote = "Merge sort is stable and runs in O(n log n) time in all cases."
    anchor = resolve_anchor(quote, CITABLE_BLOCKS)
    assert anchor is not None
    assert anchor.block_id == "b_b"
    assert anchor.match_kind == "exact"
    # the whole point of an anchor: slicing the source text at (start, end)
    # must reproduce exactly what was matched.
    assert BLOCK_B.text[anchor.char_start : anchor.char_end] == quote


def test_noisy_quote_resolves_via_fuzzy_fallback():
    # punctuation/case drift vs. BLOCK_B's real text -- not an exact substring
    noisy_quote = "merge sort is stable and runs in O(n log n) time in all cases"
    anchor = resolve_anchor(noisy_quote, CITABLE_BLOCKS)
    assert anchor is not None
    assert anchor.block_id == "b_b"
    assert anchor.match_kind == "fuzzy"
    recovered = BLOCK_B.text[anchor.char_start : anchor.char_end]
    # round-trips to *a* real span of source text, not to the noisy quote
    # verbatim -- that's expected: fuzzy matching finds where in the real
    # text the quote most likely came from, not a copy of the quote itself.
    assert recovered in BLOCK_B.text
    assert len(recovered) > 0


def test_hallucinated_quote_does_not_resolve():
    hallucinated = "Quick sort uses a randomly chosen pivot to partition elements in place."
    anchor = resolve_anchor(hallucinated, CITABLE_BLOCKS)
    assert anchor is None


def test_quote_shorter_than_minimum_does_not_resolve():
    short_quote = "sort" * 1  # well under MIN_QUOTE_CHARS
    assert len(short_quote) < MIN_QUOTE_CHARS
    assert resolve_anchor(short_quote, CITABLE_BLOCKS) is None


def test_anchoring_to_model_generated_block_is_a_hard_error():
    with pytest.raises(AnchoringToModelGeneratedBlockError):
        resolve_anchor("Figure: a recursive split-and-merge diagram.", [BLOCK_MODEL_GENERATED])


def test_citable_blocks_for_slides_excludes_model_generated():
    all_blocks = [BLOCK_A, BLOCK_B, BLOCK_MODEL_GENERATED]
    filtered = citable_blocks_for_slides(all_blocks, {1})
    assert BLOCK_MODEL_GENERATED not in filtered
    assert {block.block_id for block in filtered} == {BLOCK_A.block_id, BLOCK_B.block_id}


# --- build_and_validate_evidence: full pipeline, LLM mocked ---------------


def _fake_complete_result(draft: EvidenceCardDraft) -> CompleteResult:
    return CompleteResult(content="(fixture)", parsed=draft, model="fake-model", usage=None, llm_call_id=uuid.uuid4())


def test_hallucinated_quote_is_dropped_end_to_end(monkeypatch):
    """The adversarial fixture the module explicitly asked for: the model
    returns one real quote and one hallucinated one -- assert the real idea
    survives, the hallucinated one is dropped, and it's dropped for the
    right reason."""
    draft = EvidenceCardDraft(
        expected_ideas=[
            ExpectedIdeaDraft(
                idea="Merge sort is stable",
                quote="Merge sort is stable and runs in O(n log n) time in all cases.",
            ),
            ExpectedIdeaDraft(
                idea="Quick sort partitions around a pivot",
                quote="Quick sort uses a randomly chosen pivot to partition elements in place.",
            ),
        ],
        known_misconceptions=[MisconceptionDraft(code="merge_needs_extra_memory", text="Merge sort can be done in place with no extra memory.")],
        prerequisite_indices=[],
    )

    def fake_complete(**kwargs):
        return _fake_complete_result(draft)

    monkeypatch.setattr("slidevision.planbuilder.evidence.complete", fake_complete)

    objective_id = uuid.uuid4()
    result = build_and_validate_evidence(
        objective_id,
        "Student can explain merge sort's stability and running time",
        unit_slides=UNIT_SLIDES,
        citable_blocks=CITABLE_BLOCKS,
        prior_objectives=[],
    )

    assert len(result.anchored_ideas) == 1
    assert result.anchored_ideas[0].idea == "Merge sort is stable"
    assert result.anchored_ideas[0].block_id == "b_b"

    assert len(result.dropped_ideas) == 1
    assert result.dropped_ideas[0].idea == "Quick sort partitions around a pivot"
    assert result.dropped_ideas[0].reason == "no_match_above_threshold"

    assert result.low_confidence is True  # only 1 anchored idea, < 2
    assert result.zero_ideas is False


def test_zero_anchored_ideas_is_low_confidence_and_zero_ideas(monkeypatch):
    draft = EvidenceCardDraft(
        expected_ideas=[
            ExpectedIdeaDraft(idea="Nonexistent idea one", quote="This text was never on any slide about sorting."),
        ],
        known_misconceptions=[],
        prerequisite_indices=[],
    )
    monkeypatch.setattr("slidevision.planbuilder.evidence.complete", lambda **kwargs: _fake_complete_result(draft))

    result = build_and_validate_evidence(
        uuid.uuid4(), "Student can do something unsupported", unit_slides=UNIT_SLIDES, citable_blocks=CITABLE_BLOCKS, prior_objectives=[]
    )
    assert result.anchored_ideas == []
    assert result.low_confidence is True
    assert result.zero_ideas is True


def test_prerequisite_indices_resolve_to_objective_ids(monkeypatch):
    draft = EvidenceCardDraft(
        expected_ideas=[
            ExpectedIdeaDraft(idea="Merge sort is stable", quote="Merge sort is stable and runs in O(n log n) time in all cases."),
            ExpectedIdeaDraft(
                idea="Merge sort splits input recursively", quote="Merge sort splits the input in half recursively."
            ),
        ],
        known_misconceptions=[MisconceptionDraft(code="unstable_merge", text="Merge sort does not preserve equal elements' order.")],
        prerequisite_indices=[0, 2],  # 2 is out of range and must be silently ignored, not crash
    )
    monkeypatch.setattr("slidevision.planbuilder.evidence.complete", lambda **kwargs: _fake_complete_result(draft))

    prior_id = uuid.uuid4()
    prior_refs = [PriorObjectiveRef(index=0, objective_id=prior_id, statement="Student can define a sorting algorithm")]

    result = build_and_validate_evidence(
        uuid.uuid4(), "Student can explain merge sort", unit_slides=UNIT_SLIDES, citable_blocks=CITABLE_BLOCKS, prior_objectives=prior_refs
    )
    assert result.prerequisite_objective_ids == [prior_id]
    assert len(result.anchored_ideas) == 2
    assert result.low_confidence is False
