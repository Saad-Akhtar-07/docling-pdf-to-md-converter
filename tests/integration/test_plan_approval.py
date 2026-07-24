"""Integration tests for Module 3's plan-review API: PATCH/DELETE
/objectives/{id}, POST /plans/{id}/approve, and the plan_edits audit trail.

Requires a real Postgres reachable at DATABASE_URL (docker compose up -d)
with migrations applied — see tests/integration/conftest.py. Seeds a draft
plan directly via the repositories (bypassing Module 2's LLM plan-build job,
out of scope here) with one unit/objective/expected-idea/misconception
anchored to a real document_block, then exercises the review API through
FastAPI's TestClient. FastAPI's TestClient runs the whole request
synchronously, so no polling is needed.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from slidevision.persistence.db import SessionLocal
from slidevision.persistence.enums import PlanStatus, Provenance
from slidevision.persistence.models import (
    Document,
    LearningObjective,
    LearningPlan,
    ObjectiveExpectedIdea,
    ObjectiveMisconception,
)
from slidevision.persistence.repositories import DocumentRepository, PlanRepository


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seeded_plan():
    """A draft plan with one unit/objective/expected idea/misconception,
    created directly via the repositories and committed for real (the API's
    own SessionLocal() must see it) — same real-database cleanup pattern as
    tests/integration/test_documents_api.py's `created_documents` fixture."""
    session = SessionLocal()
    documents = DocumentRepository(session)
    plans = PlanRepository(session)
    try:
        document = documents.create(
            title="Review Fixture",
            source_filename="review.pdf",
            mime="application/pdf",
            content_hash=uuid.uuid4().hex,
            storage_uri="data/uploads/test/review.pdf",
        )
        block = documents.add_block(
            block_id=uuid.uuid4().hex,
            document_id=document.id,
            slide_no=1,
            order_index=0,
            text="Shuffle groups keys before reduce runs.",
            provenance=Provenance.VERBATIM,
        )
        plan = plans.create_plan(document_id=document.id, version=1, status=PlanStatus.DRAFT)
        unit = plans.add_unit(plan_id=plan.id, title="Unit 1", order_index=0, slide_ids=[1])
        objective = plans.add_objective(unit_id=unit.id, statement="Explain shuffle.", order_index=0)
        idea = plans.add_expected_idea(
            objective_id=objective.id, idea="Shuffle groups keys.", block_id=block.id, char_start=0, char_end=8
        )
        misconception = plans.add_misconception(
            objective_id=objective.id, code="M01", text="Wrong belief about shuffle."
        )
        session.commit()
        ids = {
            "document_id": document.id,
            "plan_id": plan.id,
            "unit_id": unit.id,
            "objective_id": objective.id,
            "idea_id": idea.id,
            "misconception_id": misconception.id,
            "block_id": block.id,
        }
    finally:
        session.close()

    yield ids

    session = SessionLocal()
    try:
        # plan_edits cascades from learning_plans (ON DELETE CASCADE); the
        # plan itself must go before the document, which the plan
        # RESTRICTs deletion of.
        plan = session.get(LearningPlan, ids["plan_id"])
        if plan is not None:
            session.delete(plan)
            session.commit()
        document = session.get(Document, ids["document_id"])
        if document is not None:
            session.delete(document)
            session.commit()
    finally:
        session.close()


def test_edit_objective(client, seeded_plan):
    objective_id = str(seeded_plan["objective_id"])
    response = client.patch(f"/objectives/{objective_id}", json={"statement": "Explain the shuffle phase in detail."})
    assert response.status_code == 200
    body = response.json()
    assert body["statement"] == "Explain the shuffle phase in detail."
    assert body["reviewed"] is False


def test_reviewed_flag_persists(client, seeded_plan):
    objective_id = str(seeded_plan["objective_id"])
    response = client.patch(f"/objectives/{objective_id}", json={"reviewed": True})
    assert response.status_code == 200
    assert response.json()["reviewed"] is True


def test_expected_ideas_add_edit_remove(client, seeded_plan):
    objective_id = str(seeded_plan["objective_id"])
    kept_idea_id = str(seeded_plan["idea_id"])
    block_id = seeded_plan["block_id"]

    response = client.patch(
        f"/objectives/{objective_id}",
        json={
            "expected_ideas": [
                # edit the existing idea in place (also covers re-anchoring:
                # block_id/char_start/char_end can all change here)
                {"id": kept_idea_id, "idea": "Shuffle groups keys (edited).", "block_id": block_id, "char_start": 0, "char_end": 8},
                # add a brand-new idea (no id)
                {"idea": "A second anchored idea.", "block_id": block_id, "char_start": 9, "char_end": 15},
            ]
        },
    )
    assert response.status_code == 200
    ideas = response.json()["expected_ideas"]
    assert len(ideas) == 2
    idea_texts = {idea["idea"] for idea in ideas}
    assert idea_texts == {"Shuffle groups keys (edited).", "A second anchored idea."}


def test_approved_plan_rejects_further_edits(client, seeded_plan):
    objective_id = str(seeded_plan["objective_id"])
    plan_id = str(seeded_plan["plan_id"])

    edit_response = client.patch(f"/objectives/{objective_id}", json={"statement": "First edit."})
    assert edit_response.status_code == 200

    approve_response = client.post(f"/plans/{plan_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    second_edit = client.patch(f"/objectives/{objective_id}", json={"statement": "Should be rejected."})
    assert second_edit.status_code == 409

    delete_response = client.delete(f"/objectives/{objective_id}")
    assert delete_response.status_code == 409

    second_approve = client.post(f"/plans/{plan_id}/approve")
    assert second_approve.status_code == 409


def test_plan_edits_records_every_change(client, seeded_plan):
    objective_id = str(seeded_plan["objective_id"])
    plan_id = str(seeded_plan["plan_id"])

    client.patch(f"/objectives/{objective_id}", json={"statement": "Updated statement."})
    client.patch(f"/objectives/{objective_id}", json={"reviewed": True})
    client.post(f"/plans/{plan_id}/approve")

    edits = client.get(f"/plans/{plan_id}/edits").json()
    actions = [edit["action"] for edit in edits]
    assert actions == ["update", "update", "approve"]

    first_edit = edits[0]
    assert first_edit["objective_id"] == objective_id
    assert first_edit["before"]["statement"] == "Explain shuffle."
    assert first_edit["after"]["statement"] == "Updated statement."

    approve_edit = edits[-1]
    assert approve_edit["objective_id"] is None
    assert approve_edit["before"]["status"] == "draft"
    assert approve_edit["after"]["status"] == "approved"


def test_delete_objective_cascades_ideas_and_misconceptions(client, seeded_plan):
    objective_id = str(seeded_plan["objective_id"])
    plan_id = str(seeded_plan["plan_id"])

    delete_response = client.delete(f"/objectives/{objective_id}")
    assert delete_response.status_code == 204

    session = SessionLocal()
    try:
        assert session.get(LearningObjective, seeded_plan["objective_id"]) is None
        assert (
            session.query(ObjectiveExpectedIdea)
            .filter(ObjectiveExpectedIdea.objective_id == seeded_plan["objective_id"])
            .count()
            == 0
        )
        assert (
            session.query(ObjectiveMisconception)
            .filter(ObjectiveMisconception.objective_id == seeded_plan["objective_id"])
            .count()
            == 0
        )
    finally:
        session.close()

    edits = client.get(f"/plans/{plan_id}/edits").json()
    assert edits[-1]["action"] == "delete"
    assert edits[-1]["before"]["expected_ideas"]
    assert edits[-1]["before"]["misconceptions"]
    assert edits[-1]["after"] is None


def test_patch_unknown_objective_404(client):
    response = client.patch(f"/objectives/{uuid.uuid4()}", json={"statement": "x"})
    assert response.status_code == 404


def test_approve_unknown_plan_404(client):
    response = client.post(f"/plans/{uuid.uuid4()}/approve")
    assert response.status_code == 404
