"""run_turn(session_id, message, idempotency_key) -> TutorTurn -- the turn
contract's single entry point (docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §2.5).
One call, one Postgres transaction: state in is exactly what load_state
reads from Postgres, state out is exactly what persist_turn (or
return_existing, for a duplicate idempotency_key) commits before this
function returns. No LangGraph interrupt(), no checkpointer -- the graph
completes and returns; the wait for the next student message lives in HTTP.
"""

from __future__ import annotations

import uuid

from slidevision.graph.build import get_graph
from slidevision.graph.result import TutorTurn
from slidevision.persistence.db import SessionLocal


def run_turn(session_id: uuid.UUID, message: str | None, idempotency_key: str) -> TutorTurn:
    db = SessionLocal()
    try:
        graph = get_graph()
        final_state = graph.invoke(
            {
                "db": db,
                "session_id": session_id,
                "message": message,
                "idempotency_key": idempotency_key,
            }
        )
        return final_state["result"]
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
