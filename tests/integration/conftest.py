"""Shared fixtures for tests/integration."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from slidevision.persistence.db import engine


@pytest.fixture(autouse=True)
def _require_database():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres not reachable at DATABASE_URL: {exc}")
