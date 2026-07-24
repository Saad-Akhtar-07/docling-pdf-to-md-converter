"""Unit tests for the Module 4 policy stub (packages/tutor_core/policy.py).

A pure function -- no DB, no fixtures beyond plain dicts. Encodes the
stub's entire contract: accept any answer unconditionally, advance
linearly through plan order, and degrade gracefully once every objective
is resolved.
"""

from __future__ import annotations

from slidevision.tutor_core import ObjectiveState, ObjectiveStatus, PedagogicalAction, select_action


def _unseen_states(ids: list[str]) -> dict[str, ObjectiveState]:
    return {oid: ObjectiveState(objective_id=oid) for oid in ids}


def test_first_turn_probes_first_objective():
    result = select_action(
        objective_order=["a", "b", "c"],
        objective_states=_unseen_states(["a", "b", "c"]),
        probing_objective_id=None,
        has_answer=False,
    )
    assert result.action == PedagogicalAction.PROBE
    assert result.objective_id == "a"
    assert result.objective_states["a"].status == ObjectiveStatus.PROBING
    assert result.session_complete is False


def test_answer_resolves_current_and_advances():
    states = _unseen_states(["a", "b", "c"])
    states["a"].status = ObjectiveStatus.PROBING

    result = select_action(
        objective_order=["a", "b", "c"],
        objective_states=states,
        probing_objective_id="a",
        has_answer=True,
    )

    assert result.objective_states["a"].status == ObjectiveStatus.RESOLVED
    assert result.objective_states["a"].attempts == 1
    assert result.objective_states["a"].met_count == 1
    assert result.objective_id == "b"
    assert result.objective_states["b"].status == ObjectiveStatus.PROBING
    assert result.session_complete is False


def test_any_answer_is_accepted_regardless_of_content():
    """The stub's whole point: it never judges the answer, it just accepts it."""
    states = _unseen_states(["a"])
    states["a"].status = ObjectiveStatus.PROBING

    result = select_action(objective_order=["a"], objective_states=states, probing_objective_id="a", has_answer=True)

    assert result.objective_states["a"].status == ObjectiveStatus.RESOLVED
    assert result.objective_id is None
    assert result.session_complete is True


def test_session_complete_once_all_resolved():
    states = {
        "a": ObjectiveState(objective_id="a", status=ObjectiveStatus.RESOLVED),
        "b": ObjectiveState(objective_id="b", status=ObjectiveStatus.RESOLVED),
    }
    result = select_action(objective_order=["a", "b"], objective_states=states, probing_objective_id=None, has_answer=False)
    assert result.objective_id is None
    assert result.session_complete is True
    assert result.action == PedagogicalAction.PROBE  # stub always returns PROBE


def test_pure_function_does_not_mutate_input_states():
    states = _unseen_states(["a", "b"])
    states["a"].status = ObjectiveStatus.PROBING
    original_status = states["a"].status

    select_action(objective_order=["a", "b"], objective_states=states, probing_objective_id="a", has_answer=True)

    assert states["a"].status == original_status  # caller's dict/models untouched


def test_extra_answer_after_completion_is_harmless():
    states = {"a": ObjectiveState(objective_id="a", status=ObjectiveStatus.RESOLVED)}
    result = select_action(objective_order=["a"], objective_states=states, probing_objective_id=None, has_answer=True)
    assert result.objective_id is None
    assert result.session_complete is True


def test_empty_plan_completes_immediately():
    result = select_action(objective_order=[], objective_states={}, probing_objective_id=None, has_answer=False)
    assert result.objective_id is None
    assert result.session_complete is True
