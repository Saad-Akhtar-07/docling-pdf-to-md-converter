"""Typed errors for packages/graph, mirroring packages/persistence/errors.py's
pattern of raising specific exceptions the API layer maps to HTTP statuses."""

from __future__ import annotations


class SessionNotFoundError(Exception):
    """No `sessions` row exists with the given id."""


class SessionCompleteError(Exception):
    """A new (non-duplicate) turn was requested against a session that is
    no longer ACTIVE (already COMPLETED or ABANDONED)."""
