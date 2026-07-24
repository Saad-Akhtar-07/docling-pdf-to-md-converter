"""Engine / session factory for packages/persistence.

Reads DATABASE_URL from the environment. Unlike packages/extraction/config.py
(whose env vars are injected by apps/web/vite.config.js when it spawns the
extractor subprocess), this module has no such orchestrator — Alembic and
pytest invoke it directly — so it loads .env.local / .env itself.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env.local")
load_dotenv(_REPO_ROOT / ".env")

DEFAULT_DATABASE_URL = "postgresql+psycopg://tutor:tutor@localhost:5432/tutor"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Session:
    return SessionLocal()
