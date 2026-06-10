const DATA_URI_PATTERN = /^data:image\/[a-zA-Z0-9.+-]+;base64,/;
const BASE64_PATTERN = /^[A-Za-z0-9+/]+={0,2}$/;

export const DEFAULT_VISION_FILTERS = {
  minPictureBoxes: 1,
  minPictureAreaPercent: 12,
  minResidualRatioPercent: 30,
  minEdgeRatioPercent: 10,
  textMaskPadding: 3,
  minTextBoxesToMask: 1,
  maxRepeatCount: 1,
  enableResidualFallback: false,
};

export function normalizeVisionFilters(filters = {}) {
  return {
    ...DEFAULT_VISION_FILTERS,
    ...filters,
    minPictureBoxes: Number(filters.minPictureBoxes ?? DEFAULT_VISION_FILTERS.minPictureBoxes),
    minPictureAreaPercent: Number(
      filters.minPictureAreaPercent ?? DEFAULT_VISION_FILTERS.minPictureAreaPercent,
    ),
    minResidualRatioPercent: Number(
      filters.minResidualRatioPercent ?? DEFAULT_VISION_FILTERS.minResidualRatioPercent,
    ),
    minEdgeRatioPercent: Number(filters.minEdgeRatioPercent ?? DEFAULT_VISION_FILTERS.minEdgeRatioPercent),
    textMaskPadding: Number(filters.textMaskPadding ?? DEFAULT_VISION_FILTERS.textMaskPadding),
    minTextBoxesToMask: Number(filters.minTextBoxesToMask ?? DEFAULT_VISION_FILTERS.minTextBoxesToMask),
    maxRepeatCount: Number(filters.maxRepeatCount ?? DEFAULT_VISION_FILTERS.maxRepeatCount),
    enableResidualFallback: Boolean(
      filters.enableResidualFallback ?? DEFAULT_VISION_FILTERS.enableResidualFallback,
    ),
  };
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function getPathValue(source, path) {
  return path.split(".").reduce((current, key) => {
    if (current === undefined || current === null) return undefined;
    return current[key];
  }, source);
}

function parseJsonIfPossible(value) {
  if (isObject(value) || Array.isArray(value)) return value;
  if (typeof value !== "string" || !value.trim()) return null;

  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function pickFirst(...values) {
  return values.find((value) => value !== undefined && value !== null && value !== "") ?? "";
}

function findStructuredDocument(response) {
  const commonPaths = [
    "result.document",
    "document",
    "result",
    "result.document.json_content",
    "document.json_content",
    "json_content",
    "result.json",
    "json",
  ];

  for (const path of commonPaths) {
    const value = getPathValue(response, path);
    const parsed = parseJsonIfPossible(value);

    if (parsed && (parsed.body || parsed.texts || parsed.tables || parsed.pictures)) {
      return parsed;
    }
  }

  return response;
}

function getSelfRef(item) {
  return pickFirst(item.self_ref, item.selfRef, item.ref, item.$ref);
}

function getPageNo(item) {
  return pickFirst(
    item.prov?.[0]?.page_no,
    item.prov?.[0]?.page,
    item.page_no,
    item.pageNumber,
    item.page_number,
    item.page,
  );
}

function inferPageNumberFromPath(sourcePath) {
  const match = String(sourcePath).match(/(?:^|\.)pages(?:\.|\[)(\d+)/);
  return match ? Number(match[1]) : "";
}

function normalizePageNumber(value) {
  if (value === undefined || value === null || value === "") return null;
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : value;
}

function getTextContent(item) {
  return pickFirst(item.text, item.orig, item.content, item.value, item.markdown, item.md);
}

function getItemLabel(item, fallback = "") {
  return String(pickFirst(item.label, item.type, item.kind, fallback)).toLowerCase();
}

function isPictureLike(item, sourcePath) {
  const label = getItemLabel(item);
  const path = String(sourcePath).toLowerCase();

  if (path.includes(".pages.") || path.includes(".pages[")) return false;

  return (
    label.includes("picture") ||
    label.includes("figure") ||
    label.includes("chart") ||
    label.includes("diagram") ||
    label.includes("image")
  );
}

function getPageSize(item) {
  const width = pickFirst(
    item.size?.width,
    item.page_size?.width,
    item.pageSize?.width,
    item.dimension?.width,
    item.dimensions?.width,
    item.width,
  );
  const height = pickFirst(
    item.size?.height,
    item.page_size?.height,
    item.pageSize?.height,
    item.dimension?.height,
    item.dimensions?.height,
    item.height,
  );

  if (!width || !height) return null;

  return {
    width: Number(width),
    height: Number(height),
  };
}

function normalizeBbox(bbox) {
  if (!bbox || typeof bbox !== "object") return null;

  const left = pickFirst(bbox.l, bbox.left, bbox.x0, bbox.x);
  const right = pickFirst(bbox.r, bbox.right, bbox.x1);
  const top = pickFirst(bbox.t, bbox.top, bbox.y1);
  const bottom = pickFirst(bbox.b, bbox.bottom, bbox.y0, bbox.y);

  if ([left, right, top, bottom].some((value) => value === "")) return null;

  return {
    l: Number(left),
    r: Number(right),
    t: Number(top),
    b: Number(bottom),
    coordOrigin: String(bbox.coord_origin || bbox.coordOrigin || "BOTTOMLEFT").toUpperCase(),
  };
}

function getBboxFromProv(prov) {
  return normalizeBbox(prov?.bbox || prov?.box || prov);
}

function stringifyCaption(caption) {
  if (!caption) return "";
  if (typeof caption === "string") return caption;
  if (Array.isArray(caption)) return caption.map(stringifyCaption).filter(Boolean).join(" ");
  if (isObject(caption)) return pickFirst(caption.text, caption.content, caption.value);
  return String(caption);
}

function getCaption(item) {
  return pickFirst(
    stringifyCaption(item.caption),
    stringifyCaption(item.captions),
    item.text,
    item.title,
    item.description,
  );
}

function normalizeMimeType(value) {
  const mimeType = String(value || "").trim();
  if (mimeType.startsWith("image/")) return mimeType;
  if (mimeType.includes("jpeg") || mimeType.includes("jpg")) return "image/jpeg";
  if (mimeType.includes("webp")) return "image/webp";
  if (mimeType.includes("gif")) return "image/gif";
  return "image/png";
}

function normalizeImageSource(value, mimeType) {
  if (typeof value !== "string") return "";

  const source = value.trim();
  if (!source) return "";
  if (DATA_URI_PATTERN.test(source)) return source;

  const compactSource = source.replace(/\s/g, "");
  if (compactSource.length > 100 && BASE64_PATTERN.test(compactSource)) {
    return `data:${normalizeMimeType(mimeType)};base64,${compactSource}`;
  }

  return "";
}

function getEmbeddedImageSource(item) {
  const mimeType = pickFirst(
    item.image?.mimetype,
    item.image?.mime_type,
    item.image?.mimeType,
    item.mimetype,
    item.mime_type,
    item.mimeType,
  );

  return pickFirst(
    normalizeImageSource(item.image?.uri, mimeType),
    normalizeImageSource(item.image?.data, mimeType),
    normalizeImageSource(item.image?.base64, mimeType),
    normalizeImageSource(item.uri, mimeType),
    normalizeImageSource(item.base64, mimeType),
    normalizeImageSource(item.data?.uri, mimeType),
    normalizeImageSource(item.data?.base64, mimeType),
  );
}

function hashString(value) {
  let hash = 5381;

  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 33) ^ value.charCodeAt(index);
  }

  return (hash >>> 0).toString(16);
}

export function getVisionSkipReasons({ analysis, repeatCount, filters }) {
  const reasons = [];
  const normalizedFilters = normalizeVisionFilters(filters);
  const minResidualRatio = normalizedFilters.minResidualRatioPercent / 100;
  const minEdgeRatio = normalizedFilters.minEdgeRatioPercent / 100;
  const minPictureAreaRatio = normalizedFilters.minPictureAreaPercent / 100;

  if (analysis?.status === "error") {
    reasons.push("load failed");
    return reasons;
  }

  if (!analysis || analysis.status !== "ready") {
    reasons.push("analyzing");
    return reasons;
  }

  if (repeatCount > normalizedFilters.maxRepeatCount) reasons.push(`repeated ${repeatCount}x`);

  if (analysis.pictureBoxCount < normalizedFilters.minPictureBoxes) {
    reasons.push(`picture boxes < ${normalizedFilters.minPictureBoxes}`);
  }

  if (analysis.pictureAreaRatio < minPictureAreaRatio) {
    reasons.push(`picture area < ${normalizedFilters.minPictureAreaPercent}%`);
  }

  const hasPictureEvidence =
    analysis.pictureBoxCount >= normalizedFilters.minPictureBoxes &&
    analysis.pictureAreaRatio >= minPictureAreaRatio;
  const hasResidualContent =
    normalizedFilters.enableResidualFallback &&
    analysis.textBoxCount >= normalizedFilters.minTextBoxesToMask &&
    (analysis.residualRatio >= minResidualRatio || analysis.edgeRatio >= minEdgeRatio);

  if (!hasPictureEvidence && !hasResidualContent) {
    reasons.push("below vision threshold");
  }

  return reasons;
}

export function appendKeptImagesToMarkdown(markdown, decisions) {
  const keptImages = decisions.filter((decision) => decision.isKept);

  if (!keptImages.length) return markdown;

  const imagesByPage = new Map();

  keptImages.forEach((decision) => {
    const pageKey = decision.image.pageNumber ? String(decision.image.pageNumber) : "Unknown";
    if (!imagesByPage.has(pageKey)) {
      imagesByPage.set(pageKey, []);
    }
    imagesByPage.get(pageKey).push(decision);
  });

  function formatVisionImage({ image, analysis }, index) {
    const pageText = image.pageNumber ? `Page ${image.pageNumber}` : "Page Unknown";
    const altText = `${pageText} vision image ${index + 1}`;
    const caption = image.caption ? `\n${image.caption}` : "";
    const scoreLine = analysis
      ? `\nPicture regions: ${analysis.pictureBoxCount}, picture area: ${(
          analysis.pictureAreaRatio * 100
        ).toFixed(2)}%, residual score: ${(analysis.residualRatio * 100).toFixed(2)}%`
      : "";

    return `### Vision Image${caption}${scoreLine}\n\n![${altText}](${image.source})`;
  }

  const sections = markdown.trim().split(/\n\n---\n\n/);
  const renderedSections = sections.map((section) => {
    const pageMatch = section.match(/^\[Page ([^\]]+)\]/);
    const pageKey = pageMatch?.[1] || "";
    const pageImages = imagesByPage.get(pageKey);

    if (!pageImages?.length) return section;

    imagesByPage.delete(pageKey);

    return `${section.trim()}\n\n${pageImages.map(formatVisionImage).join("\n\n")}`;
  });

  if (imagesByPage.size) {
    const unmatchedImages = Array.from(imagesByPage.values())
      .flat()
      .map((decision, index) => {
        const pageText = decision.image.pageNumber ? `Page ${decision.image.pageNumber}` : "Page Unknown";
        return `[${pageText}]\n\n${formatVisionImage(decision, index)}`;
      });

    renderedSections.push(...unmatchedImages);
  }

  return renderedSections.join("\n\n---\n\n");
}

function collectPictureAreas(root) {
  const pictureAreas = new Map();
  const seen = new WeakSet();

  function addPictureArea(pageNumber, area) {
    const normalizedPageNumber = normalizePageNumber(pageNumber);
    if (!normalizedPageNumber || !area?.bbox) return;

    if (!pictureAreas.has(normalizedPageNumber)) {
      pictureAreas.set(normalizedPageNumber, []);
    }

    pictureAreas.get(normalizedPageNumber).push(area);
  }

  function visit(value, sourcePath = "document", inheritedPageNo = "") {
    if (!isObject(value) && !Array.isArray(value)) return;

    if (typeof value === "object" && value !== null) {
      if (seen.has(value)) return;
      seen.add(value);
    }

    if (Array.isArray(value)) {
      value.forEach((item, index) => visit(item, `${sourcePath}[${index}]`, inheritedPageNo));
      return;
    }

    const pageNumber = getPageNo(value) || inferPageNumberFromPath(sourcePath) || inheritedPageNo;

    if (isPictureLike(value, sourcePath) && Array.isArray(value.prov)) {
      value.prov.forEach((prov) => {
        addPictureArea(prov.page_no || pageNumber, {
          bbox: getBboxFromProv(prov),
          label: getItemLabel(value),
          sourcePath,
        });
      });
    }

    Object.entries(value).forEach(([key, nestedValue]) => {
      visit(nestedValue, `${sourcePath}.${key}`, pageNumber);
    });
  }

  visit(root);

  return pictureAreas;
}

function collectPageSizes(root) {
  const pageSizes = new Map();

  function addPageSize(pageNumber, value) {
    const normalizedPageNumber = normalizePageNumber(pageNumber);
    const pageSize = getPageSize(value);

    if (normalizedPageNumber && pageSize?.width && pageSize?.height) {
      pageSizes.set(normalizedPageNumber, pageSize);
    }
  }

  if (isObject(root?.pages)) {
    Object.entries(root.pages).forEach(([pageNumber, page]) => addPageSize(pageNumber, page));
  }

  if (Array.isArray(root?.pages)) {
    root.pages.forEach((page, index) => addPageSize(getPageNo(page) || index + 1, page));
  }

  return pageSizes;
}

function collectTextAreas(root) {
  const textAreas = new Map();
  const seen = new WeakSet();

  function addTextArea(pageNumber, area) {
    const normalizedPageNumber = normalizePageNumber(pageNumber);
    if (!normalizedPageNumber || !area) return;

    if (!textAreas.has(normalizedPageNumber)) {
      textAreas.set(normalizedPageNumber, []);
    }

    textAreas.get(normalizedPageNumber).push(area);
  }

  function visit(value, sourcePath = "document", inheritedPageNo = "") {
    if (!isObject(value) && !Array.isArray(value)) return;

    if (typeof value === "object" && value !== null) {
      if (seen.has(value)) return;
      seen.add(value);
    }

    if (Array.isArray(value)) {
      value.forEach((item, index) => visit(item, `${sourcePath}[${index}]`, inheritedPageNo));
      return;
    }

    const pageNumber = getPageNo(value) || inferPageNumberFromPath(sourcePath) || inheritedPageNo;
    const text = String(getTextContent(value) || "").trim();

    if (text && Array.isArray(value.prov)) {
      value.prov.forEach((prov) => {
        const bbox = getBboxFromProv(prov);
        addTextArea(prov.page_no || pageNumber, {
          bbox,
          text,
          sourcePath,
        });
      });
    }

    Object.entries(value).forEach(([key, nestedValue]) => {
      visit(nestedValue, `${sourcePath}.${key}`, pageNumber);
    });
  }

  visit(root);

  return textAreas;
}

function inferMissingPageSizes(pageSizes, textAreas) {
  textAreas.forEach((areas, pageNumber) => {
    if (pageSizes.has(pageNumber)) return;

    const bounds = areas.reduce(
      (current, area) => {
        if (!area.bbox) return current;

        return {
          width: Math.max(current.width, area.bbox.l, area.bbox.r),
          height: Math.max(current.height, area.bbox.t, area.bbox.b),
        };
      },
      { width: 0, height: 0 },
    );

    if (bounds.width && bounds.height) {
      pageSizes.set(pageNumber, bounds);
    }
  });
}

export function extractEmbeddedImages(response) {
  const root = findStructuredDocument(response);
  const images = [];
  const seenObjects = new WeakSet();
  const seenKeys = new Set();
  const pageSizes = collectPageSizes(root);
  const textAreas = collectTextAreas(root);
  const pictureAreas = collectPictureAreas(root);
  inferMissingPageSizes(pageSizes, textAreas);

  function visit(value, sourcePath = "document", inheritedPageNo = "") {
    if (!isObject(value) && !Array.isArray(value)) return;

    if (typeof value === "object" && value !== null) {
      if (seenObjects.has(value)) return;
      seenObjects.add(value);
    }

    if (Array.isArray(value)) {
      value.forEach((item, index) => visit(item, `${sourcePath}[${index}]`, inheritedPageNo));
      return;
    }

    const pageNumber =
      normalizePageNumber(getPageNo(value) || inferPageNumberFromPath(sourcePath) || inheritedPageNo) ||
      null;
    const source = getEmbeddedImageSource(value);

    if (source) {
      const fingerprint = hashString(source.replace(DATA_URI_PATTERN, ""));
      const ref = getSelfRef(value);
      const key = `${pageNumber || "unknown"}-${fingerprint}`;

      if (!seenKeys.has(key)) {
        seenKeys.add(key);
        images.push({
          id: ref || `${sourcePath}-${images.length + 1}`,
          pageNumber,
          caption: getCaption(value),
          source,
          sourcePath,
          fingerprint,
          reference: ref,
          pageSize: pageSizes.get(pageNumber) || null,
          textAreas: textAreas.get(pageNumber) || [],
          pictureAreas: pictureAreas.get(pageNumber) || [],
          byteEstimate: Math.round((source.length * 3) / 4),
        });
      }
    }

    Object.entries(value).forEach(([key, nestedValue]) => {
      visit(nestedValue, `${sourcePath}.${key}`, pageNumber);
    });
  }

  visit(root);

  return images;
}
