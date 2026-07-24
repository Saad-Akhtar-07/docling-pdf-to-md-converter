"""Typed errors for packages/persistence."""

from __future__ import annotations


class PlanNotEditableError(Exception):
    """Raised when a mutation targets an objective/idea belonging to a plan
    that is no longer `draft` (approved or archived). Enforced in
    PlanRepository itself, not just apps/api's router, so approval really is
    a freeze regardless of which caller mutates the aggregate."""
