"""Integration test for packages/persistence's schema.

Requires a real Postgres reachable at DATABASE_URL (docker compose up -d)
with migrations applied (alembic upgrade head). Creates one row in every
table defined in docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §2.10 and asserts
FK cascade/restrict behavior matches the ON DELETE choices documented at the
top of packages/persistence/models.py.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from slidevision.persistence.db import SessionLocal, engine
from slidevision.persistence.enums import (
    DocumentStatus,
    Intent,
    ObjectiveStatus,
    PedagogicalAction,
    PlanStatus,
    Provenance,
    SessionStatus,
)
from slidevision.persistence.models import (
    Document,
    DocumentBlock,
    LearningObjective,
    LearningPlan,
    LearningUnit,
    LlmCall,
    ObjectiveExpectedIdea,
    ObjectiveMisconception,
    Session as SessionModel,
    SessionObjectiveState,
    SessionReport,
    Turn,
    TurnEvent,
)
from slidevision.persistence.repositories import DocumentRepository, PlanRepository, SessionRepository


def _new_document(documents: DocumentRepository, **overrides) -> Document:
    """documents.create() now requires content_hash/storage_uri (added by the
    Document Registry module for upload idempotency and file location) that
    these schema-level tests don't otherwise care about — fill in throwaway
    defaults so each call site doesn't have to.
    """
    defaults = dict(
        title="Deck",
        source_filename="d.pdf",
        mime="application/pdf",
        content_hash=uuid.uuid4().hex,
        storage_uri="data/uploads/test/d.pdf",
    )
    defaults.update(overrides)
    return documents.create(**defaults)


@pytest.fixture
def db() -> Session:
    """A session bound to a connection-level transaction that is always
    rolled back at teardown, so tests never leave rows behind in the real
    database no matter how many times `session.commit()` is called inside
    them (SQLAlchemy 2.0's `join_transaction_mode="create_savepoint"` turns
    each inner commit into a SAVEPOINT release instead of a real COMMIT).
    """
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()


def _seed_full_graph(db: Session):
    """Create one row in every §2.10 table and return the key objects."""
    documents = DocumentRepository(db)
    plans = PlanRepository(db)
    sessions = SessionRepository(db)

    document = _new_document(
        documents,
        title="Week 15 IR Optimization",
        source_filename="week15.pptx",
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        status=DocumentStatus.READY,
    )
    block = documents.add_block(
        block_id="b" * 64,
        document_id=document.id,
        slide_no=1,
        order_index=0,
        text="Shuffle sorts intermediate keys before reduce.",
        provenance=Provenance.VERBATIM,
        producer="pymupdf4llm",
    )

    plan = plans.create_plan(document_id=document.id, version=1, status=PlanStatus.DRAFT)
    unit = plans.add_unit(plan_id=plan.id, title="MapReduce internals", order_index=0, slide_ids=[1, 2])
    objective = plans.add_objective(unit_id=unit.id, statement="Explain the shuffle phase.", order_index=0)
    idea = plans.add_expected_idea(
        objective_id=objective.id,
        idea="Shuffle groups keys before reduce runs.",
        block_id=block.id,
        char_start=0,
        char_end=10,
    )
    misconception = plans.add_misconception(
        objective_id=objective.id, code="M01", text="Believes shuffle produces the final answer."
    )

    session = sessions.create_session(document_id=document.id, plan_id=plan.id)
    state = sessions.upsert_objective_state(
        session_id=session.id, objective_id=objective.id, status=ObjectiveStatus.PROBING
    )
    turn = sessions.add_turn(
        session_id=session.id,
        index=0,
        idempotency_key=str(uuid.uuid4()),
        student_message="Shuffle produces the final answer.",
        intent=Intent.ANSWER,
        action=PedagogicalAction.HINT,
        tutor_message="Not quite — what happens after shuffle groups the keys?",
        objective_id=objective.id,
    )
    event = sessions.add_turn_event(
        session_id=session.id, turn_id=turn.id, event_type="ASSESSMENT", payload={"verdict": "incorrect"}
    )
    llm_call = sessions.record_llm_call(
        session_id=session.id,
        turn_id=turn.id,
        purpose="assessment",
        provider="openai",
        model="gpt-4o",
        prompt_id="assess_v1",
        prompt_version="1",
        input_tokens=100,
        output_tokens=20,
    )
    report = sessions.create_report(session_id=session.id, summary="Resolved 1 objective.")

    db.commit()
    return {
        "document": document,
        "block": block,
        "plan": plan,
        "unit": unit,
        "objective": objective,
        "idea": idea,
        "misconception": misconception,
        "session": session,
        "state": state,
        "turn": turn,
        "event": event,
        "llm_call": llm_call,
        "report": report,
    }


def test_one_row_per_table(db: Session):
    seeded = _seed_full_graph(db)

    assert db.get(Document, seeded["document"].id) is not None
    assert db.get(DocumentBlock, seeded["block"].id) is not None
    assert db.get(LearningPlan, seeded["plan"].id) is not None
    assert db.get(LearningUnit, seeded["unit"].id) is not None
    assert db.get(LearningObjective, seeded["objective"].id) is not None
    assert db.get(ObjectiveExpectedIdea, seeded["idea"].id) is not None
    assert db.get(ObjectiveMisconception, seeded["misconception"].id) is not None
    assert db.get(SessionModel, seeded["session"].id) is not None
    assert (
        db.get(SessionObjectiveState, (seeded["session"].id, seeded["objective"].id)) is not None
    )
    assert db.get(Turn, seeded["turn"].id) is not None
    assert db.get(TurnEvent, seeded["event"].id) is not None
    assert db.get(LlmCall, seeded["llm_call"].id) is not None
    assert db.get(SessionReport, seeded["report"].id) is not None


def test_learning_plans_unique_document_version(db: Session):
    documents = DocumentRepository(db)
    plans = PlanRepository(db)
    document = _new_document(documents)
    plans.create_plan(document_id=document.id, version=1)
    db.commit()

    with pytest.raises(IntegrityError):
        plans.create_plan(document_id=document.id, version=1)
    db.rollback()


def test_turns_idempotency_key_unique(db: Session):
    documents = DocumentRepository(db)
    plans = PlanRepository(db)
    sessions = SessionRepository(db)
    document = _new_document(documents)
    plan = plans.create_plan(document_id=document.id, version=1)
    session = sessions.create_session(document_id=document.id, plan_id=plan.id)
    key = str(uuid.uuid4())
    sessions.add_turn(session_id=session.id, index=0, idempotency_key=key, student_message="hi")
    db.commit()

    with pytest.raises(IntegrityError):
        sessions.add_turn(session_id=session.id, index=1, idempotency_key=key, student_message="hi again")
    db.rollback()


def test_document_blocks_cascade_on_document_delete(db: Session):
    documents = DocumentRepository(db)
    document = _new_document(documents)
    block = documents.add_block(
        block_id="c" * 64,
        document_id=document.id,
        slide_no=1,
        order_index=0,
        text="text",
        provenance=Provenance.VERBATIM,
    )
    db.commit()

    db.delete(document)
    db.commit()

    assert db.get(DocumentBlock, block.id) is None


def test_learning_plans_document_restrict_on_delete(db: Session):
    documents = DocumentRepository(db)
    plans = PlanRepository(db)
    document = _new_document(documents)
    plans.create_plan(document_id=document.id, version=1)
    db.commit()

    db.delete(document)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_learning_units_cascade_on_plan_delete(db: Session):
    documents = DocumentRepository(db)
    plans = PlanRepository(db)
    document = _new_document(documents)
    plan = plans.create_plan(document_id=document.id, version=1)
    unit = plans.add_unit(plan_id=plan.id, title="Unit", order_index=0)
    db.commit()

    db.delete(plan)
    db.commit()

    assert db.get(LearningUnit, unit.id) is None


def test_sessions_cascade_turns_and_events_on_session_delete(db: Session):
    documents = DocumentRepository(db)
    plans = PlanRepository(db)
    sessions = SessionRepository(db)
    document = _new_document(documents)
    plan = plans.create_plan(document_id=document.id, version=1)
    session = sessions.create_session(document_id=document.id, plan_id=plan.id)
    turn = sessions.add_turn(
        session_id=session.id, index=0, idempotency_key=str(uuid.uuid4()), student_message="hi"
    )
    event = sessions.add_turn_event(session_id=session.id, turn_id=turn.id, event_type="X", payload={})
    db.commit()

    db.delete(session)
    db.commit()

    assert db.get(Turn, turn.id) is None
    assert db.get(TurnEvent, event.id) is None


def test_objective_expected_idea_restricts_block_delete(db: Session):
    documents = DocumentRepository(db)
    plans = PlanRepository(db)
    document = _new_document(documents)
    block = documents.add_block(
        block_id="d" * 64,
        document_id=document.id,
        slide_no=1,
        order_index=0,
        text="text",
        provenance=Provenance.VERBATIM,
    )
    plan = plans.create_plan(document_id=document.id, version=1)
    unit = plans.add_unit(plan_id=plan.id, title="Unit", order_index=0)
    objective = plans.add_objective(unit_id=unit.id, statement="Statement", order_index=0)
    plans.add_expected_idea(objective_id=objective.id, idea="idea", block_id=block.id, char_start=0, char_end=4)
    db.commit()

    db.delete(block)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
