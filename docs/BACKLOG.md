# Backlog

Deferred items surface here as modules are built. Empty at project start.

## From "Database Schema" module (packages/persistence, docker-compose, Alembic)

- ~~No API routes, job runner, or extraction wiring populate these tables
  yet.~~ **Resolved by the "Document Registry" module**: `apps/api` now
  does exactly this.

- ~~`documents.status` values are this module's own judgment call.~~
  **Resolved**: the "Document Registry" module's prompt pinned down the
  exact lifecycle (`uploaded -> extracting -> ready | failed`); enum values
  renamed to match (`UPLOADED`/`EXTRACTING` replacing the old
  `PENDING`/`PROCESSING` guesses).

- **No `users` table exists.** `documents.user_id` / `sessions.user_id` are
  bare, unconstrained UUID columns — Module 1 explicitly lists "multi-user
  auth" under **Future**, so there's nothing to FK against yet. The
  "Document Registry" module hardcodes a fixed dev user id
  (`apps/api/routers/documents.py::DEV_USER_ID`,
  `00000000-0000-0000-0000-000000000001`) on every upload — replace with
  the real authenticated user once auth lands, and add the FK then.

- ~~`document_blocks.id` / `document_id` type mismatch with the extraction
  module's current output is not reconciled.~~ **Resolved by the "Document
  Registry" module**: `apps/api/jobs/extraction.py::run_extraction_job`
  passes `str(document_id)` (the DB-issued UUID) into
  `extract_document(..., document_id=...)`, so `make_block_id` hashes the
  real UUID rather than extraction minting its own hash-based id. The
  pre-existing `upsert_document`/`file_hash` bug noted below is still
  unfixed, but it's now fully isolated to the legacy SQLite-cached debug
  extractor (`packages/extraction/service.py`, port 5052) — `apps/api`
  never calls `upsert_document` at all.

- **`objective_expected_ideas.block_id` and every cross-aggregate FK from
  session/turn data back into plan structure use `ON DELETE RESTRICT`**
  (not `CASCADE`), to stop citations and research data
  (`turn_events`/`llm_calls`) from silently vanishing if someone deletes a
  document or plan out from under them. Practical consequence: deleting a
  `document` that has any `learning_plans` row, or a `learning_plan` that
  has any `sessions` row, will fail with a FK violation by design — there is
  no cascade/archive path yet. Module 3's plan-approval/archive flow should
  decide whether "delete" should even be exposed once a plan has sessions,
  or whether it should soft-delete (`status=archived`) instead.

- **`objective_misconceptions.code` / `session_objective_states.active_misconception_id`
  are unconstrained strings, not FKs.** §2.9's `ObjectiveAssessment.misconception_id`
  reads as a per-objective catalog code (paired with `misconception_novel_text`
  for not-yet-catalogued ones), not `objective_misconceptions.id`'s UUID PK —
  and a code is only unique per-objective, not globally, so it isn't
  cleanly FK-able. Revisit if Module 5/6 need referential integrity here.

- **`plan_edits` audit table (Module 3) not created.** Out of scope for this
  module — §2.10 doesn't list it, Module 3's spec does.

- **`document_blocks.embedding` (semantic fallback retrieval, §2.18 v1.1
  extension point) not added.** Explicitly deferred to v1.1 per the roadmap.

## From "Document Registry" module (apps/api, apps/web Documents tab)

- **No authentication — a single hardcoded dev user id.**
  `apps/api/routers/documents.py::DEV_USER_ID =
  uuid.UUID("00000000-0000-0000-0000-000000000001")` is attributed to every
  uploaded document, per this module's explicit instruction. Replace with
  real auth (§2.10's Future item) when that module is built; nothing else
  needs to change since `documents.user_id` is already a bare UUID column.

- **Re-upload idempotency is keyed on content hash, with two chosen
  behaviors — recorded here since the module asked for the rationale to be
  written down, not just implemented:**
  - Same bytes, existing document not `FAILED` → **200**, no-op, existing
    `document_id` returned, extraction is NOT re-triggered. Re-extracting a
    document whose blocks are already ready (or already in flight) would
    just burn OCR/vision cost for identical output, and would fight the
    in-flight job over the same rows.
  - Same bytes, existing document `FAILED` → **202**, treated as a retry:
    status resets to `uploaded`, extraction is rescheduled against the same
    `document_id`. Re-uploading a file that previously failed is exactly
    what a user does to ask "try again" — there's no separate retry
    endpoint, so this is the only way to retry via the API as built.
  - Not supported: retrying with *different* bytes under the same
    `document_id` (e.g. "I fixed the corrupt file, same upload slot").
    Different content hash → different `document_id` by design; this is
    arguably correct (different bytes are a different document) but worth
    a product decision later if it surprises users.

- **No `GET /documents` list endpoint.** Module 1's own API list is exactly
  `POST /documents`, `GET /documents/{id}`, `GET /documents/{id}/blocks`,
  `GET /health` — no list route. `apps/web`'s Documents tab only ever shows
  the most recently uploaded document (in-memory React state); there's no
  way to browse previously uploaded documents from the UI after a page
  reload. Add a list endpoint + a document picker when that's needed.

- **`VITE_API_BASE_URL` was repurposed.** It previously pointed the
  extractor-debug tool (`apps/web/src/utils/localExtractorApi.js`) at a
  base URL but was always blank in both env files, so in practice it did
  nothing (the tool always fell back to the `/local-extractor` Vite-proxy
  path). It now points the new typed `apps/web/src/api` client at `apps/api`
  (`http://localhost:8000` by default) per this module's explicit
  instruction ("the only VITE_ var"). `localExtractorApi.js` no longer reads
  it at all — the extractor-debug tool unconditionally uses the proxy path,
  which is what it was already doing in every configured environment.

- **`apps/web/src/api/client.ts`'s `uploadDocument` needs a manual
  `bodySerializer`,** not openapi-fetch's default multipart handling —
  passing `client.POST("/documents", { body: { file } })` alone produced an
  HTTP 422 against FastAPI's `File(...)` parameter (confirmed live, not
  theorized). The generated type for the upload body field is `string`
  (OpenAPI's `format: binary` has no native "File" type), cast to `unknown`
  then `string` at that one call site. If openapi-fetch changes its
  multipart defaults in a future upgrade, re-check whether the manual
  `bodySerializer` is still needed.

- **apps/api's OpenAPI spec only documents `200` for `POST /documents`,
  never the `202` it can actually return.** FastAPI infers the documented
  success status from the route decorator; this route sets
  `response.status_code` dynamically (200 vs. 202) instead of declaring a
  fixed one, and FastAPI doesn't introspect that. The response *body*
  shape (`DocumentCreateResponse`) is identical either way, so the
  generated TS types are unaffected — this is a spec-accuracy gap, not a
  functional one. Fix by adding `responses={202: {...}}` to the decorator
  if/when the OpenAPI spec itself needs to be authoritative (e.g. published
  externally).

- **`tests/integration/test_documents_api.py`'s per-test cleanup
  occasionally leaves a document's upload directory behind under
  `data/uploads/`** (Postgres rows are always cleaned — confirmed via
  `SELECT count(*) FROM documents` after a full run — only the on-disk
  directory can survive). `shutil.rmtree(..., ignore_errors=True)` silently
  swallows what looks like a Windows file-handle lock from
  `packages/extraction`'s PDF rendering, not from `apps/api` itself.
  Harmless (gitignored, disposable dev data) but not root-caused — chasing
  it would mean touching `packages/extraction` internals, out of scope for
  this module.

## From Module 0.5 (provenance-tagged Block extraction)

- **Fixture decks are synthetic.** No real lecture deck exists anywhere in
  the repo (checked — `data/`, `db/`, and the whole tree), so
  `tests/fixtures/decks/*/deck.pdf` are generated by
  `tests/fixtures/generate_decks.py`. Swap in real decks under the same path
  whenever convenient and re-run `generate_expected_blocks.py` to refresh the
  goldens; the regression suite doesn't care which.

- **Real vision calls are not wired into `extract_document`/the CLI.**
  `blocks.block_from_visual_description()` converts one vision-model
  description dict into a `model_generated` Block and is unit-tested, but
  nothing in `pipeline.py` calls the actual OpenCode vision API — today that
  only happens via the frontend-driven `/v1/visual-descriptions` endpoint in
  `service.py`, decoupled from `extract_document`. Wiring real vision calls
  into the core pipeline (and appending the resulting blocks) is deferred so
  the regression suite stays offline/deterministic; do it once there's a
  reason to make `model_generated` blocks part of the CLI/service's default
  output rather than a frontend-orchestrated side channel.

- **Mixed-page OCR is not implemented.** A page is currently classified as
  either fully `verbatim` (has ≥10 legible chars) or fully `ocr` (does not);
  there's no per-span detection of "mostly real text plus one illegible
  embedded screenshot" on the same page. Building that requires the
  redact-only-illegible-regions approach `ocr.py`'s `exec_modern_rapidocr`
  already uses for markdown rendering, adapted to emit blocks instead of
  mutating the page. See `packages/extraction/blocks.py`'s
  `_extract_ocr_blocks` docstring.

- **`markdown` is still pymupdf4llm output, not a rendering of blocks.** The
  roadmap's target end-state has Markdown derived from blocks (with the
  `<!-- block: ... provenance: ... -->` comment format shown in
  ARCHITECTURE_REVIEW_AND_ROADMAP.md §1.1). That format doesn't match what
  `apps/web/src/utils/imagePipeline.js` currently parses (`[Page N]` /
  `---`-separated sections), and this module's scope excludes touching
  `apps/web`. `blocks` is exposed as an additive field alongside the
  unchanged `markdown`/`chunks` fields; do the full switch (and the
  matching frontend parser update) together in whichever module takes on
  the frontend/block integration.

- **`service.py`'s extraction cache doesn't persist `blocks`/`documentId`.**
  A cache **hit** in `/v1/convert/file` still returns the old shape (no
  `blocks`, no `documentId`) since `cache.py`'s `document_extractions` table
  schema wasn't extended — only a cache **miss** (full extraction) returns
  them. Extending the SQLite cache is arguably premature given
  `packages/persistence` is the module meant to own durable storage; revisit
  there.

- **Pre-existing bug found while building this module:** `service.py`'s
  document registry (`upsert_document`, keyed on `file_hash`) hashes the
  *converted* PDF for PPT/PPTX/ODP uploads, and LibreOffice's PDF export
  embeds a fresh timestamp on every conversion — so re-uploading the exact
  same `.pptx` gets a different `document_id` every time. Confirmed in the
  existing cache: `data/slidevision-cache.sqlite` has 4 different
  `document_id`s all named `Week 15 IR Optimization.pptx`. The new
  block-level `document_id` (hash of the *original* upload, computed before
  conversion) does not have this problem — but `upsert_document`'s own
  `document_id` param is untouched here to keep this module's diff minimal.
  Point `upsert_document` at the same original-file hash when someone next
  touches the document registry.
