# PDF to Markdown Processor

A small React + Vite + Tailwind app for testing Docling Serve PDF-to-Markdown conversion. It uploads a local PDF, calls Docling Serve, extracts Markdown defensively from the response, and keeps the raw JSON visible for parser inspection.

## Requirements

- Node.js 18+
- npm
- Docling Serve running at `http://localhost:5001`

## Install

```bash
npm install
```

## Run

```bash
npm run dev
```

Open the Vite URL shown in the terminal, usually:

```text
http://localhost:5173
```

## Make Sure Docling Serve Is Running

Start your Docling Serve Docker container so the API is reachable on:

```text
http://localhost:5001
```

The app calls:

```text
POST /v1/convert/file
```

through the Vite proxy:

```text
/docling/v1/convert/file
```

The proxy is configured in `vite.config.js` and avoids browser CORS issues during development.

## Test With A PDF

1. Start Docling Serve.
2. Run `npm run dev`.
3. Open the app.
4. Choose or drop a `.pdf` file.
5. Adjust OCR, table, format, and image export options.
6. Click `Convert PDF`.
7. Review the Markdown, raw JSON, stats, and detected image/figure metadata.

The Markdown output is generated from Docling structured JSON when available. Items are grouped by
`prov[0].page_no`, producing page markers such as `[Page 1]`. The app also shows a `chunks` array
with `documentName`, `pageNo`, `type`, `content`, and metadata so you can inspect how each item was
placed into the page-aware Markdown.

## Configuration

The Docling base URL is configured in one place:

```js
src/utils/doclingApi.js
```

By default it uses the Vite proxy:

```text
VITE_DOCLING_BASE_URL=/docling
```

To call Docling directly from the browser, create `.env.local`:

```text
VITE_DOCLING_BASE_URL=http://localhost:5001
```

Restart the Vite dev server after changing environment variables.

## Common Issues

### Docling server offline

If conversion fails with a network error, confirm Docker is running and Docling Serve is listening on `http://localhost:5001`.

### CORS error

Use the default `/docling` proxy. If you changed `VITE_DOCLING_BASE_URL` to `http://localhost:5001`, switch it back to `/docling` during Vite development.

### Timeout or large file delay

If Docling returns `HTTP 504` with `DOCLING_SERVE_MAX_SYNC_WAIT=120`, increase the Docling Serve container wait time.

For Docker:

```bash
docker run -p 5001:5001 -e DOCLING_SERVE_MAX_SYNC_WAIT=600 your-docling-serve-image
```

For Docker Compose:

```yaml
environment:
  DOCLING_SERVE_MAX_SYNC_WAIT: "600"
```

The app also has a browser-side timeout:

```text
VITE_DOCLING_TIMEOUT_MS=600000
```

This value is in milliseconds, so `600000` means 10 minutes.

### No Markdown found

Docling response shapes can vary. The full raw JSON response is displayed so you can inspect it and update `src/utils/responseParser.js` with the correct Markdown path.

### Image export mode unsupported

Different Docling Serve versions may support different image export modes. Try `embedded` first, then `referenced`.

## Build

```bash
npm run build
```

Preview the production build:

```bash
npm run preview
```
