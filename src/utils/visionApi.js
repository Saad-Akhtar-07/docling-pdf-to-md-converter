const DEFAULT_VISION_API_BASE_URL = import.meta.env.VITE_VISION_API_BASE_URL || "/api/vision";

function normalizeBaseUrl(baseUrl) {
  return baseUrl.replace(/\/$/, "");
}

function toImagePayload(decision) {
  const { image, analysis } = decision;

  return {
    id: image.id,
    fingerprint: image.fingerprint,
    pageNumber: image.pageNumber,
    caption: image.caption,
    source: image.source,
    sourcePath: image.sourcePath,
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

export async function describeVisionCandidates({
  decisions,
  pageTextByNumber,
  baseUrl = DEFAULT_VISION_API_BASE_URL,
}) {
  const images = decisions.filter((decision) => decision.isKept).map(toImagePayload);

  if (!images.length) {
    return {
      provider: "groq",
      model: "",
      descriptions: [],
    };
  }

  let response;

  try {
    response = await fetch(`${normalizeBaseUrl(baseUrl)}/describe-batch`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify({
        images,
        pageTextByNumber,
      }),
    });
  } catch {
    throw new Error(
      "Vision service is not reachable. Restart the app with `npm run dev` so Vite can load the server-side Vision API.",
    );
  }

  const body = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(body.error || `Vision service returned HTTP ${response.status}.`);
  }

  return body;
}
