import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_PORT = Number(process.env.VISION_SERVICE_PORT || 8787);
const GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions";
const DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct";
const MAX_BODY_BYTES = Number(process.env.VISION_SERVICE_MAX_BODY_BYTES || 64 * 1024 * 1024);
const MAX_BASE64_REQUEST_BYTES = Number(process.env.GROQ_MAX_BASE64_REQUEST_BYTES || 4 * 1024 * 1024);
const DEFAULT_CONCURRENCY = Number(process.env.GROQ_VISION_CONCURRENCY || 1);
const DEFAULT_TIMEOUT_MS = Number(process.env.GROQ_VISION_TIMEOUT_MS || 180_000);
const DEFAULT_MAX_COMPLETION_TOKENS = Number(process.env.GROQ_VISION_MAX_TOKENS || 500);
const DEFAULT_RETRY_COUNT = Number(process.env.GROQ_VISION_RETRY_COUNT || 6);
const DEFAULT_RETRY_BASE_DELAY_MS = Number(process.env.GROQ_VISION_RETRY_BASE_DELAY_MS || 4_000);
const DEFAULT_REQUEST_DELAY_MS = Number(process.env.GROQ_VISION_REQUEST_DELAY_MS || 15_000);

export function loadDotEnv() {
  [".env", ".env.local"].forEach((fileName) => {
    const filePath = resolve(process.cwd(), fileName);
    if (!existsSync(filePath)) return;

    const lines = readFileSync(filePath, "utf8").split(/\r?\n/);
    lines.forEach((line) => {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) return;

      const separatorIndex = trimmed.indexOf("=");
      if (separatorIndex === -1) return;

      const key = trimmed.slice(0, separatorIndex).trim();
      const rawValue = trimmed.slice(separatorIndex + 1).trim();
      const value = rawValue.replace(/^['"]|['"]$/g, "");

      if (key && process.env[key] === undefined) {
        process.env[key] = value;
      }
    });
  });
}

function sendJson(response, statusCode, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "access-control-allow-headers": "content-type,authorization",
  });
  response.end(body);
}

function readJsonBody(request) {
  return new Promise((resolveBody, reject) => {
    let receivedBytes = 0;
    const chunks = [];

    request.on("data", (chunk) => {
      receivedBytes += chunk.length;

      if (receivedBytes > MAX_BODY_BYTES) {
        reject(new Error(`Request body exceeds ${MAX_BODY_BYTES} bytes.`));
        request.destroy();
        return;
      }

      chunks.push(chunk);
    });

    request.on("end", () => {
      try {
        const body = Buffer.concat(chunks).toString("utf8");
        resolveBody(body ? JSON.parse(body) : {});
      } catch {
        reject(new Error("Request body must be valid JSON."));
      }
    });

    request.on("error", reject);
  });
}

function compactPageText(pageText = "") {
  return String(pageText)
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, Number(process.env.GROQ_VISION_PAGE_TEXT_CHARS || 1500));
}

function createPrompt({ pageNumber, caption, pageText }) {
  const pageLabel = pageNumber ? `Page ${pageNumber}` : "Unknown page";
  const contextText = compactPageText(pageText);
  const captionText = caption ? `\nCaption: ${caption}` : "";
  const pageContext = contextText ? `\nExisting OCR/text from the slide:\n${contextText}` : "";

  return `Describe this lecture slide for a downstream teaching pipeline.

Return only valid JSON with these keys:
- pageNumber: number or null
- visualDescription: 2-4 concise sentences about diagrams, charts, visual layout, arrows, formulas, or relationships
- teachingExplanation: 2-4 concise sentences explaining what a teacher should say about the visual content
- importantVisualElements: array of short strings
- missingTextFromImage: array of short strings for visible text/symbols not already present in OCR, or []

Do not repeat all OCR text. Do not invent details. If the slide is mostly text, summarize only visual structure and any meaningful non-text visuals.

Slide: ${pageLabel}${captionText}${pageContext}`;
}

function normalizeGroqJson(content, fallbackPageNumber) {
  try {
    const parsed = JSON.parse(content);

    return {
      pageNumber: parsed.pageNumber ?? fallbackPageNumber ?? null,
      visualDescription: String(parsed.visualDescription || "").trim(),
      teachingExplanation: String(parsed.teachingExplanation || "").trim(),
      importantVisualElements: Array.isArray(parsed.importantVisualElements)
        ? parsed.importantVisualElements.map(String).filter(Boolean)
        : [],
      missingTextFromImage: Array.isArray(parsed.missingTextFromImage)
        ? parsed.missingTextFromImage.map(String).filter(Boolean)
        : [],
    };
  } catch {
    return {
      pageNumber: fallbackPageNumber ?? null,
      visualDescription: String(content || "").trim(),
      teachingExplanation: "",
      importantVisualElements: [],
      missingTextFromImage: [],
    };
  }
}

async function describeImage({ image, pageText }) {
  const apiKey = process.env.GROQ_API_KEY;
  if (!apiKey) {
    throw new Error("GROQ_API_KEY is not set. Add it to .env.local and restart the Vision service.");
  }

  if (!image?.source) {
    throw new Error("Image source is missing.");
  }

  const requestBytes = Buffer.byteLength(image.source, "utf8");
  if (requestBytes > MAX_BASE64_REQUEST_BYTES) {
    throw new Error(
      `Image data is ${requestBytes} bytes, above Groq base64 request limit ${MAX_BASE64_REQUEST_BYTES}. Lower imagesScale or upload image URLs instead.`,
    );
  }

  const responseBody = await callGroqWithRetry({
    image,
    pageText,
    apiKey,
  });
  const content = responseBody?.choices?.[0]?.message?.content || "";
  const description = normalizeGroqJson(content, image.pageNumber);

  return {
    id: image.id,
    fingerprint: image.fingerprint,
    pageNumber: image.pageNumber,
    provider: "groq",
    model: process.env.GROQ_VISION_MODEL || DEFAULT_MODEL,
    ...description,
  };
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function getRetryAfterMs(response) {
  const retryAfter = response.headers.get("retry-after");
  if (!retryAfter) return 0;

  const retryAfterSeconds = Number(retryAfter);
  if (Number.isFinite(retryAfterSeconds)) return retryAfterSeconds * 1000;

  const retryAt = Date.parse(retryAfter);
  return Number.isFinite(retryAt) ? Math.max(0, retryAt - Date.now()) : 0;
}

function isRetryableStatus(status) {
  return status === 408 || status === 409 || status === 425 || status === 429 || status >= 500;
}

function buildGroqPayload({ image, pageText }) {
  return {
    model: process.env.GROQ_VISION_MODEL || DEFAULT_MODEL,
    messages: [
      {
        role: "user",
        content: [
          {
            type: "text",
            text: createPrompt({
              pageNumber: image.pageNumber,
              caption: image.caption,
              pageText,
            }),
          },
          {
            type: "image_url",
            image_url: {
              url: image.source,
            },
          },
        ],
      },
    ],
    temperature: Number(process.env.GROQ_VISION_TEMPERATURE || 0.2),
    top_p: 1,
    max_completion_tokens: DEFAULT_MAX_COMPLETION_TOKENS,
    response_format: { type: "json_object" },
    stream: false,
  };
}

async function callGroqOnce({ image, pageText, apiKey }) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);

  try {
    const groqResponse = await fetch(GROQ_API_URL, {
      method: "POST",
      headers: {
        authorization: `Bearer ${apiKey}`,
        "content-type": "application/json",
      },
      body: JSON.stringify(buildGroqPayload({ image, pageText })),
      signal: controller.signal,
    });

    const responseBody = await groqResponse.json().catch(async () => ({
      error: { message: await groqResponse.text() },
    }));

    if (!groqResponse.ok) {
      const message = responseBody?.error?.message || JSON.stringify(responseBody);
      const error = new Error(`Groq returned HTTP ${groqResponse.status}: ${message}`);
      error.status = groqResponse.status;
      error.retryAfterMs = getRetryAfterMs(groqResponse);
      throw error;
    }

    return responseBody;
  } finally {
    clearTimeout(timeoutId);
  }
}

async function callGroqWithRetry({ image, pageText, apiKey }) {
  let lastError = null;

  for (let attempt = 0; attempt <= DEFAULT_RETRY_COUNT; attempt += 1) {
    try {
      return await callGroqOnce({ image, pageText, apiKey });
    } catch (error) {
      lastError = error;
      const status = error.status || 0;
      const isTimeout = error.name === "AbortError";
      const shouldRetry = isTimeout || isRetryableStatus(status);

      if (!shouldRetry || attempt === DEFAULT_RETRY_COUNT) {
        throw error;
      }

      const backoffMs = DEFAULT_RETRY_BASE_DELAY_MS * 2 ** attempt;
      const jitterMs = Math.floor(Math.random() * 1000);
      const delayMs = Math.max(error.retryAfterMs || 0, backoffMs + jitterMs);

      await sleep(delayMs);
    }
  }

  throw lastError || new Error("Groq request failed.");
}

async function runWithConcurrency(items, concurrency, worker) {
  const results = new Array(items.length);
  let nextIndex = 0;

  async function runWorker() {
    while (nextIndex < items.length) {
      const index = nextIndex;
      nextIndex += 1;

      try {
        if (index > 0 && DEFAULT_REQUEST_DELAY_MS > 0) {
          await sleep(DEFAULT_REQUEST_DELAY_MS);
        }

        results[index] = await worker(items[index], index);
      } catch (error) {
        results[index] = {
          id: items[index]?.image?.id,
          fingerprint: items[index]?.image?.fingerprint,
          pageNumber: items[index]?.image?.pageNumber,
          error: error.message || "Vision description failed.",
        };
      }
    }
  }

  await Promise.all(
    Array.from({ length: Math.max(1, Math.min(concurrency, items.length)) }, () => runWorker()),
  );

  return results;
}

async function handleDescribeBatch(request, response) {
  const payload = await readJsonBody(request);
  const candidates = Array.isArray(payload.images) ? payload.images : [];
  const pageTextByNumber = payload.pageTextByNumber || {};

  const jobs = candidates.map((image) => ({
    image,
    pageText: pageTextByNumber[String(image.pageNumber || "Unknown")] || "",
  }));

  const descriptions = await runWithConcurrency(jobs, DEFAULT_CONCURRENCY, describeImage);

  sendJson(response, 200, {
    provider: "groq",
    model: process.env.GROQ_VISION_MODEL || DEFAULT_MODEL,
    descriptions,
  });
}

export async function handleVisionRequest(request, response) {
  try {
    if (request.method === "OPTIONS") {
      sendJson(response, 204, {});
      return;
    }

    if (request.method === "GET" && request.url === "/api/vision/health") {
      sendJson(response, 200, {
        ok: true,
        provider: "groq",
        model: process.env.GROQ_VISION_MODEL || DEFAULT_MODEL,
        hasApiKey: Boolean(process.env.GROQ_API_KEY),
      });
      return;
    }

    if (request.method === "POST" && request.url === "/api/vision/describe-batch") {
      await handleDescribeBatch(request, response);
      return;
    }

    sendJson(response, 404, { error: "Not found." });
  } catch (error) {
    sendJson(response, 500, { error: error.message || "Vision service failed." });
  }
}

function createVisionServer() {
  return createServer(async (request, response) => {
    await handleVisionRequest(request, response);
  });
}

loadDotEnv();

const isDirectRun = process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1]);

if (isDirectRun) {
  createVisionServer().listen(DEFAULT_PORT, () => {
    console.log(
      `SlideVision Vision service listening on http://localhost:${DEFAULT_PORT} using ${
        process.env.GROQ_VISION_MODEL || DEFAULT_MODEL
      }`,
    );
  });
}
