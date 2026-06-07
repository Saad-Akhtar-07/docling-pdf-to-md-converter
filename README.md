# SlideVision Markdown Extractor

A React + Vite + Tailwind app for turning slide PDFs into page-aware Markdown for downstream
text and Vision LLM pipelines.

The app uses Docling Serve to extract OCR/text/table content, keeps each slide/page separated, and
embeds full-page slide images only for pages that Docling identifies as useful Vision candidates.
This helps avoid sending plain text slides to a Vision model while preserving diagrams, charts,
architecture figures, and other visual regions that OCR may not describe well.

## What It Produces

The downloaded Markdown is organized by slide/page:

```md
[Page 4]

OCR/text content extracted by Docling...

### Vision Image
Picture regions: 1, picture area: 36.95%, residual score: 20.57%

![Page 4 vision image 1](data:image/png;base64,...)
```

Pages without a `Send to Vision` decision include text only.

## Core Pipeline

**PDF files** go directly to Docling Serve:

```text
PDF slide deck
  → Docling Serve OCR/table/layout extraction
  → embedded full-page slide images
  → Docling picture-region scoring
  → page-aware Markdown
  → optional Vision LLM step for selected pages
```

**PowerPoint files** (.ppt / .pptx) go through an extra conversion step first:

```text
PPT / PPTX
  → Gotenberg (LibreOffice headless) → PDF
  → Docling Serve structured JSON + Markdown extraction
  → page-aware Markdown
```

Gotenberg converts the presentation to a pixel-perfect PDF using LibreOffice so
that Docling can run its normal OCR and layout pipeline on the rendered slides.

The app intentionally uses:

```text
to_formats: ["md", "json"]
image_export_mode: "embedded"
include_images: true
force_ocr: true by default
```

Referenced and placeholder image modes are not used because the downstream Vision pipeline needs
direct image bytes.

`Force visual OCR` is enabled by default because some slide PDFs contain broken embedded text
layers or custom font encodings. In those files, normal PDF text extraction can produce garbled
output even though the slide looks correct. Forced OCR asks Docling to read the rendered slide
visually instead.

## Requirements

- Node.js 18+
- npm
- **Docker** (for Gotenberg and Docling Serve)
- Gotenberg running at `http://localhost:3000`
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

## Gotenberg (required for PowerPoint files)

Gotenberg converts PPT / PPTX files to PDF using LibreOffice before they are
passed to Docling. Start it with:

```bash
docker run -d --name gotenberg -p 3000:3000 gotenberg/gotenberg:8
```

> **Note:** Gotenberg only needs to be running when you upload PowerPoint files.
> PDF files are sent directly to Docling and do not use Gotenberg.

To stop and remove the container when you no longer need it:

```bash
docker stop gotenberg && docker rm gotenberg
```

## Docling Serve

The app calls:

```text
POST /v1/convert/file
```

through the Vite proxy:

```text
/docling/v1/convert/file
```

The Docling base URL is configured in:

```text
src/utils/doclingApi.js
```

By default it uses:

```text
VITE_DOCLING_BASE_URL=/docling
```

To call Docling directly from the browser, create `.env.local`:

```text
VITE_DOCLING_BASE_URL=http://localhost:5001
```

Restart the Vite dev server after changing environment variables.

## Vision Candidate Logic

The `Vision Candidate Pages` panel shows every embedded page image and whether it will be included
in the final Markdown.

Default decision filters:

```js
minPictureBoxes: 1
minPictureAreaPercent: 10
maxRepeatCount: 1
enableResidualFallback: false
```

Meaning:

```text
Send to Vision if Docling detected at least one picture/figure region covering 10% or more
of the slide image, unless the exact page image is repeated.
```

The panel also shows:

```text
original page image
text-masked debug image
picture box overlay
picture area %
residual score
edge score
skip/send reason
```

The text-masked preview is diagnostic only by default. The main decision uses Docling layout
picture regions because they are more reliable for slide decks than raw OCR masking.

## Common Issues

### Garbled text output

If text looks like shifted or nonsense characters, keep `Force visual OCR` enabled and run the
extraction again. That usually means the PDF text layer is bad, not that the visible slide text is
unreadable.

### Docling server offline

Confirm Docker is running and Docling Serve is listening on `http://localhost:5001`.

### CORS error

Use the default `/docling` proxy during Vite development.

### Timeout or large file delay

If Docling returns `HTTP 504`, increase the Docling Serve wait time:

```bash
docker run -p 5001:5001 -e DOCLING_SERVE_MAX_SYNC_WAIT=600 your-docling-serve-image
```

The browser-side timeout can also be adjusted:

```text
VITE_DOCLING_TIMEOUT_MS=600000
```

## Build

```bash
npm run build
```

Preview the production build:

```bash
npm run preview
```
