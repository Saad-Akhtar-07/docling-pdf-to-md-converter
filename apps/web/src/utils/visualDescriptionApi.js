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

function toHashOnlyPayload(decision) {
  const { image } = decision;
  return {
    id: image.id,
    pageNumber: image.pageNumber,
    slideHash: image.slideHash || image.fingerprint,
  };
}

function emptyResult(model) {
  return {
    provider: "opencode-go",
    model,
    descriptions: [],
    cache: { hits: 0, misses: 0, failures: 0 },
  };
}

/**
 * Step 1: Ask the backend which slide hashes are already cached.
 * Sends only hashes (< 1 KB) — no base64 image data.
 */
async function lookupCachedDescriptions({
  slideHashes,
  model,
  baseUrl,
  signal,
}) {
  if (!slideHashes.length) return { cached: [], missing: [] };

  const response = await fetch(`${normalizeBaseUrl(baseUrl)}/v1/visual-descriptions/lookup`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ slideHashes, model }),
    signal,
  });

  const responseClone = response.clone();
  const body = await response.json().catch(async () => ({ error: await responseClone.text() }));

  if (!response.ok) {
    // Non-fatal: fall back to sending all images
    console.warn("Cache lookup failed, will send all images:", body?.error || body?.detail);
    return { cached: [], missing: slideHashes };
  }

  return body;
}

/**
 * Step 2: Send only images that were NOT in cache and get fresh descriptions.
 */
async function describeUncachedSlides({
  images,
  pageTextByNumber,
  model,
  baseUrl,
  timeoutMs,
  signal,
}) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  const combinedSignal = signal || controller.signal;

  try {
    const response = await fetch(`${normalizeBaseUrl(baseUrl)}/v1/visual-descriptions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ images, pageTextByNumber, model }),
      signal: combinedSignal,
    });

    const responseClone = response.clone();
    const body = await response.json().catch(async () => ({ error: await responseClone.text() }));

    if (!response.ok) {
      throw new Error(body?.detail || body?.error || `Visual description service returned HTTP ${response.status}.`);
    }

    return body;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

/**
 * Main entry point. Uses a lookup-first pattern:
 * 1. Send slide hashes → receive cached/missing split (tiny request)
 * 2. Send base64 images only for the missing slides (saves bandwidth)
 * 3. Merge results and return unified response
 */
export async function describeVisualSlides({
  decisions,
  pageTextByNumber,
  baseUrl = DEFAULT_LOCAL_EXTRACTOR_BASE_URL,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  model = DEFAULT_MODEL,
}) {
  const keptDecisions = decisions.filter((d) => d.isKept);

  if (!keptDecisions.length) {
    return emptyResult(model);
  }

  const allImages = keptDecisions.map(toImagePayload);
  const allHashes = allImages.map((img) => img.slideHash).filter(Boolean);

  // --- Phase 3: Hash-only lookup first ---
  const lookupResult = await lookupCachedDescriptions({
    slideHashes: allHashes,
    model,
    baseUrl,
  });

  const cachedByHash = new Map(
    (lookupResult.cached || []).map((d) => [d.slideHash, d]),
  );

  // Only images whose hash wasn't in the cache need full upload
  const missingImages = allImages.filter(
    (img) => img.slideHash && !cachedByHash.has(img.slideHash),
  );

  // Images with no slideHash still need to be sent (can't look them up)
  const unHashableImages = allImages.filter((img) => !img.slideHash);
  const imagesToSend = [...missingImages, ...unHashableImages];

  let freshDescriptions = [];
  let rawCache = { hits: cachedByHash.size, misses: imagesToSend.length, failures: 0 };

  if (imagesToSend.length) {
    try {
      const freshResult = await describeUncachedSlides({
        images: imagesToSend,
        pageTextByNumber,
        model,
        baseUrl,
        timeoutMs,
      });
      freshDescriptions = freshResult.descriptions || [];
      // Merge backend-reported cache stats with our lookup stats
      const bc = freshResult.cache || {};
      rawCache = {
        hits: (cachedByHash.size) + (bc.hits || 0),
        misses: (bc.misses || imagesToSend.length),
        failures: bc.failures || 0,
      };
    } catch (error) {
      if (error.name === "AbortError") {
        throw new Error("Visual description request timed out. Increase VITE_OPENCODE_VISION_TIMEOUT_MS if needed.");
      }
      if (error.message?.includes("Failed to fetch")) {
        throw new Error("Could not reach the local visual description service. Restart with `npm run dev`.");
      }
      throw error;
    }
  }

  // Merge: cached descriptions + fresh descriptions, preserving slide order
  const freshByHash = new Map(
    freshDescriptions.map((d) => [d.slideHash, d]),
  );

  const orderedDescriptions = allImages.map((img) => {
    if (img.slideHash && cachedByHash.has(img.slideHash)) {
      return { ...cachedByHash.get(img.slideHash), id: img.id, pageNumber: img.pageNumber };
    }
    if (img.slideHash && freshByHash.has(img.slideHash)) {
      return freshByHash.get(img.slideHash);
    }
    // Fallback: find by id in fresh results
    return freshDescriptions.find((d) => d.id === img.id) || null;
  }).filter(Boolean);

  return {
    provider: "opencode-go",
    model,
    descriptions: orderedDescriptions,
    cache: rawCache,
  };
}
