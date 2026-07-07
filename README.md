# SlideVision Markdown Extractor

Docker-free local service for turning slide PDFs and presentations into page-aware Markdown.

The pipeline is intentionally local-first:

```text
PDF / PPT / PPTX / ODP
-> local LibreOffice conversion when needed
-> PyMuPDF4LLM structured Markdown extraction
-> RapidOCR for pages with missing or broken text
-> visual-rich slides selected by threshold
-> OpenCode Go vision description on cache misses
-> teaching-ready Markdown with text descriptions inserted per page
```

Rendered slide images are used internally for visual understanding and hashing. The final Markdown
does not need to carry base64 images once visual descriptions have been generated.

## Output Shape

```md
[Page 4]

Extracted slide text, headings, bullets, and tables...

### Visual Explanation

This slide shows a neural network architecture with features flowing through hidden layers toward an
output prediction.

Teaching note:
Use this visual to explain that each layer transforms the previous representation into a more useful
form for the final task.
```

Pages without large visual regions stay text-only. Before visual descriptions are generated, the app
shows the local OCR Markdown only.

## Requirements

- Windows 10/11
- Node.js 18+
- Python 3.11, 3.12, or 3.13, 64-bit
- LibreOffice, for PPT/PPTX/ODP conversion
- npm

Docker is not required.

## New PC Setup

1. Install Node.js 18+.
2. Install Python 3.11, 3.12, or 3.13.
3. Install LibreOffice from `https://www.libreoffice.org/download/download-libreoffice/`.
4. Add LibreOffice to PATH, or configure its path in `.env.local`:

```text
LIBREOFFICE_PATH=C:\Program Files\LibreOffice\program\soffice.com
```

5. Install JavaScript dependencies:

```bash
npm install
```

6. Create and fill the Python virtual environment:

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-local-extractor.txt
```

7. Start everything with one command:

```bash
npm run dev
```

Open the Vite URL shown in the terminal, usually:

```text
http://localhost:5173
```

`npm run dev` starts both the React app and the local Python extractor. The extractor also starts a
headless LibreOffice listener so presentation conversion does not pay the full startup cost each time.

## Optional Environment

Create `.env.local` if the defaults need changing:

```text
LOCAL_EXTRACTOR_PORT=5052
LOCAL_EXTRACTOR_IMAGES_SCALE=2
LOCAL_EXTRACTOR_MAX_IMAGES_SCALE=3
LOCAL_EXTRACTOR_OCR_LANGUAGE=eng
LOCAL_EXTRACTOR_FORCE_OCR_RETRY=true
LIBREOFFICE_PATH=C:\Program Files\LibreOffice\program\soffice.com
VITE_LOCAL_EXTRACTOR_TIMEOUT_MS=600000

OPENCODE_API_KEY=your_opencode_go_key
OPENCODE_VISION_MODEL=mimo-v2.5
OPENCODE_VISION_TIMEOUT_MS=90000
OPENCODE_VISION_MAX_TOKENS=700
OPENCODE_VISION_TEMPERATURE=0.2
OPENCODE_VISION_CONCURRENCY=1
OPENCODE_VISION_PAGE_TEXT_CHARS=1800
OPENCODE_VISION_PROMPT_VERSION=v1
SLIDEVISION_CACHE_NAMESPACE=default
SLIDEVISION_CACHE_PATH=data/slidevision-cache.sqlite

VITE_VISUAL_MIN_PICTURE_AREA_PERCENT=12
VITE_VISUAL_MIN_PICTURE_BOXES=1
VITE_VISUAL_ENABLE_RESIDUAL_FALLBACK=false
```

Useful notes:

- `LOCAL_EXTRACTOR_IMAGES_SCALE` controls rendered slide image size.
- The visual threshold controls which rendered slides are sent for description.
- OpenCode calls are cached by namespace, slide image hash, model, and prompt version.
- Increase `OPENCODE_VISION_PROMPT_VERSION` when changing the visual-description prompt.
- Use `SLIDEVISION_CACHE_NAMESPACE` for an instructor or tenant id once the product has accounts.
- RapidOCR is the only OCR engine used by this MVP.
- The first RapidOCR run may take longer while models initialize.

## Manual Service Debugging

Normally this is not needed, but the Python service can be started by itself:

```bash
npm run dev:extractor
```

Health check:

```text
http://127.0.0.1:5052/health
```

The health response reports:

- PyMuPDF and PyMuPDF4LLM versions
- whether RapidOCR is available
- LibreOffice path
- whether the LibreOffice listener is running
- OpenCode model/cache configuration

## OpenCode Vision Probe

After adding `OPENCODE_API_KEY` to `.env.local`, test image support with:

```bash
npm run probe:opencode
```

You can also test a specific model:

```bash
npm run probe:opencode -- mimo-v2.5
```

The app uses `mimo-v2.5` by default for visual descriptions because it has been verified to accept
image input through the OpenCode Go `chat/completions` endpoint.

## Build

```bash
npm run build
```

Preview the production build:

```bash
npm run preview
```

For production deployment, run the Python extractor as a service and point
`VITE_LOCAL_EXTRACTOR_BASE_URL` at that service.
