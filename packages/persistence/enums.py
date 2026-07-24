"""Storage-level enums for packages/persistence.

Mirrors the shapes of the state-model enums in
docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §2.9 (Provenance, Intent,
ObjectiveStatus, PedagogicalAction) plus a few storage-only status enums
(§2.10 gives their values inline as SQL comments: DocumentStatus is implied
by Module 1's "processing status" / "failed" language and is not given
explicit values anywhere, so it is this module's own judgment call).

Deliberately NOT imported from packages/tutor_core: that package does not
exist yet (a later module) and, per CLAUDE.md invariant #2, must never
import packages/persistence. Keeping these enums independent here (rather
than importing tutor_core's Pydantic enums once they exist) keeps the
dependency edge one-directional in either final shape.
"""

import enum


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Provenance(str, enum.Enum):
    VERBATIM = "verbatim"
    OCR = "ocr"
    MODEL_GENERATED = "model_generated"


class PlanStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    ARCHIVED = "archived"


class SessionStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class Intent(str, enum.Enum):
    ANSWER = "answer"
    QUESTION = "question"
    META = "meta"
    OFF_TASK = "off_task"


class ObjectiveStatus(str, enum.Enum):
    UNSEEN = "unseen"
    PROBING = "probing"
    PARTIAL = "partial"
    MISCONCEPTION = "misconception"
    CONFUSED = "confused"
    RESOLVED = "resolved"
    DEFERRED = "deferred"
    SKIPPED = "skipped"


class PedagogicalAction(str, enum.Enum):
    PROBE = "probe"
    HINT = "hint"
    REPHRASE = "rephrase"
    BRIDGE = "bridge"
    RETEACH = "reteach"
    CHECK_AGAIN = "check_again"
    DEEPEN = "deepen"
    REVISIT_PREREQ = "revisit_prereq"
    ADVANCE = "advance"
    DEFER = "defer"
    ANSWER_QUESTION = "answer_question"
    REDIRECT = "redirect"
