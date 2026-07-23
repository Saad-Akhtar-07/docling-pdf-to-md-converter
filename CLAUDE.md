# SlideVision Adaptive Tutor — Working Rules

## Project summary

An Adaptive AI-Powered Intelligent Tutoring System (FYP). A single Python (FastAPI)
service converts uploaded lecture slides (PDF/PPT/PPTX/ODP) into a provenance-tagged,
span-anchored learning plan (units → objectives → evidence cards, each idea anchored to
an exact block/char-offset in the source), then runs tutoring sessions as a sequence of
**pure turns**: each turn loads explicit state from Postgres, classifies the student's
intent (ANSWER/QUESTION/META/OFF_TASK), produces a structured assessment, applies a
deterministic policy to pick one pedagogical action (PROBE/HINT/REPHRASE/BRIDGE/RETEACH/
DEEPEN/ADVANCE/DEFER/...), and generates language constrained to that action and to cited
source spans. Every intermediate decision is written to an append-only event log.

The defining property: **no decision is hidden inside a prompt.** Perception (LLM),
control (deterministic policy), and generation (LLM, constrained) are three separately
inspectable, separately testable stages. Postgres is the single source of truth;
LangGraph is a structuring tool for one-shot turn execution, not a source of state.

Current repo state is a pre-restructure spike (`dockling test`): a React/Vite frontend
plus a Python FastAPI extractor (`server/localExtractorService.py`, PyMuPDF4LLM +
RapidOCR + OpenCode vision) that turns slides into Markdown. This is Module 0/0.5 of the
roadmap. The full spec, critique, module roadmap, and week plan live in
`docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md` — read it before starting any module.

## Architecture invariants (never violate)

1. Postgres is the ONLY source of truth. Nothing may exist only in memory or only
   in a LangGraph checkpoint.
2. `packages/tutor_core` must NEVER import an LLM library, an HTTP client, or a DB
   driver. It contains pure state models, the pedagogical policy, consistency checks,
   and termination rules. This is enforced by an import-linter test.
3. One student turn = one graph invocation, start to finish. State is loaded from
   Postgres at the first node and written back at the last. No LangGraph `interrupt()`.
4. Every tutor claim must cite a source span. Evidence may only anchor to blocks with
   provenance `verbatim` or `ocr` — NEVER `model_generated`.
5. The pedagogical policy is a PURE FUNCTION with no I/O. The LLM reports observations;
   the policy owns all state transitions.
6. Every LLM call goes through `packages/llm` and is logged to the `llm_calls` table
   with prompt_id, prompt_version, model, tokens, latency, and cost.
7. No secret may ever use the `VITE_` prefix. Vite inlines those into the browser
   bundle. The ONLY permitted client-side variable is `VITE_API_BASE_URL`.

## Scope discipline

- Build ONLY the module named in the current prompt. If you notice something that
  belongs to a later module, write it in `docs/BACKLOG.md` and move on.
- Do not add dependencies not required by the current module. Ask first.
- Do not refactor code outside the current module's scope.
- If a requirement in the prompt contradicts `docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md`,
  STOP and ask me.

## Environment

- Windows, PowerShell, `.venv`. Quote all paths (they contain spaces).
- Give me PowerShell commands, not bash. Do not chain with `&&`; use separate lines.

## Definition of done for every module

- Tests written and passing
- `docs/BACKLOG.md` updated with anything deferred
- You tell me exactly which env vars to add and what to run to verify
