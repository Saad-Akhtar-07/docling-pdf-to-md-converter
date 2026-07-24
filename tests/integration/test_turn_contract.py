"""Integration tests for Module 4's turn contract (docs/…§2.5) and session
runtime skeleton: POST /sessions, POST /sessions/{id}/turns, GET
/sessions/{id}, GET /sessions/{id}/turns.

Requires a real Postgres reachable at DATABASE_URL (docker compose up -d)
with migrations applied -- see tests/integration/conftest.py. Seeds an
already-APPROVED plan directly via the repositories (bypassing Module 2's
LLM plan-build and Module 3's review flow, both out of scope here) with
three objectives and no expected ideas -- Module 4's session loop never
reads expected_ideas/misconceptions.
"""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from slidevision.graph.run_turn import run_turn
from slidevision.persistence.db import SessionLocal
from slidevision.persistence.enums import ObjectiveStatus as StoredObjectiveStatus
from slidevision.persistence.enums import PlanStatus
from slidevision.persistence.models import Document, LearningPlan
from slidevision.persistence.models import Session as SessionModel
from slidevision.persistence.models import SessionObjectiveState, Turn
from slidevision.persistence.repositories import DocumentRepository, PlanRepository, SessionRepository
from slidevision.tutor_core import ObjectiveState, ObjectiveStatus, select_action


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seeded_plan():
    """An already-APPROVED plan with three bare objectives (no expected
    ideas/misconceptions -- Module 4 doesn't touch either), plus a place
    for each test to register session ids it creates so they get cleaned
    up alongside the plan/document."""
    session = SessionLocal()
    documents = DocumentRepository(session)
    plans = PlanRepository(session)
    try:
        document = documents.create(
            title="Turn Contract Fixture",
            source_filename="turns.pdf",
            mime="application/pdf",
            content_hash=uuid.uuid4().hex,
            storage_uri="data/uploads/test/turns.pdf",
        )
        plan = plans.create_plan(document_id=document.id, version=1, status=PlanStatus.APPROVED)
        unit = plans.add_unit(plan_id=plan.id, title="Unit 1", order_index=0, slide_ids=[1])
        objective_ids = [
            plans.add_objective(unit_id=unit.id, statement=f"Objective {i}", order_index=i).id
            for i in range(3)
        ]
        session.commit()
        ids = {"document_id": document.id, "plan_id": plan.id, "objective_ids": objective_ids}
    finally:
        session.close()

    created_session_ids: list[uuid.UUID] = []
    yield ids, created_session_ids

    cleanup = SessionLocal()
    try:
        for session_id in created_session_ids:
            db_session = cleanup.get(SessionModel, session_id)
            if db_session is not None:
                cleanup.delete(db_session)
                cleanup.commit()
        plan = cleanup.get(LearningPlan, ids["plan_id"])
        if plan is not None:
            cleanup.delete(plan)
            cleanup.commit()
        document = cleanup.get(Document, ids["document_id"])
        if document is not None:
            cleanup.delete(document)
            cleanup.commit()
    finally:
        cleanup.close()


def _seed_session(ids: dict) -> uuid.UUID:
    """Creates a session + UNSEEN objective_states directly via the
    repositories, for tests that drive run_turn() without going through
    POST /sessions."""
    session = SessionLocal()
    try:
        session_repo = SessionRepository(session)
        db_session = session_repo.create_session(document_id=ids["document_id"], plan_id=ids["plan_id"])
        for objective_id in ids["objective_ids"]:
            session_repo.upsert_objective_state(
                session_id=db_session.id, objective_id=objective_id, status=StoredObjectiveStatus.UNSEEN
            )
        session.commit()
        return db_session.id
    finally:
        session.close()


def _parse_sse_turn(response_text: str) -> dict:
    for line in response_text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: "):])
    raise AssertionError(f"no SSE data line found in: {response_text!r}")


# --- API-level: full session walk, duplicate idempotency ------------------


def test_session_walks_all_objectives_in_order_and_completes(client, seeded_plan):
    ids, created = seeded_plan

    create_response = client.post(
        "/sessions", json={"document_id": str(ids["document_id"]), "plan_id": str(ids["plan_id"])}
    )
    assert create_response.status_code == 201
    body = create_response.json()
    session_id = body["session"]["id"]
    created.append(uuid.UUID(session_id))

    first_turn = body["turn"]
    assert first_turn["turn_index"] == 0
    assert first_turn["action"] == "probe"
    assert first_turn["objective_id"] == str(ids["objective_ids"][0])
    assert first_turn["student_message"] is None
    assert first_turn["session_complete"] is False
    assert first_turn["progress"] == {"resolved": 0, "deferred": 0, "total": 3}

    expected_next_objective = [ids["objective_ids"][1], ids["objective_ids"][2], None]
    for turn_number, expected_objective in enumerate(expected_next_objective, start=1):
        response = client.post(
            f"/sessions/{session_id}/turns",
            json={"message": f"my answer #{turn_number}", "idempotency_key": f"turn-{turn_number}"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        turn = _parse_sse_turn(response.text)
        assert turn["turn_index"] == turn_number
        assert turn["objective_id"] == (str(expected_objective) if expected_objective else None)
        assert turn["session_complete"] == (expected_objective is None)

    final_session = client.get(f"/sessions/{session_id}").json()
    assert final_session["status"] == "completed"
    assert final_session["progress"] == {"resolved": 3, "deferred": 0, "total": 3}
    assert all(o["status"] == "resolved" for o in final_session["objectives"])

    history = client.get(f"/sessions/{session_id}/turns").json()
    assert [t["index"] for t in history] == [0, 1, 2, 3]
    assert history[1]["student_message"] == "my answer #1"


def test_duplicate_idempotency_key_returns_stored_turn_without_re_executing(client, seeded_plan):
    ids, created = seeded_plan
    create_response = client.post(
        "/sessions", json={"document_id": str(ids["document_id"]), "plan_id": str(ids["plan_id"])}
    )
    session_id = create_response.json()["session"]["id"]
    created.append(uuid.UUID(session_id))

    key = "duplicate-key"
    first = _parse_sse_turn(
        client.post(f"/sessions/{session_id}/turns", json={"message": "answer", "idempotency_key": key}).text
    )
    second = _parse_sse_turn(
        client.post(f"/sessions/{session_id}/turns", json={"message": "a completely different message", "idempotency_key": key}).text
    )

    assert first["turn_id"] == second["turn_id"]
    assert first["tutor_message"] == second["tutor_message"]
    assert first["turn_index"] == second["turn_index"] == 1

    db = SessionLocal()
    try:
        matching_turns = (
            db.query(Turn).filter(Turn.session_id == uuid.UUID(session_id), Turn.idempotency_key == key).all()
        )
        assert len(matching_turns) == 1
        assert matching_turns[0].student_message == "answer"  # the second (different) message was never applied

        db_session = db.get(SessionModel, uuid.UUID(session_id))
        assert db_session.turn_count == 2  # turn 0 (init) + turn 1 -- not incremented twice
    finally:
        db.close()


def test_unknown_session_returns_404(client):
    response = client.post(
        f"/sessions/{uuid.uuid4()}/turns", json={"message": "hi", "idempotency_key": "x"}
    )
    assert response.status_code == 404


# --- Turn contract properties, driven directly through run_turn() ---------


def test_state_in_from_db_state_out_persisted_matches_pure_policy(seeded_plan):
    """Turn contract rules 1 & 2 (§2.5): what select_action computes from
    must be exactly what's in Postgres, and what gets persisted afterward
    must be exactly what select_action returned. Seeds a non-default state
    directly in the DB (not through the API, so "state in" is known
    precisely), calls run_turn, then recomputes the expected transition
    independently via tutor_core.select_action and asserts the DB row
    matches it exactly."""
    ids, created = seeded_plan
    objective_ids = ids["objective_ids"]

    db = SessionLocal()
    try:
        session_repo = SessionRepository(db)
        db_session = session_repo.create_session(document_id=ids["document_id"], plan_id=ids["plan_id"])
        session_repo.upsert_objective_state(
            session_id=db_session.id, objective_id=objective_ids[0], status=StoredObjectiveStatus.RESOLVED, attempts=1, met_count=1
        )
        session_repo.upsert_objective_state(
            session_id=db_session.id, objective_id=objective_ids[1], status=StoredObjectiveStatus.PROBING, attempts=2, hint_level=1
        )
        session_repo.upsert_objective_state(
            session_id=db_session.id, objective_id=objective_ids[2], status=StoredObjectiveStatus.UNSEEN
        )
        db_session.current_objective_id = objective_ids[1]
        db_session.turn_count = 1
        db.commit()
        session_id = db_session.id
    finally:
        db.close()
    created.append(session_id)

    turn = run_turn(session_id, message="an answer", idempotency_key="prop-test-1")

    # Recompute independently, from the exact same "state in", what the
    # pure policy should have produced.
    order = [str(oid) for oid in objective_ids]
    loaded_states = {
        str(objective_ids[0]): ObjectiveState(objective_id=str(objective_ids[0]), status=ObjectiveStatus.RESOLVED, attempts=1, met_count=1),
        str(objective_ids[1]): ObjectiveState(objective_id=str(objective_ids[1]), status=ObjectiveStatus.PROBING, attempts=2, hint_level=1),
        str(objective_ids[2]): ObjectiveState(objective_id=str(objective_ids[2])),
    }
    expected = select_action(
        objective_order=order, objective_states=loaded_states, probing_objective_id=str(objective_ids[1]), has_answer=True
    )

    assert turn.turn_index == 1
    assert turn.objective_id == objective_ids[2]
    assert turn.action.value == expected.action.value

    db = SessionLocal()
    try:
        db_session = db.get(SessionModel, session_id)
        assert db_session.turn_count == 2
        assert db_session.current_objective_id == objective_ids[2]

        for oid_str, expected_state in expected.objective_states.items():
            row = db.get(SessionObjectiveState, (session_id, uuid.UUID(oid_str)))
            assert row.status.value == expected_state.status.value
            assert row.attempts == expected_state.attempts
            assert row.hint_level == expected_state.hint_level
            assert row.met_count == expected_state.met_count
    finally:
        db.close()


def test_crash_before_commit_leaves_no_partial_state_and_retry_succeeds(seeded_plan, monkeypatch):
    """Simulates "kill the process mid-turn, restart, continue correctly"
    without literally spawning/killing uvicorn: since nothing is written to
    Postgres until persist_turn's final commit (no LangGraph checkpointer,
    no in-memory session state -- CLAUDE.md invariants #1/#3), a crash at
    any point before that commit must leave the session exactly as it was,
    and a retry with the same idempotency_key must then run the turn fresh
    rather than see a half-written one."""
    ids, created = seeded_plan
    session_id = _seed_session(ids)
    created.append(session_id)

    run_turn(session_id, message=None, idempotency_key=f"session:{session_id}:init")

    before = SessionLocal()
    try:
        before_session = before.get(SessionModel, session_id)
        before_turn_count = before_session.turn_count
        before_current_objective = before_session.current_objective_id
    finally:
        before.close()

    original_add_turn = SessionRepository.add_turn
    call_count = {"n": 0}

    def _flaky_add_turn(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated crash mid-turn, before persist_turn's commit")
        return original_add_turn(self, *args, **kwargs)

    monkeypatch.setattr(SessionRepository, "add_turn", _flaky_add_turn)

    key = "crash-then-retry"
    with pytest.raises(RuntimeError):
        run_turn(session_id, message="first attempt", idempotency_key=key)

    mid_crash = SessionLocal()
    try:
        mid_session = mid_crash.get(SessionModel, session_id)
        assert mid_session.turn_count == before_turn_count
        assert mid_session.current_objective_id == before_current_objective
        assert (
            mid_crash.query(Turn).filter(Turn.session_id == session_id, Turn.idempotency_key == key).count() == 0
        )
    finally:
        mid_crash.close()

    # "Restart": retry the exact same call. Not treated as a duplicate --
    # nothing with this idempotency_key was ever actually persisted -- so
    # it runs the turn fresh, this time succeeding.
    turn = run_turn(session_id, message="first attempt", idempotency_key=key)
    assert turn.turn_index == before_turn_count

    after = SessionLocal()
    try:
        after_session = after.get(SessionModel, session_id)
        assert after_session.turn_count == before_turn_count + 1
        assert after.query(Turn).filter(Turn.session_id == session_id, Turn.idempotency_key == key).count() == 1
    finally:
        after.close()


def test_concurrent_turns_on_same_session_do_not_corrupt_state(seeded_plan):
    """Two concurrent run_turn() calls against the SAME session, each a
    genuinely distinct (non-duplicate) turn -- proves the row lock
    load_state takes (`SELECT ... FOR UPDATE`) serializes them instead of
    racing on session.turn_count / current_objective_id. A lost update
    would show up here as a short turn_count or two turns sharing an
    index."""
    ids, created = seeded_plan
    session_id = _seed_session(ids)
    created.append(session_id)

    run_turn(session_id, message=None, idempotency_key=f"session:{session_id}:init")

    results = []
    errors = []

    def _post(key: str) -> None:
        try:
            results.append(run_turn(session_id, message=f"answer-{key}", idempotency_key=key))
        except Exception as exc:  # pragma: no cover - asserted via `errors` below
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(_post, "concurrent-a"), executor.submit(_post, "concurrent-b")]
        for future in futures:
            future.result()

    assert not errors
    assert len(results) == 2
    assert sorted(r.turn_index for r in results) == [1, 2]  # no lost update, no duplicate index

    db = SessionLocal()
    try:
        db_session = db.get(SessionModel, session_id)
        assert db_session.turn_count == 3  # init + two concurrent turns, none lost
        assert db.query(Turn).filter(Turn.session_id == session_id).count() == 3
    finally:
        db.close()
