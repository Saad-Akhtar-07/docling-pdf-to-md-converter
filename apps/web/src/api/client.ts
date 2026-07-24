// Thin typed wrapper around apps/api. The *shapes* below (paths, schemas)
// come entirely from generate:api-types (openapi-typescript reading apps/api's
// live OpenAPI schema) — nothing here hand-writes a response type.
import createClient from "openapi-fetch";
import type { paths } from "./schema";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const client = createClient<paths>({ baseUrl: BASE_URL });

export type DocumentStatus = "uploaded" | "extracting" | "ready" | "failed";
export type Provenance = "verbatim" | "ocr" | "model_generated";

async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await promise;
  if (error !== undefined) {
    const detail =
      typeof error === "object" && error !== null && "detail" in error
        ? String((error as { detail: unknown }).detail)
        : `Request failed with HTTP ${response.status}.`;
    throw new Error(detail);
  }
  return data as T;
}

export function uploadDocument(file: File) {
  // The generated body type is `string` because OpenAPI's `format: binary`
  // has no native "File" representation — the cast bridges that gap at this
  // one call site. bodySerializer builds the actual multipart/form-data
  // payload FastAPI's File(...) parameter expects; openapi-fetch's default
  // JSON serializer doesn't produce that shape.
  return unwrap(
    client.POST("/documents", {
      body: { file: file as unknown as string },
      bodySerializer() {
        const formData = new FormData();
        formData.append("file", file);
        return formData;
      },
    }),
  );
}

export function getDocument(documentId: string) {
  return unwrap(client.GET("/documents/{document_id}", { params: { path: { document_id: documentId } } }));
}

export function getDocumentBlocks(documentId: string, slide?: number) {
  return unwrap(
    client.GET("/documents/{document_id}/blocks", {
      params: { path: { document_id: documentId }, query: slide ? { slide } : undefined },
    }),
  );
}
