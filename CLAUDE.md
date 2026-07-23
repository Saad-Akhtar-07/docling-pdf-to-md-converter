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

Repo is restructured onto the target layout (§2.17 of the roadmap doc): `apps/web`
(React/Vite frontend, unchanged), `apps/api` (FastAPI skeleton, health check only so
far), `packages/extraction` (the Module 0/0.5 extractor — PyMuPDF4LLM + RapidOCR +
OpenCode vision — importable as `slidevision.extraction`, plus a `cli.py`), and empty
`packages/tutor_core` / `packages/llm` / `packages/persistence` for later modules. The
extractor still runs as its own FastAPI process (`slidevision.extraction.service:app`,
spawned by `apps/web/vite.config.js` exactly as `server/localExtractorService.py` used
to be) rather than being merged into `apps/api` — that merge is Module 1's job, once
persistence and a job runner exist to justify it. The full spec, critique, module
roadmap, and week plan live in `docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md` — read it
before starting any module.

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
   bundle. The ONLY permitted client-side variable is `VITE_API_BASE_URL` — **with one
   documented exception**: a fixed set of browser-only tuning/timeout variables with no
   server-side duplicate and no secret value — `VITE_VISUAL_*` (client-side canvas pixel
   analysis in `apps/web/src/components/ImageDebugPanel.jsx` /
   `apps/web/src/utils/imagePipeline.js`), `VITE_OPENCODE_VISION_MODEL` /
   `VITE_OPENCODE_VISION_TIMEOUT_MS` (`apps/web/src/utils/visualDescriptionApi.js`), and
   `VITE_LOCAL_EXTRACTOR_TIMEOUT_MS` / `VITE_LOCAL_EXTRACTOR_IMAGES_SCALE`
   (`apps/web/src/utils/localExtractorApi.js`, the fetch timeout and requested render
   scale for the extractor call). Renaming any of these away from `VITE_` would silently
   break the feature that reads it (Vite only exposes `VITE_`-prefixed vars to browser
   code). See `docs/DECISIONS.md` for the reasoning. Before adding any new `VITE_`
   variable, verify it's genuinely client-only the same way — grep for where it's
   actually read — rather than assuming the prefix is available by default.

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
