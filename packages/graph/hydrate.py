"""Converts persistence-layer session_objective_states rows into
tutor_core's pure ObjectiveState model. The one place packages/graph
translates between the two independent enum copies -- see
packages/persistence/enums.py's docstring for why they're independent
rather than one importing the other."""

from __future__ import annotations

from slidevision.persistence.models import SessionObjectiveState
from slidevision.tutor_core import ObjectiveState, ObjectiveStatus, PedagogicalAction


def to_tutor_core_state(row: SessionObjectiveState) -> ObjectiveState:
    return ObjectiveState(
        objective_id=str(row.objective_id),
        status=ObjectiveStatus(row.status.value),
        attempts=row.attempts,
        hint_level=row.hint_level,
        deepen_count=row.deepen_count,
        prereq_revisits=row.prereq_revisits,
        met_count=row.met_count,
        active_misconception_id=row.active_misconception_id,
        last_action=PedagogicalAction(row.last_action.value) if row.last_action else None,
    )
