"""SQLAlchemy 2.0 models for every table in docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §2.10.

All tables are created now, even for modules not yet built, so later modules
never need a destructive migration (CLAUDE.md). No business logic, no API
routes, no LLM code lives here — this module owns shape and constraints only.

Design decisions not fully pinned down by §2.10 (documented here rather than
silently guessed, per CLAUDE.md's "if underspecified, note the call"):

- All entity primary keys are UUID, matching the `uuid[]` columns §2.10
  already uses elsewhere (prerequisite_objective_ids, resolved, deferred).
  The one exception is document_blocks.id, which is the content-derived,
  stable-across-re-runs hash string `packages/extraction/blocks.py` already
  generates and tests (`make_block_id`) — making it a surrogate UUID instead
  would break the "stable block ID" contract Module 0.5 built.
- `documents.user_id` / `sessions.user_id` are bare UUID columns with no FK:
  §2.10 includes the column but no `users` table exists anywhere in the
  roadmap, and Module 1 explicitly lists "multi-user auth" under **Future**.
  This is a single-user MVP placeholder, not an oversight.
- `objective_expected_ideas.block_id` (anchoring) and every reference from
  session/turn "research data" back up into plan structure
  (learning_plans.document_id, sessions.document_id, sessions.plan_id,
  turns.objective_id, session_objective_states.objective_id) use
  ON DELETE RESTRICT: these protect citations and research data
  (turn_events/llm_calls, called out in §2.10 as "your research dataset")
  from silently disappearing because something upstream was deleted.
  Structural parent/child rows within one aggregate (document_blocks under
  documents; units/objectives/ideas/misconceptions under a plan; turns/
  turn_events/session_objective_states under a session) use ON DELETE CASCADE.
- `active_misconception_id` (session_objective_states) and
  `misconception_id` (would-be assessment payload) are plain strings, not a
  hard FK to objective_misconceptions.id: §2.9's ObjectiveAssessment model
  pairs `misconception_id` with `misconception_novel_text`, implying it
  matches against `objective_misconceptions.code` (a short catalog code) or
  is a not-yet-catalogued novel one — not the row's UUID PK. A code isn't
  globally unique (only unique per objective), so it isn't FK-able cleanly;
  left unconstrained like `prerequisite_objective_ids` already is in §2.10.
- `llm_calls.session_id` / `.turn_id` are nullable: plan-building LLM calls
  (Module 2) happen before any session exists.
- `session_reports.session_id` has a UNIQUE constraint (one report per
  session) beyond the four indexes the prompt named explicitly — a direct
  reading of "a report per session", not scope creep.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from slidevision.persistence.enums import (
    DocumentStatus,
    Intent,
    ObjectiveStatus,
    PedagogicalAction,
    PlanStatus,
    Provenance,
    SessionStatus,
)


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _pg_enum(py_enum: type, name: str):
    return Enum(py_enum, name=name, native_enum=False, validate_strings=True)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        _pg_enum(DocumentStatus, "document_status"),
        nullable=False,
        default=DocumentStatus.PENDING,
    )
    created_at: Mapped[datetime] = _created_at()

    blocks: Mapped[list["DocumentBlock"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentBlock(Base):
    __tablename__ = "document_blocks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    slide_no: Mapped[int] = mapped_column(Integer, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[Provenance] = mapped_column(
        _pg_enum(Provenance, "block_provenance"), nullable=False
    )
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    producer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bbox: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="blocks")

    __table_args__ = (
        Index("ix_document_blocks_document_slide_order", "document_id", "slide_no", "order_index"),
    )


class LearningPlan(Base):
    __tablename__ = "learning_plans"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PlanStatus] = mapped_column(
        _pg_enum(PlanStatus, "plan_status"), nullable=False, default=PlanStatus.DRAFT
    )
    builder_prompt_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = _created_at()

    units: Mapped[list["LearningUnit"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_learning_plans_document_version"),)


class LearningUnit(Base):
    __tablename__ = "learning_units"

    id: Mapped[uuid.UUID] = _uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_plans.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    slide_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=list)

    plan: Mapped["LearningPlan"] = relationship(back_populates="units")
    objectives: Mapped[list["LearningObjective"]] = relationship(
        back_populates="unit", cascade="all, delete-orphan"
    )


class LearningObjective(Base):
    __tablename__ = "learning_objectives"

    id: Mapped[uuid.UUID] = _uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_units.id", ondelete="CASCADE"), nullable=False
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    low_confidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prerequisite_objective_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list
    )

    unit: Mapped["LearningUnit"] = relationship(back_populates="objectives")
    expected_ideas: Mapped[list["ObjectiveExpectedIdea"]] = relationship(
        back_populates="objective", cascade="all, delete-orphan"
    )
    misconceptions: Mapped[list["ObjectiveMisconception"]] = relationship(
        back_populates="objective", cascade="all, delete-orphan"
    )


class ObjectiveExpectedIdea(Base):
    __tablename__ = "objective_expected_ideas"

    id: Mapped[uuid.UUID] = _uuid_pk()
    objective_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_objectives.id", ondelete="CASCADE"), nullable=False
    )
    idea: Mapped[str] = mapped_column(Text, nullable=False)
    block_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("document_blocks.id", ondelete="RESTRICT"), nullable=False
    )
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)

    objective: Mapped["LearningObjective"] = relationship(back_populates="expected_ideas")

    __table_args__ = (CheckConstraint("char_end > char_start", name="ck_expected_idea_span_nonempty"),)


class ObjectiveMisconception(Base):
    __tablename__ = "objective_misconceptions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    objective_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_objectives.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    objective: Mapped["LearningObjective"] = relationship(back_populates="misconceptions")

    __table_args__ = (UniqueConstraint("objective_id", "code", name="uq_objective_misconceptions_objective_code"),)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[SessionStatus] = mapped_column(
        _pg_enum(SessionStatus, "session_status"), nullable=False, default=SessionStatus.ACTIVE
    )
    current_objective_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_objectives.id", ondelete="RESTRICT"), nullable=True
    )
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = _created_at()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    objective_states: Mapped[list["SessionObjectiveState"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    turns: Mapped[list["Turn"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class SessionObjectiveState(Base):
    __tablename__ = "session_objective_states"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    objective_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_objectives.id", ondelete="RESTRICT"), primary_key=True
    )
    status: Mapped[ObjectiveStatus] = mapped_column(
        _pg_enum(ObjectiveStatus, "objective_status"), nullable=False, default=ObjectiveStatus.UNSEEN
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hint_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deepen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prereq_revisits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    met_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_misconception_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_action: Mapped[PedagogicalAction | None] = mapped_column(
        _pg_enum(PedagogicalAction, "pedagogical_action"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    session: Mapped["Session"] = relationship(back_populates="objective_states")


class Turn(Base):
    __tablename__ = "turns"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    student_message: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[Intent | None] = mapped_column(_pg_enum(Intent, "turn_intent"), nullable=True)
    action: Mapped[PedagogicalAction | None] = mapped_column(
        _pg_enum(PedagogicalAction, "pedagogical_action"), nullable=True
    )
    tutor_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    objective_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_objectives.id", ondelete="RESTRICT"), nullable=True
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = _created_at()

    session: Mapped["Session"] = relationship(back_populates="turns")
    events: Mapped[list["TurnEvent"]] = relationship(back_populates="turn", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_turns_session_index", "session_id", "index"),)


class TurnEvent(Base):
    __tablename__ = "turn_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("turns.id", ondelete="CASCADE"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created_at()

    turn: Mapped["Turn | None"] = relationship(back_populates="events")

    __table_args__ = (Index("ix_turn_events_session_created", "session_id", "created_at"),)


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("turns.id", ondelete="CASCADE"), nullable=True
    )
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_id: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()


class SessionReport(Base):
    __tablename__ = "session_reports"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    deferred: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    misconceptions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    effective_actions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created_at()
