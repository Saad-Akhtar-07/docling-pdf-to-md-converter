"""Offline unit tests for packages/planbuilder/segment.py: the hard
partition-completeness check and its one-retry-then-raise behavior.

No network, no DB: `complete()` is monkeypatched at the point segment.py
imports it, so these never touch packages/llm's transport layer.
"""

from __future__ import annotations

import uuid

import pytest

from slidevision.llm.client import CompleteResult
from slidevision.planbuilder.errors import PartitionError
from slidevision.planbuilder.segment import UnitDraft, UnitSegmentationResult, build_units, validate_partition
from slidevision.planbuilder.slides import SlideSummary


def _slide(slide_no: int) -> SlideSummary:
    return SlideSummary(slide_no=slide_no, title=f"Slide {slide_no}", citable_text=f"content for slide {slide_no}")


def _fake_result(units: list[UnitDraft]) -> CompleteResult:
    return CompleteResult(
        content="(fixture — not real model output)",
        parsed=UnitSegmentationResult(units=units),
        model="fake-model",
        usage=None,
        llm_call_id=uuid.uuid4(),
    )


# --- validate_partition: pure-function checks -------------------------------


def test_validate_partition_accepts_full_coverage():
    units = [
        UnitDraft(title="A", summary="s", slide_ids=[1, 2]),
        UnitDraft(title="B", summary="s", slide_ids=[3, 4, 5]),
    ]
    validate_partition(units, [1, 2, 3, 4, 5])  # must not raise


def test_validate_partition_detects_gaps_overlaps_and_unknown_slides():
    # slide 2 duplicated across units, slide 3/5 missing entirely, slide 9 doesn't exist
    units = [
        UnitDraft(title="A", summary="s", slide_ids=[1, 2]),
        UnitDraft(title="B", summary="s", slide_ids=[2, 4, 9]),
    ]
    with pytest.raises(PartitionError) as exc_info:
        validate_partition(units, [1, 2, 3, 4, 5])

    err = exc_info.value
    assert err.missing == [3, 5]
    assert err.duplicated == [2]
    assert err.unknown == [9]


# --- build_units: adversarial model output + the one-retry contract --------


def test_build_units_retries_once_and_recovers_from_overlapping_units(monkeypatch):
    slides = [_slide(n) for n in range(1, 6)]  # slides 1..5

    # Adversarial first response: slide 3 in both units, slide 5 missing entirely.
    overlapping = [
        UnitDraft(title="Intro", summary="s", slide_ids=[1, 2, 3]),
        UnitDraft(title="Core", summary="s", slide_ids=[3, 4]),
    ]
    corrected = [
        UnitDraft(title="Intro", summary="s", slide_ids=[1, 2, 3]),
        UnitDraft(title="Core", summary="s", slide_ids=[4, 5]),
    ]

    calls: list[list[dict]] = []

    def fake_complete(*, purpose, messages, schema, prompt_id, prompt_version, **_ignored):
        calls.append(messages)
        return _fake_result(overlapping if len(calls) == 1 else corrected)

    monkeypatch.setattr("slidevision.planbuilder.segment.complete", fake_complete)

    units, model = build_units(slides)

    assert model == "fake-model"
    assert len(calls) == 2  # exactly one retry
    assert {slide_id for unit in units for slide_id in unit.slide_ids} == {1, 2, 3, 4, 5}
    # the retry must tell the model what was wrong, not just repeat the ask
    retry_prompt = calls[1][-1]["content"]
    assert "invalid" in retry_prompt.lower()
    assert "3" in retry_prompt or "duplicate" in retry_prompt.lower()


def test_build_units_raises_partition_error_after_second_failure(monkeypatch):
    slides = [_slide(n) for n in range(1, 6)]
    always_incomplete = [UnitDraft(title="Only", summary="s", slide_ids=[1, 2])]  # 3, 4, 5 always missing

    calls: list[list[dict]] = []

    def fake_complete(*, purpose, messages, schema, prompt_id, prompt_version, **_ignored):
        calls.append(messages)
        return _fake_result(always_incomplete)

    monkeypatch.setattr("slidevision.planbuilder.segment.complete", fake_complete)

    with pytest.raises(PartitionError) as exc_info:
        build_units(slides)

    assert len(calls) == 2  # tried once, retried once, then gave up -- no more
    assert exc_info.value.missing == [3, 4, 5]
