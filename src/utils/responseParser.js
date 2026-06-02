const MARKDOWN_FIELD_NAMES = [
  "md_content",
  "markdown",
  "markdown_content",
  "md",
  "text_md",
  "content_md",
];

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function getPathValue(source, path) {
  return path.split(".").reduce((current, key) => {
    if (current === undefined || current === null) return undefined;
    return current[key];
  }, source);
}

function looksLikeMarkdown(value) {
  if (typeof value !== "string") return false;
  const trimmed = value.trim();
  if (trimmed.length < 20) return false;

  return (
    /^#{1,6}\s/m.test(trimmed) ||
    /^\s*[-*+]\s+/m.test(trimmed) ||
    /^\s*\|.+\|\s*$/m.test(trimmed) ||
    /```/.test(trimmed) ||
    /\n{2,}/.test(trimmed)
  );
}

function findFirstStringAtPaths(response, paths) {
  for (const path of paths) {
    const value = getPathValue(response, path);
    if (typeof value === "string" && value.trim()) {
      return { value, sourcePath: path };
    }
  }

  return { value: "", sourcePath: "" };
}

function findMarkdownByFieldName(value, sourcePath = "response", seen = new WeakSet()) {
  if (!isObject(value) && !Array.isArray(value)) return null;

  if (typeof value === "object" && value !== null) {
    if (seen.has(value)) return null;
    seen.add(value);
  }

  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      const found = findMarkdownByFieldName(value[index], `${sourcePath}[${index}]`, seen);
      if (found) return found;
    }
    return null;
  }

  for (const [key, nestedValue] of Object.entries(value)) {
    const lowerKey = key.toLowerCase();
    const currentPath = `${sourcePath}.${key}`;

    if (
      MARKDOWN_FIELD_NAMES.includes(lowerKey) &&
      typeof nestedValue === "string" &&
      nestedValue.trim()
    ) {
      return { value: nestedValue, sourcePath: currentPath };
    }
  }

  for (const [key, nestedValue] of Object.entries(value)) {
    const found = findMarkdownByFieldName(nestedValue, `${sourcePath}.${key}`, seen);
    if (found) return found;
  }

  return null;
}

function findMarkdownByContent(value, sourcePath = "response", seen = new WeakSet()) {
  if (typeof value === "string") {
    return looksLikeMarkdown(value) ? { value, sourcePath } : null;
  }

  if (!isObject(value) && !Array.isArray(value)) return null;

  if (typeof value === "object" && value !== null) {
    if (seen.has(value)) return null;
    seen.add(value);
  }

  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      const found = findMarkdownByContent(value[index], `${sourcePath}[${index}]`, seen);
      if (found) return found;
    }
    return null;
  }

  for (const [key, nestedValue] of Object.entries(value)) {
    const found = findMarkdownByContent(nestedValue, `${sourcePath}.${key}`, seen);
    if (found) return found;
  }

  return null;
}

function pickFirst(...values) {
  return values.find((value) => value !== undefined && value !== null && value !== "") ?? "";
}

function maybeFigureLike(item) {
  if (!isObject(item)) return false;

  const searchable = `${item.type || ""} ${item.label || ""} ${item.name || ""} ${
    item.caption || ""
  }`.toLowerCase();

  return (
    searchable.includes("image") ||
    searchable.includes("figure") ||
    searchable.includes("picture") ||
    Boolean(item.image || item.uri || item.path || item.data || item.base64)
  );
}

function normalizeFigure(item, index) {
  const caption =
    typeof item.caption === "string"
      ? item.caption
      : Array.isArray(item.caption)
        ? item.caption.join(" ")
        : pickFirst(item.text, item.title, item.description);

  return {
    id: pickFirst(item.id, item.self_ref, item.ref, `figure-${index + 1}`),
    pageNumber: pickFirst(item.page, item.page_no, item.page_number, item.prov?.[0]?.page_no),
    caption,
    reference: pickFirst(
      item.uri,
      item.path,
      item.image?.uri,
      item.image?.path,
      item.image?.data,
      item.base64,
      item.data,
    ),
    type: pickFirst(item.type, item.label, item.kind, "figure"),
    raw: item,
  };
}

function collectFigures(value, figures = [], seen = new WeakSet()) {
  if (!isObject(value) && !Array.isArray(value)) return figures;

  if (typeof value === "object" && value !== null) {
    if (seen.has(value)) return figures;
    seen.add(value);
  }

  if (Array.isArray(value)) {
    value.forEach((item) => {
      if (maybeFigureLike(item)) {
        figures.push(normalizeFigure(item, figures.length));
      }
      collectFigures(item, figures, seen);
    });
    return figures;
  }

  Object.values(value).forEach((nestedValue) => collectFigures(nestedValue, figures, seen));
  return figures;
}

function maybeTableLike(item) {
  if (!isObject(item)) return false;

  const searchable = `${item.type || ""} ${item.label || ""} ${item.name || ""}`.toLowerCase();
  return (
    searchable.includes("table") ||
    Array.isArray(item.rows) ||
    Array.isArray(item.cells) ||
    Array.isArray(item.table_cells)
  );
}

function countTables(value, seen = new WeakSet()) {
  if (!isObject(value) && !Array.isArray(value)) return 0;

  if (typeof value === "object" && value !== null) {
    if (seen.has(value)) return 0;
    seen.add(value);
  }

  if (Array.isArray(value)) {
    return value.reduce((count, item) => count + (maybeTableLike(item) ? 1 : 0) + countTables(item, seen), 0);
  }

  return Object.values(value).reduce((count, nestedValue) => count + countTables(nestedValue, seen), 0);
}

export function extractMarkdown(response) {
  const commonPaths = [
    "result.document.md_content",
    "result.document.markdown",
    "result.markdown",
    "document.md_content",
    "document.markdown",
    "md_content",
    "markdown",
  ];

  const directMatch = findFirstStringAtPaths(response, commonPaths);
  if (directMatch.value) return directMatch;

  const fieldMatch = findMarkdownByFieldName(response);
  if (fieldMatch) return fieldMatch;

  const contentMatch = findMarkdownByContent(response);
  if (contentMatch) return contentMatch;

  return { value: "", sourcePath: "" };
}

export function extractFigures(response) {
  const figures = collectFigures(response);
  const unique = new Map();

  figures.forEach((figure) => {
    const key = `${figure.id}-${figure.pageNumber}-${figure.reference}-${figure.caption}`;
    if (!unique.has(key)) unique.set(key, figure);
  });

  return Array.from(unique.values());
}

export function extractResponseSummary(response) {
  const figures = extractFigures(response);

  return {
    figures,
    tableCount: countTables(response),
  };
}
