"""select_action(): the Module 4 stub for LangGraph node 7
(docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §2.7).

This is NOT the real policy (§2.8's table) -- that is Module 6. Its entire
contract here: accept the previous turn's answer unconditionally (whatever
objective was PROBING becomes RESOLVED, no matter what was said) and PROBE
the next UNSEEN objective in plan order. A pure function -- no I/O, no
randomness, fully deterministic given its inputs (CLAUDE.md invariant #5,
turn contract rule 3) -- so it exists purely to prove the state plumbing
while assessment/policy don't exist yet.
"""

from __future__ import annotations

from pydantic import BaseModel

from slidevision.tutor_core.models import ObjectiveState, ObjectiveStatus, PedagogicalAction


class SelectActionResult(BaseModel):
    action: PedagogicalAction
    objective_id: str | None  # objective targeted this turn; None once every objective is resolved
    objective_states: dict[str, ObjectiveState]
    session_complete: bool


def select_action(
    *,
    objective_order: list[str],
    objective_states: dict[str, ObjectiveState],
    probing_objective_id: str | None,
    has_answer: bool,
) -> SelectActionResult:
    """`objective_order` is the plan's curriculum order (all objective ids,
    as strings). `objective_states` must have an entry for every id in
    `objective_order`. `probing_objective_id` is whichever objective the
    session most recently asked about (session.current_objective_id);
    `has_answer` is True whenever this turn carries a student message to
    accept as resolving it (False only for the very first turn of a
    session, which has no answer yet to accept)."""
    states = {oid: state.model_copy(deep=True) for oid, state in objective_states.items()}

    if has_answer and probing_objective_id is not None:
        current = states[probing_objective_id]
        states[probing_objective_id] = current.model_copy(
            update={
                "status": ObjectiveStatus.RESOLVED,
                "attempts": current.attempts + 1,
                "met_count": current.met_count + 1,
                "last_action": PedagogicalAction.PROBE,
            }
        )

    next_id = next(
        (oid for oid in objective_order if states[oid].status == ObjectiveStatus.UNSEEN),
        None,
    )
    if next_id is None:
        return SelectActionResult(
            action=PedagogicalAction.PROBE,
            objective_id=None,
            objective_states=states,
            session_complete=True,
        )

    states[next_id] = states[next_id].model_copy(update={"status": ObjectiveStatus.PROBING})
    return SelectActionResult(
        action=PedagogicalAction.PROBE,
        objective_id=next_id,
        objective_states=states,
        session_complete=False,
    )
