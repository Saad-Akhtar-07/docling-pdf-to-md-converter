"""Integration tests for apps/api's document upload -> extraction -> blocks
path (POST /documents, GET /documents/{id}, GET /documents/{id}/blocks).

Requires a real Postgres reachable at DATABASE_URL (docker compose up -d)
with migrations applied — see tests/integration/conftest.py. FastAPI's
TestClient runs BackgroundTasks synchronously as part of request handling,
so `client.post("/documents", ...)` has already run (or failed) extraction
by the time it returns; no polling needed here, unlike a real browser client
talking to a live uvicorn server.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.jobs.extraction import run_extraction_job
from apps.api.main import app
from apps.api.settings import get_settings
from slidevision.persistence.db import SessionLocal
from slidevision.persistence.enums import DocumentStatus
from slidevision.persistence.models import Document
from slidevision.persistence.repositories import DocumentRepository

FIXTURE_DECK = Path(__file__).resolve().parents[1] / "fixtures" / "decks" / "text_heavy" / "deck.pdf"


@contextmanager
def _scratch_file(name: str, content: bytes):
    """A standalone tempfile.TemporaryDirectory() instead of pytest's
    tmp_path fixture: this environment's pytest-managed base temp dir
    (AppData\\Local\\Temp\\pytest-of-...) has a stale permission issue
    unrelated to this test suite.
    """
    with tempfile.TemporaryDirectory(prefix="slidevision-test-") as tmp_dir:
        path = Path(tmp_dir) / name
        path.write_bytes(content)
        yield path


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def created_documents():
    """Tracks document ids (as strings) created during a test and deletes
    them, plus their uploaded files, afterward.

    Unlike test_schema.py's rollback-only `db` fixture, this can't use a
    shared uncommitted transaction: the background extraction job opens its
    own SessionLocal() and must actually see what the request handler
    wrote, so apps/api commits for real against the dev database and this
    fixture cleans up for real too.
    """
    ids: list[str] = []
    yield ids
    if not ids:
        return
    session = SessionLocal()
    try:
        for document_id in ids:
            document = session.get(Document, uuid.UUID(document_id))
            if document is not None:
                session.delete(document)
                session.commit()
            shutil.rmtree(get_settings().upload_dir / document_id, ignore_errors=True)
    finally:
        session.close()


def _upload(client, created_documents, path, filename=None, content_type="application/pdf"):
    with path.open("rb") as fh:
        response = client.post("/documents", files={"file": (filename or path.name, fh, content_type)})
    if response.status_code in (200, 202):
        created_documents.append(response.json()["document_id"])
    return response


def test_upload_persists_provenance_tagged_blocks(client, created_documents):
    response = _upload(client, created_documents, FIXTURE_DECK)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "uploaded"
    document_id = body["document_id"]

    detail = client.get(f"/documents/{document_id}").json()
    assert detail["status"] == "ready"
    assert detail["error"] is None

    blocks = client.get(f"/documents/{document_id}/blocks").json()["blocks"]
    assert len(blocks) > 0
    provenances = {block["provenance"] for block in blocks}
    assert provenances <= {"verbatim", "ocr", "model_generated"}
    assert "verbatim" in provenances  # text_heavy deck has real text layers

    slide_1_blocks = [b for b in blocks if b["slide_no"] == 1]
    assert [b["order_index"] for b in slide_1_blocks] == sorted(b["order_index"] for b in slide_1_blocks)

    upload_path = get_settings().upload_dir / document_id / "deck.pdf"
    assert upload_path.exists()


def test_blocks_can_be_filtered_by_slide(client, created_documents):
    document_id = _upload(client, created_documents, FIXTURE_DECK).json()["document_id"]
    all_blocks = client.get(f"/documents/{document_id}/blocks").json()["blocks"]
    max_slide = max(b["slide_no"] for b in all_blocks)

    filtered = client.get(f"/documents/{document_id}/blocks", params={"slide": max_slide}).json()["blocks"]
    assert filtered
    assert all(b["slide_no"] == max_slide for b in filtered)
    assert len(filtered) < len(all_blocks)


def test_reupload_same_bytes_is_idempotent(client, created_documents):
    first = _upload(client, created_documents, FIXTURE_DECK)
    assert first.status_code == 202
    document_id = first.json()["document_id"]

    second = _upload(client, created_documents, FIXTURE_DECK)
    assert second.status_code == 200
    assert second.json()["document_id"] == document_id
    assert second.json()["status"] == "ready"

    session = SessionLocal()
    try:
        assert session.query(Document).filter(Document.id == uuid.UUID(document_id)).count() == 1
    finally:
        session.close()
    assert len(client.get(f"/documents/{document_id}/blocks").json()["blocks"]) > 0


def test_upload_rejects_unsupported_extension(client, created_documents):
    with _scratch_file("notes.txt", b"just text") as bogus:
        response = _upload(client, created_documents, bogus, content_type="text/plain")
    assert response.status_code == 415


def test_upload_rejects_empty_file(client, created_documents):
    with _scratch_file("empty.pdf", b"") as empty:
        response = _upload(client, created_documents, empty)
    assert response.status_code == 400


def test_get_document_404_for_unknown_id(client):
    response = client.get("/documents/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_failed_extraction_sets_status_and_error(client, created_documents):
    with _scratch_file("broken.pdf", b"not a real pdf file") as broken:
        response = _upload(client, created_documents, broken)
    assert response.status_code == 202
    document_id = response.json()["document_id"]

    detail = client.get(f"/documents/{document_id}").json()
    assert detail["status"] == "failed"
    assert detail["error"]
    assert client.get(f"/documents/{document_id}/blocks").json()["blocks"] == []


def test_retry_after_failure_reextracts_same_document(client, created_documents):
    with _scratch_file("retry.pdf", b"not a real pdf file") as broken:
        first = _upload(client, created_documents, broken, filename="retry.pdf")
        assert first.status_code == 202
        document_id = first.json()["document_id"]
        assert client.get(f"/documents/{document_id}").json()["status"] == "failed"

        # Re-uploading the exact same (still broken) bytes is a retry: still
        # 202 (work was rescheduled against the same document_id), not the
        # 200 no-op a healthy/in-flight content-hash match would get.
        second = _upload(client, created_documents, broken, filename="retry.pdf")
    assert second.status_code == 202
    assert second.json()["document_id"] == document_id
    assert client.get(f"/documents/{document_id}").json()["status"] == "failed"


def test_extraction_job_persists_blocks_committed_before_a_later_failure(created_documents, monkeypatch):
    """Exercises run_extraction_job directly: if persisting block N of an
    otherwise-successful extraction raises, blocks 0..N-1 must already be
    durably committed rather than lost with the rest of the transaction —
    the concrete mechanism behind "on failure: persist partial blocks".
    """
    session = SessionLocal()
    repo = DocumentRepository(session)
    document = repo.create(
        title="Partial",
        source_filename="partial.pdf",
        mime="application/pdf",
        content_hash=uuid.uuid4().hex,
        storage_uri="data/uploads/partial/partial.pdf",
    )
    session.commit()
    document_id = document.id
    created_documents.append(str(document_id))
    session.close()

    fake_blocks = [
        {
            "block_id": f"blk-{i}",
            "slide_no": 1,
            "order_index": i,
            "text": f"block {i}",
            "provenance": "verbatim",
            "ocr_confidence": None,
            "producer": None,
            "bbox": None,
        }
        for i in range(3)
    ]

    def fake_extract_document(*args, **kwargs):
        return {"blocks": fake_blocks}

    real_add_block = DocumentRepository.add_block
    call_count = {"n": 0}

    def flaky_add_block(self, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated write failure on the 2nd block")
        return real_add_block(self, **kwargs)

    monkeypatch.setattr("apps.api.jobs.extraction.extract_document", fake_extract_document)
    monkeypatch.setattr(DocumentRepository, "add_block", flaky_add_block)

    run_extraction_job(document_id, Path("unused.pdf"))

    session = SessionLocal()
    try:
        refreshed = session.get(Document, document_id)
        assert refreshed.status == DocumentStatus.FAILED
        assert "simulated write failure" in refreshed.error
        remaining_blocks = DocumentRepository(session).get_blocks(document_id)
        assert len(remaining_blocks) == 1  # the one block committed before the 2nd failed
    finally:
        session.close()
