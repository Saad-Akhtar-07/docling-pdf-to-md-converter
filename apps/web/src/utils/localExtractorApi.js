export const LOCAL_EXTRACTOR_PROXY_BASE_URL = "/local-extractor";
export const DEFAULT_LOCAL_EXTRACTOR_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || LOCAL_EXTRACTOR_PROXY_BASE_URL;

const CONVERT_PATH = "/v1/convert/file";
const DEFAULT_TIMEOUT_MS = Number(import.meta.env.VITE_LOCAL_EXTRACTOR_TIMEOUT_MS || 600_000);
const DEFAULT_IMAGES_SCALE = Number(import.meta.env.VITE_LOCAL_EXTRACTOR_IMAGES_SCALE || 2);

function normalizeBaseUrl(baseUrl) {
  return baseUrl.replace(/\/$/, "");
}

function buildFormData(file) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("images_scale", String(DEFAULT_IMAGES_SCALE));
  return formData;
}

function buildErrorMessage(error) {
  if (error.name === "AbortError") {
    return "The local extractor request timed out. Large slide decks can take a while; increase VITE_LOCAL_EXTRACTOR_TIMEOUT_MS if needed.";
  }

  if (error.message?.includes("Failed to fetch")) {
    return "Could not reach the local extractor. Start the app with `npm run dev` so Vite can launch the Python service.";
  }

  return error.message || "Local extraction failed.";
}

export async function convertFileWithLocalExtractor({
  file,
  baseUrl = DEFAULT_LOCAL_EXTRACTOR_BASE_URL,
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

    const responseClone = response.clone();
    const body = await response.json().catch(async () => ({ error: await responseClone.text() }));

    if (!response.ok) {
      throw new Error(body?.detail || body?.error || `Local extractor returned HTTP ${response.status}.`);
    }

    return body;
  } catch (error) {
    throw new Error(buildErrorMessage(error));
  } finally {
    window.clearTimeout(timeoutId);
  }
}
