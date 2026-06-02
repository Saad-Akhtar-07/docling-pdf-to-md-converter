export const DOCLING_DIRECT_BASE_URL = "http://localhost:5001";
export const DOCLING_PROXY_BASE_URL = "/docling";
export const DEFAULT_DOCLING_BASE_URL =
  import.meta.env.VITE_DOCLING_BASE_URL || DOCLING_PROXY_BASE_URL;

const CONVERT_PATH = "/v1/convert/file";
const DEFAULT_TIMEOUT_MS = 120_000;

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

function buildFormData(file, options) {
  const formData = new FormData();
  formData.append("files", file);
  formData.append("file", file);

  const toFormats = options.outputFormat === "both" ? ["md", "json"] : [options.outputFormat];

  const payload = {
    to_formats: toFormats,
    do_ocr: options.doOcr,
    force_ocr: options.forceOcr,
    do_table_structure: options.doTableStructure,
    table_mode: options.tableMode,
    image_export_mode: options.imageExportMode,
  };

  Object.entries(payload).forEach(([key, value]) => appendFormValue(formData, key, value));

  // Some Docling Serve builds prefer a JSON options part, while others accept flat form fields.
  formData.append("options", JSON.stringify(payload));

  return formData;
}

function buildErrorMessage(error) {
  if (error.name === "AbortError") {
    return "The conversion timed out. Large slide PDFs can take a while; try again or increase the timeout in src/utils/doclingApi.js.";
  }

  if (error.message?.includes("Failed to fetch")) {
    return "Could not reach Docling Serve. Make sure Docker is running and Docling Serve is available at http://localhost:5001. If this is a browser CORS issue, keep using the /docling Vite proxy.";
  }

  return error.message || "Docling conversion failed.";
}

export async function convertPdfWithDocling({
  file,
  options,
  baseUrl = DEFAULT_DOCLING_BASE_URL,
  timeoutMs = DEFAULT_TIMEOUT_MS,
}) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${normalizeBaseUrl(baseUrl)}${CONVERT_PATH}`, {
      method: "POST",
      body: buildFormData(file, options),
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
