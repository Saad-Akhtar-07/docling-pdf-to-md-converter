"""Typed errors for packages/llm.

docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §2.13: "the session never breaks
because a model returned bad JSON" — callers catch StructuredOutputError and
choose their own safe default (e.g. verdict=confused, action=REPHRASE).
This module must never invent a fallback value itself.
"""

from __future__ import annotations


class LlmRequestError(RuntimeError):
    """Transport/HTTP-level failure (timeout, 5xx, 429, connection error)
    that survived all retries in client.py."""


class StructuredOutputError(RuntimeError):
    """Structured output could not be parsed/validated after the repair
    retry. Carries the raw model output and the validation errors from
    both attempts so callers/logs can diagnose without re-running."""

    def __init__(self, message: str, *, raw_response: str, validation_errors: str) -> None:
        super().__init__(message)
        self.raw_response = raw_response
        self.validation_errors = validation_errors
