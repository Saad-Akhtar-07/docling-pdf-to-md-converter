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

function parseJsonIfPossible(value) {
  if (isObject(value) || Array.isArray(value)) return value;
  if (typeof value !== "string" || !value.trim()) return null;

  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
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
      return { document: parsed, sourcePath: path };
    }
  }

  return { document: null, sourcePath: "" };
}

function resolveJsonPointer(root, ref) {
  if (typeof ref !== "string" || !ref.startsWith("#/")) return null;

  return ref
    .slice(2)
    .split("/")
    .reduce((current, segment) => {
      if (current === undefined || current === null) return null;
      const key = segment.replace(/~1/g, "/").replace(/~0/g, "~");
      return current[key];
    }, root);
}

function getSelfRef(item) {
  return pickFirst(item.self_ref, item.selfRef, item.ref, item.$ref);
}

function flattenBodyItems(root, node = root.body, items = [], seen = new WeakSet(), parentType = "") {
  if (!node) return items;

  const resolved = node.$ref ? resolveJsonPointer(root, node.$ref) : node;
  if (!resolved || typeof resolved !== "object") return items;
  if (seen.has(resolved)) return items;

  seen.add(resolved);

  const currentType = getItemType(resolved);
  const isFigureChildText = parentType === "figure" && currentType === "text";

  if (
    resolved !== root.body &&
    !isFigureChildText &&
    (resolved.prov || resolved.text || resolved.data || resolved.image)
  ) {
    items.push({
      item: resolved,
      sourcePath: node.$ref || getSelfRef(resolved) || "document.body",
    });
  }

  if (Array.isArray(resolved.children)) {
    resolved.children.forEach((child) => flattenBodyItems(root, child, items, seen, currentType));
  }

  return items;
}

function collectKnownDocumentArrays(root) {
  const collections = [
    ["texts", "text"],
    ["tables", "table"],
    ["pictures", "figure"],
    ["figures", "figure"],
    ["images", "figure"],
  ];

  return collections.flatMap(([key, fallbackType]) => {
    const values = Array.isArray(root[key]) ? root[key] : [];

    return values.map((item, index) => ({
      item,
      sourcePath: `document.${key}[${index}]`,
      fallbackType,
    }));
  });
}

function getOrderedDocumentItems(root) {
  const orderedItems = flattenBodyItems(root);
  const knownItems = collectKnownDocumentArrays(root);
  const seenKeys = new Set();

  orderedItems.forEach(({ item, sourcePath }) => {
    seenKeys.add(getSelfRef(item) || sourcePath);
  });

  knownItems.forEach((knownItem) => {
    const key = getSelfRef(knownItem.item) || knownItem.sourcePath;
    if (!seenKeys.has(key)) {
      orderedItems.push(knownItem);
      seenKeys.add(key);
    }
  });

  return orderedItems;
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

function getItemLabel(item, fallbackType = "") {
  return String(pickFirst(item.label, item.type, item.kind, fallbackType)).toLowerCase();
}

function getItemType(item, fallbackType = "") {
  const label = getItemLabel(item, fallbackType);

  if (label.includes("table") || item.data?.table_cells || item.table_cells) return "table";
  if (
    label.includes("picture") ||
    label.includes("figure") ||
    label.includes("image") ||
    item.image ||
    item.uri ||
    item.base64
  ) {
    return "figure";
  }

  return "text";
}

function stringifyCaption(caption) {
  if (!caption) return "";
  if (typeof caption === "string") return caption;
  if (Array.isArray(caption)) return caption.map(stringifyCaption).filter(Boolean).join(" ");
  if (isObject(caption)) return pickFirst(caption.text, caption.content, caption.value);
  return String(caption);
}

function getFigureCaption(item) {
  return pickFirst(
    stringifyCaption(item.caption),
    stringifyCaption(item.captions),
    item.text,
    item.title,
    item.description,
  );
}

function getFigureReference(item) {
  return pickFirst(
    item.image?.uri,
    item.image?.path,
    item.image?.data,
    item.uri,
    item.path,
    item.base64,
    item.data?.uri,
    item.data?.path,
    getSelfRef(item),
  );
}

function getTextContent(item) {
  return pickFirst(item.text, item.orig, item.content, item.value, item.markdown, item.md);
}

function formatTextContent(item) {
  const label = getItemLabel(item);
  const text = String(getTextContent(item) || "").trim();
  if (!text) return "";

  if ((label.includes("title") || label.includes("section_header")) && !text.startsWith("#")) {
    return `## ${text}`;
  }

  if (label.includes("list") && !/^[-*+]\s+/.test(text)) {
    return `- ${text}`;
  }

  return text;
}

function tableCellsToMarkdown(data) {
  const cells = data?.table_cells || data?.cells || [];
  const rowCount = data?.num_rows || data?.row_count || 0;
  const colCount = data?.num_cols || data?.col_count || 0;

  if (!Array.isArray(cells) || !cells.length) return "";

  const maxRow =
    rowCount ||
    Math.max(...cells.map((cell) => cell.end_row_offset_idx ?? cell.row ?? cell.row_index ?? 0)) + 1;
  const maxCol =
    colCount ||
    Math.max(...cells.map((cell) => cell.end_col_offset_idx ?? cell.col ?? cell.col_index ?? 0)) + 1;

  const matrix = Array.from({ length: maxRow }, () => Array.from({ length: maxCol }, () => ""));

  cells.forEach((cell) => {
    const row = cell.start_row_offset_idx ?? cell.row ?? cell.row_index ?? 0;
    const col = cell.start_col_offset_idx ?? cell.col ?? cell.col_index ?? 0;
    matrix[row][col] = String(pickFirst(cell.text, cell.content, cell.value)).replace(/\s+/g, " ");
  });

  const rows = matrix.filter((row) => row.some((cell) => cell.trim()));
  if (!rows.length) return "";

  const header = rows[0];
  const separator = header.map(() => "---");
  const body = rows.slice(1);

  return [header, separator, ...body]
    .map((row) => `| ${row.map((cell) => cell.trim()).join(" | ")} |`)
    .join("\n");
}

function formatTableContent(item) {
  const directMarkdown = pickFirst(item.markdown, item.md, item.text);
  if (directMarkdown) return String(directMarkdown).trim();

  return tableCellsToMarkdown(item.data || item);
}

function collectFigureOcrText(root, item, seen = new WeakSet()) {
  if (!root || !Array.isArray(item.children)) return "";

  return item.children
    .map((child) => {
      const resolved = child.$ref ? resolveJsonPointer(root, child.$ref) : child;
      if (!resolved || typeof resolved !== "object" || seen.has(resolved)) return "";

      seen.add(resolved);

      if (getItemType(resolved) === "text") {
        return formatTextContent(resolved);
      }

      return collectFigureOcrText(root, resolved, seen);
    })
    .filter(Boolean)
    .join("\n\n");
}

function formatFigureContent(item, pageNo, root) {
  const pageLabel = pageNo || "Unknown";
  const caption = getFigureCaption(item);
  const reference = getFigureReference(item);
  const ocrText = collectFigureOcrText(root, item);
  const lines = [`[Figure on Page ${pageLabel}]`];

  if (ocrText) {
    lines.push("Extracted text from image OCR:", ocrText);
  }

  lines.push(caption ? `Caption: ${caption}` : "Caption:");
  lines.push(reference ? `Image reference: ${reference}` : "Image reference:");
  lines.push("TODO: send this image to Vision LLM only if OCR text is insufficient.");

  return lines.join("\n");
}

function buildChunk({ item, fallbackType, sourcePath, documentName, root }) {
  const type = getItemType(item, fallbackType);
  const pageNo = getPageNo(item);
  const content =
    type === "table"
      ? formatTableContent(item)
      : type === "figure"
        ? formatFigureContent(item, pageNo, root)
        : formatTextContent(item);
  const figureOcrText = type === "figure" ? collectFigureOcrText(root, item) : "";

  if (!content.trim()) return null;

  return {
    documentName,
    pageNo: pageNo || null,
    type,
    content: content.trim(),
    metadata: {
      label: pickFirst(item.label, item.type, item.kind),
      sourcePath,
      selfRef: getSelfRef(item),
      prov: item.prov || [],
      missingPageNo: !pageNo,
      caption: type === "figure" ? getFigureCaption(item) : undefined,
      imageReference: type === "figure" ? getFigureReference(item) : undefined,
      imageOcrText: figureOcrText || undefined,
    },
  };
}

function comparePageKeys(left, right) {
  if (left === "Unknown") return 1;
  if (right === "Unknown") return -1;
  return Number(left) - Number(right);
}

function buildPageAwareMarkdown(chunks) {
  const pages = new Map();

  chunks.forEach((chunk) => {
    const key = chunk.pageNo || "Unknown";
    if (!pages.has(key)) pages.set(key, []);
    pages.get(key).push(chunk.content);
  });

  return Array.from(pages.entries())
    .sort(([left], [right]) => comparePageKeys(left, right))
    .map(([pageNo, contents]) => {
      const pageLabel = pageNo === "Unknown" ? "[Page Unknown]" : `[Page ${pageNo}]`;
      return `${pageLabel}\n\n${contents.join("\n\n")}`;
    })
    .join("\n\n---\n\n");
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

export function buildStructuredPageOutput(response, documentName = "document") {
  const { document, sourcePath } = findStructuredDocument(response);

  if (!document) {
    const fallback = extractMarkdown(response);

    return {
      markdown: fallback.value,
      chunks: fallback.value
        ? [
            {
              documentName,
              pageNo: null,
              type: "text",
              content: fallback.value,
              metadata: {
                sourcePath: fallback.sourcePath,
                missingPageNo: true,
                fallbackUsed: true,
              },
            },
          ]
        : [],
      figures: [],
      tableCount: 0,
      sourcePath: fallback.sourcePath || "",
      warnings: fallback.value
        ? ["Structured Docling JSON was not found, so Markdown fallback was used."]
        : ["Structured Docling JSON and Markdown fallback were not found."],
    };
  }

  const chunks = getOrderedDocumentItems(document)
    .map((entry) => buildChunk({ ...entry, documentName, root: document }))
    .filter(Boolean);

  const figures = chunks
    .filter((chunk) => chunk.type === "figure")
    .map((chunk, index) => ({
      id: chunk.metadata.selfRef || `figure-${index + 1}`,
      pageNumber: chunk.pageNo,
      caption: chunk.metadata.caption,
      reference: chunk.metadata.imageReference,
      type: chunk.metadata.label || "figure",
      raw: chunk.metadata,
    }));

  const warnings = [];

  if (chunks.some((chunk) => chunk.metadata.missingPageNo)) {
    warnings.push("Some Docling items did not include page_no, so they were placed under [Page Unknown].");
  }

  if (!chunks.length) {
    warnings.push("Structured Docling JSON was found, but no usable text, table, or figure items were extracted.");
  }

  return {
    markdown: buildPageAwareMarkdown(chunks),
    chunks,
    figures,
    tableCount: chunks.filter((chunk) => chunk.type === "table").length,
    sourcePath,
    warnings,
  };
}
