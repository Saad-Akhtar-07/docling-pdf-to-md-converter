export const LANGCHAIN_EXTRACTOR_DIRECT_BASE_URL = "http://localhost:5051";
export const LANGCHAIN_EXTRACTOR_PROXY_BASE_URL = "/langchain-extractor";
export const DEFAULT_LANGCHAIN_EXTRACTOR_BASE_URL =
  import.meta.env.VITE_LANGCHAIN_EXTRACTOR_BASE_URL || LANGCHAIN_EXTRACTOR_PROXY_BASE_URL;

const CONVERT_PATH = "/v1/convert/file";
const DEFAULT_TIMEOUT_MS = Number(import.meta.env.VITE_LANGCHAIN_EXTRACTOR_TIMEOUT_MS || 600_000);
const DEFAULT_IMAGES_SCALE = Number(import.meta.env.VITE_LANGCHAIN_EXTRACTOR_IMAGES_SCALE || 2);

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
    return "The browser request timed out. Large slide PDFs can take a while; increase VITE_LANGCHAIN_EXTRACTOR_TIMEOUT_MS if needed.";
  }

  if (error.message?.includes("Failed to fetch")) {
    return "Could not reach the LangChain/PyMuPDF extractor. Start it with `uvicorn server.langchainExtractorService:app --host 0.0.0.0 --port 5051`, or keep using the /langchain-extractor Vite proxy.";
  }

  return error.message || "LangChain/PyMuPDF extraction failed.";
}

export async function convertPdfWithLangChainExtractor({
  file,
  baseUrl = DEFAULT_LANGCHAIN_EXTRACTOR_BASE_URL,
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

    const body = await response.json().catch(async () => ({ error: await response.text() }));

    if (!response.ok) {
      throw new Error(body?.detail || body?.error || `LangChain/PyMuPDF returned HTTP ${response.status}.`);
    }

    return body;
  } catch (error) {
    throw new Error(buildErrorMessage(error));
  } finally {
    window.clearTimeout(timeoutId);
  }
}
