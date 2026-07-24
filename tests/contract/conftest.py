"""Shared fixtures for tests/contract.

These tests must run offline and free (CLAUDE.md / packages/llm prompt):
respx intercepts every HTTP call (no real gateway traffic is possible while
a respx mock is active — an unmocked request raises rather than going out),
and `logged_calls` replaces packages/llm's DB-writing logger with an
in-memory list so no Postgres connection is required either.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def load_fixture():
    """Returns a name -> dict loader, callable from within a test body."""
    return _load_fixture


@pytest.fixture
def logged_calls(monkeypatch):
    calls: list[dict] = []

    def fake_record_llm_call(**kwargs):
        call_id = uuid.uuid4()
        calls.append({**kwargs, "id": call_id})
        return call_id

    monkeypatch.setattr("slidevision.llm.client.llm_logging.record_llm_call", fake_record_llm_call)
    return calls


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch):
    """Retry backoff uses real time.sleep; tests exercise the retry path but
    shouldn't take seconds doing it."""
    monkeypatch.setattr("slidevision.llm.client.time.sleep", lambda _seconds: None)
