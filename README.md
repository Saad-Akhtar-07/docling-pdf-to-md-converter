# SlideVision Markdown Extractor

Docker-free local service for turning slide PDFs and presentations into page-aware Markdown.

The MVP pipeline is intentionally small:

```text
PDF / PPT / PPTX / ODP
-> local LibreOffice conversion when needed
-> PyMuPDF4LLM structured Markdown extraction
-> RapidOCR for pages with missing or broken text
-> full-slide image kept only when visual regions pass the threshold
-> final Markdown
```

The app no longer waits for a Vision LLM. If a slide has a large diagram, chart, or picture, the
rendered full slide is embedded directly in the Markdown so a downstream teaching model can inspect
it later.

## Output Shape

```md
[Page 4]

Extracted slide text, headings, bullets, and tables...

### Slide Image

Picture regions: 2, picture area: 34.22%, residual score: 18.91%

![Page 4 slide image 1](data:image/png;base64,...)
```

Pages without large visual regions stay text-only.

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
```

Useful notes:

- `LOCAL_EXTRACTOR_IMAGES_SCALE` controls rendered slide image size.
- The frontend keeps full-slide images only after the visual threshold check.
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
