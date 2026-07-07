import { DEFAULT_LOCAL_EXTRACTOR_BASE_URL } from "./localExtractorApi.js";

const DEFAULT_TIMEOUT_MS = Number(import.meta.env.VITE_OPENCODE_VISION_TIMEOUT_MS || 120_000);
const DEFAULT_MODEL = import.meta.env.VITE_OPENCODE_VISION_MODEL || "mimo-v2.5";

function normalizeBaseUrl(baseUrl) {
  return baseUrl.replace(/\/$/, "");
}

function toImagePayload(decision) {
  const { image, analysis } = decision;

  return {
    id: image.id,
    pageNumber: image.pageNumber,
    caption: image.caption,
    source: image.source,
    slideHash: image.slideHash || image.fingerprint,
    fingerprint: image.fingerprint,
    byteEstimate: image.byteEstimate,
    metrics: analysis
      ? {
          pictureBoxCount: analysis.pictureBoxCount,
          pictureAreaRatio: analysis.pictureAreaRatio,
          residualRatio: analysis.residualRatio,
          edgeRatio: analysis.edgeRatio,
        }
      : null,
  };
}

export async function describeVisualSlides({
  decisions,
  pageTextByNumber,
  baseUrl = DEFAULT_LOCAL_EXTRACTOR_BASE_URL,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  model = DEFAULT_MODEL,
}) {
  const images = decisions.filter((decision) => decision.isKept).map(toImagePayload);

  if (!images.length) {
    return {
      provider: "opencode-go",
      model,
      descriptions: [],
      cache: {
        hits: 0,
        misses: 0,
        failures: 0,
      },
    };
  }

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${normalizeBaseUrl(baseUrl)}/v1/visual-descriptions`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify({
        images,
        pageTextByNumber,
        model,
      }),
      signal: controller.signal,
    });

    const body = await response.json().catch(async () => ({ error: await response.text() }));

    if (!response.ok) {
      throw new Error(body?.detail || body?.error || `Visual description service returned HTTP ${response.status}.`);
    }

    return body;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("Visual description request timed out. Increase VITE_OPENCODE_VISION_TIMEOUT_MS if needed.");
    }

    if (error.message?.includes("Failed to fetch")) {
      throw new Error("Could not reach the local visual description service. Restart with `npm run dev`.");
    }

    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}
