# SlideVision Markdown Extractor

A React + Vite + Tailwind app plus a small Node Vision worker for turning slide PDFs into
page-aware Markdown for downstream teaching pipelines.

The app uses Docling Serve to extract OCR/text/table content, keeps each slide/page separated,
selects full-page slide images only when Docling identifies useful visual regions, and sends those
selected images to Groq Vision for compact descriptions. The final Markdown keeps text and tables,
but replaces raw base64 image blobs with teaching-ready visual descriptions.

## What It Produces

The downloaded Markdown is organized by slide/page:

```md
[Page 4]

OCR/text content extracted by Docling...

### Visual Description

The slide shows an LSTM cell diagram with gates controlling how information moves through the
cell state and hidden state.

Teaching note:
Use this visual to explain that the cell state is the long-term memory path, while the forget,
input, and output gates regulate what is removed, added, and exposed at each time step.
```

Pages without a Vision candidate decision include text only.

## Core Pipeline

PDF files go directly to Docling Serve:

```text
PDF slide deck
-> Docling Serve OCR/table/layout extraction
-> embedded full-page slide images
-> Docling picture-region scoring
-> page-aware Markdown
-> Groq Vision descriptions for selected pages
-> final Markdown without base64 images
```

PowerPoint files (`.ppt` / `.pptx`) go through one extra conversion step first:

```text
PPT / PPTX
-> Gotenberg (LibreOffice headless)
-> PDF
-> existing Docling Serve pipeline
-> page-aware Markdown with Groq visual descriptions
```

Gotenberg converts the presentation to PDF using LibreOffice. The app then wraps that PDF as a
browser `File` and sends it through the same Docling flow used by normal PDF uploads.

The service pipeline intentionally hardcodes:

```text
to_formats: ["md", "json"]
do_ocr: true
force_ocr: true
do_table_structure: true
table_mode: "accurate"
image_export_mode: "embedded"
include_images: true
images_scale: 2
```

Referenced and placeholder image modes are not used because the downstream Vision pipeline needs
direct image bytes.

Forced visual OCR is enabled because some slide PDFs contain broken embedded text
layers or custom font encodings. In those files, normal PDF text extraction can produce garbled
output even though the slide looks correct. Forced OCR asks Docling to read the rendered slide
visually instead.

## Requirements

- Node.js 18+
- npm
- Docker, for Docling Serve and Gotenberg
- Docling Serve running at `http://localhost:5001`
- Gotenberg running at `http://localhost:3000` for PowerPoint uploads
- Groq API key in `.env.local` for Vision descriptions

## Install

```bash
npm install
```

## Run

Start the app:

```bash
npm run dev
```

During development, Vite also hosts the server-side Groq Vision API at `/api/vision/*`, so no
second terminal is needed.

The older alias also works:

```bash
npm run dev:all
```

Open the Vite URL shown in the terminal, usually:

```text
http://localhost:5173
```

## Groq Vision

The Vision worker calls Groq's OpenAI-compatible Chat Completions endpoint with:

```text
model: meta-llama/llama-4-scout-17b-16e-instruct
response_format: json_object
temperature: 0.2
max_completion_tokens: 700
```

Create `.env.local`:

```text
GROQ_API_KEY=your_groq_api_key_here
GROQ_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
GROQ_VISION_CONCURRENCY=1
GROQ_VISION_REQUEST_DELAY_MS=15000
GROQ_VISION_RETRY_COUNT=6
GROQ_VISION_RETRY_BASE_DELAY_MS=4000
GROQ_VISION_TIMEOUT_MS=180000
GROQ_VISION_MAX_TOKENS=500
GROQ_VISION_PAGE_TEXT_CHARS=1500
GROQ_VISION_TEMPERATURE=0.2
VISION_SERVICE_PORT=8787
```

The default Vision profile is intentionally slow and patient for free-tier Groq usage: one slide at
a time, 15 seconds between requests, and retries with backoff on rate limits or transient server
errors.

During Vite development, the frontend calls the server-side Vision route at:

```text
/api/vision/describe-batch
```

Health check:

```text
http://localhost:5173/api/vision/health
```

Groq's current base64 image request limit is 4MB, so the service rejects a single slide image above
that size and asks you to lower `images_scale` or switch to hosted image URLs.

## Gotenberg

Gotenberg is required only for PowerPoint files. Start it with:

```bash
docker run -d --name gotenberg -p 3000:3000 gotenberg/gotenberg:8
```

PDF files are sent directly to Docling and do not use Gotenberg.

To stop and remove the container when you no longer need it:

```bash
docker stop gotenberg && docker rm gotenberg
```

During Vite development, PowerPoint conversion is called through:

```text
/gotenberg/forms/libreoffice/convert
```

The proxy target is configured in:

```text
vite.config.js
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

The `Vision Candidate Pages` panel shows every embedded page image and whether it will be sent to
Groq for description.

Default decision filters:

```js
minPictureBoxes: 1
minPictureAreaPercent: 12
maxRepeatCount: 1
enableResidualFallback: false
```

Meaning:

```text
Send to Vision if Docling detected at least one picture/figure region covering 12% or more
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

If text looks like shifted or nonsense characters, the PDF text layer may be bad even though the
visible slide text is readable. The service profile already forces visual OCR to reduce this issue.

### Docling server offline

Confirm Docker is running and Docling Serve is listening on `http://localhost:5001`.

### Gotenberg server offline

PowerPoint uploads require Gotenberg at `http://localhost:3000`.

### CORS error

Use the default `/docling` and `/gotenberg` proxies during Vite development.

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
