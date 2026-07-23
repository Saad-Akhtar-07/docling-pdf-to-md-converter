# Decisions

## 2026-07-23/24 — Repo restructure (Module 0.5 → target layout)

**Extractor's FastAPI app stays in `packages/extraction/service.py`, not `apps/api`.**
This module scoped `apps/api` to an empty health-check skeleton, but the React app
talks to the extractor over live HTTP (Vite spawns uvicorn, proxied through
`/local-extractor`). Merging the extraction routes into `apps/api` now would have been
scope creep ahead of Module 1 (no persistence layer or job runner exists yet to justify
`apps/api` owning them); leaving the live flow disconnected would have broken
`npm run dev`. Chose to keep a transitional FastAPI app inside `packages/extraction`
that Vite spawns directly (`slidevision.extraction.service:app`), preserving identical
behavior. Revisit when Module 1 gives `apps/api` real routes and a reason to absorb
extraction's HTTP layer.

**`server/langchainExtractorService.py` and `server/groqVisionService.js` were deleted,
not archived.** Both were confirmed dead code (unused by any script, by
`vite.config.js`, or by any `src/` import) before this restructure. Superseded by the
OpenCode-based pipeline in `localExtractorService.py` (now `packages/extraction/`).
Full history is preserved on the `pre-restructure` git tag if either is ever needed for
the FYP report's comparison section. Their frontend counterparts (`doclingApi.js`,
`pptApi.js`, `langchainExtractorApi.js`, `visionApi.js`) were deleted for the same
reason — confirmed unused, no import anywhere in `src/`.

**`VITE_VISUAL_*` and `VITE_OPENCODE_VISION_*` stay `VITE_`-prefixed — documented
exception to invariant #7.** The roadmap doc's Part 0 assumed these were "server-side
extraction heuristics with a client-side prefix" (a leak risk). Code inspection showed
otherwise: `ImageDebugPanel.jsx` does genuine canvas-based pixel analysis in the
browser (`calculateResidualScores`, `analyzeImage`) to decide which rendered slide
images are "visual enough" to send for description, and reads these vars via
`import.meta.env` with no server-side duplicate. None are secrets. Renaming them away
from `VITE_` would have required either hardcoding the values as JS constants (losing
env-configurability, a real behavior change) or a custom Vite `envPrefix` (reintroducing
the exact ambiguity the rule exists to prevent). Confirmed with the project owner:
keep them `VITE_`, document the exception in CLAUDE.md invariant #7 rather than
silently relaxing the rule. The only var actually renamed for the leak fix was
`VITE_LOCAL_EXTRACTOR_BASE_URL` → `VITE_API_BASE_URL` (a legitimate rename, not a
leak fix — the extractor was never in-process, it's still a separate FastAPI process
reached via the Vite proxy, same as before).

**`packages/extraction` is split into single-purpose modules** (`config.py`, `utils.py`,
`cache.py`, `office.py`, `ocr.py`, `geometry.py`, `markdown_build.py`, `pipeline.py`,
`service.py`, `cli.py`) rather than kept as one ~1,770-line file, matching the
"importable package" requirement. `opencodeVisionClient.mjs` moved to
`packages/extraction/opencode_helper/` since the Python code still shells out to it by
design (no LLM library dependency in the extraction layer); `OPENCODE_VISION_NODE_HELPER`'s
default path now resolves relative to the package file itself rather than process cwd,
since the package can now be imported/run from anywhere.
