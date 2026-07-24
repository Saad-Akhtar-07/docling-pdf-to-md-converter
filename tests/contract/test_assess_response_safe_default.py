"""§2.13 / Module 5 acceptance: "zero unhandled StructuredOutputError across
a 100-turn scripted run." Offline (respx-mocked, no real gateway traffic --
see tests/contract/conftest.py), so this runs in CI without an API key.

Scripts 100 assess_response calls against a gateway that behaves the way
OpenCode Zen's reasoning models are documented to (docs/BACKLOG.md, "packages/llm
module": ~10-20% empty/malformed content): roughly 15% of turns get
malformed JSON on BOTH the primary and repair-retry attempt (forcing
structured.py to raise StructuredOutputError all the way up), the rest
succeed on the first attempt. `call_assess_llm` must swallow every one of
those failures into the safe default (verdict=confused) and never let the
exception reach the caller -- the turn must never crash on bad JSON.
"""

from __future__ import annotations

import json

import httpx
import respx

from slidevision.graph.assessment import SAFE_DEFAULT_ASSESSMENT, build_messages, call_assess_llm
from slidevision.llm import config
from slidevision.tutor_core import EvidenceCard, EvidenceIdea, EvidenceMisconception

ENDPOINT = config.chat_completions_url()

_CARD = EvidenceCard(
    objective_id="obj_1",
    expected_ideas=[EvidenceIdea(id="idea_1", idea="mapper outputs carry intermediate keys")],
    known_misconceptions=[EvidenceMisconception(code="shuffle_is_reduce", text="shuffle performs the reduction itself")],
)

_VALID_ASSESSMENT_BODY = {
    "verdict": "partial",
    "objective_met": False,
    "reasoning_depth": "adequate",
    "matched_idea_ids": ["idea_1"],
    "missing_idea_ids": [],
    "misconception_id": None,
    "misconception_novel_text": None,
    "prerequisite_gap_objective_id": None,
    "evidence_quote": None,
}


def _valid_response() -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": json.dumps(_VALID_ASSESSMENT_BODY)}}]}
    )


def _malformed_response() -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": "not valid json at all"}}]})


def _messages_for_turn(i: int) -> list[dict]:
    answer = ["idk", "I think it groups keys", "totally wrong guess", ""][i % 4]
    return build_messages(
        objective_statement="Student can explain the shuffle phase",
        card=_CARD,
        source_text="(source text)",
        question="Why does shuffle group by key?",
        answer=answer,
        recent_turns_text="(no prior turns)",
        objective_state_summary="status=probing, attempts=1",
    )


@respx.mock
def test_100_turn_scripted_run_never_raises_structured_output_error(logged_calls):
    fail_turn_indices = set(range(0, 100, 7))  # 15 of the 100 turns double-fail
    responses: list[httpx.Response] = []
    for i in range(100):
        if i in fail_turn_indices:
            responses.append(_malformed_response())  # primary attempt
            responses.append(_malformed_response())  # repair retry
        else:
            responses.append(_valid_response())

    respx.post(ENDPOINT).mock(side_effect=responses)

    used_safe_default_count = 0
    for i in range(100):
        messages = _messages_for_turn(i)
        # The only assertion that matters: this never raises.
        assessment, used_safe_default = call_assess_llm(messages)

        assert assessment is not None
        if i in fail_turn_indices:
            assert used_safe_default is True
            assert assessment == SAFE_DEFAULT_ASSESSMENT
            used_safe_default_count += 1
        else:
            assert used_safe_default is False
            assert assessment.verdict == "partial"

    assert used_safe_default_count == len(fail_turn_indices)
