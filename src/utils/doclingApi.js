export const DOCLING_DIRECT_BASE_URL = "http://localhost:5001";
export const DOCLING_PROXY_BASE_URL = "/docling";
export const DEFAULT_DOCLING_BASE_URL =
  import.meta.env.VITE_DOCLING_BASE_URL || DOCLING_PROXY_BASE_URL;

const CONVERT_PATH = "/v1/convert/file";
const DEFAULT_TIMEOUT_MS = Number(import.meta.env.VITE_DOCLING_TIMEOUT_MS || 600_000);

export const SERVICE_CONVERSION_OPTIONS = {
  doOcr: true,
  forceOcr: true,
  doTableStructure: true,
  tableMode: "accurate",
  includeImages: true,
  imagesScale: 2,
};

function normalizeBaseUrl(baseUrl) {
  return baseUrl.replace(/\/$/, "");
}

function appendFormValue(formData, key, value) {
  if (Array.isArray(value)) {
    value.forEach((item) => formData.append(key, item));
    return;
  }

  if (typeof value === "boolean") {
    formData.append(key, String(value));
    return;
  }

  if (value !== undefined && value !== null && value !== "") {
    formData.append(key, value);
  }
}

function buildFormData(file) {
  const formData = new FormData();
  formData.append("files", file);
  formData.append("file", file);

  const toFormats = ["md", "json"];

  const payload = {
    to_formats: toFormats,
    do_ocr: SERVICE_CONVERSION_OPTIONS.doOcr,
    force_ocr: SERVICE_CONVERSION_OPTIONS.forceOcr,
    do_table_structure: SERVICE_CONVERSION_OPTIONS.doTableStructure,
    table_mode: SERVICE_CONVERSION_OPTIONS.tableMode,
    image_export_mode: "embedded",
    include_images: SERVICE_CONVERSION_OPTIONS.includeImages,
    images_scale: SERVICE_CONVERSION_OPTIONS.imagesScale,
  };

  Object.entries(payload).forEach(([key, value]) => appendFormValue(formData, key, value));

  // Some Docling Serve builds prefer a JSON options part, while others accept flat form fields.
  formData.append("options", JSON.stringify(payload));

  return formData;
}

function buildErrorMessage(error) {
  if (error.name === "AbortError") {
    return "The browser request timed out. Large slide PDFs can take a while; increase VITE_DOCLING_TIMEOUT_MS and DOCLING_SERVE_MAX_SYNC_WAIT if needed.";
  }

  if (error.message?.includes("Failed to fetch")) {
    return "Could not reach Docling Serve. Make sure Docker is running and Docling Serve is available at http://localhost:5001. If this is a browser CORS issue, keep using the /docling Vite proxy.";
  }

  return error.message || "Docling conversion failed.";
}

export async function convertPdfWithDocling({
  file,
  baseUrl = DEFAULT_DOCLING_BASE_URL,
  timeoutMs = DEFAULT_TIMEOUT_MS,
}) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${normalizeBaseUrl(baseUrl)}${CONVERT_PATH}`, {
      method: "POST",
      body: buildFormData(file),
      signal: controller.signal,
    });

    const contentType = response.headers.get("content-type") || "";
    const responseBody = contentType.includes("application/json")
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      const serverMessage =
        typeof responseBody === "string"
          ? responseBody
          : responseBody?.detail || responseBody?.message || JSON.stringify(responseBody);
      throw new Error(`Docling returned HTTP ${response.status}: ${serverMessage}`);
    }

    if (typeof responseBody === "string") {
      try {
        return JSON.parse(responseBody);
      } catch {
        return { markdown: responseBody };
      }
    }

    return responseBody;
  } catch (error) {
    throw new Error(buildErrorMessage(error));
  } finally {
    window.clearTimeout(timeoutId);
  }
}
