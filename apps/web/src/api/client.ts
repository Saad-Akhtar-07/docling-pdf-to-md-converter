// Thin typed wrapper around apps/api. The *shapes* below (paths, schemas)
// come entirely from generate:api-types (openapi-typescript reading apps/api's
// live OpenAPI schema) — nothing here hand-writes a response type.
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const client = createClient<paths>({ baseUrl: BASE_URL });

export type DocumentStatus = "uploaded" | "extracting" | "ready" | "failed";
export type Provenance = "verbatim" | "ocr" | "model_generated";
export type PlanStatus = "draft" | "approved" | "archived";
export type PlanEditAction = "update" | "delete" | "approve";

export type ExpectedIdeaOut = components["schemas"]["ExpectedIdeaOut"];
export type ExpectedIdeaIn = components["schemas"]["ExpectedIdeaIn"];
export type MisconceptionOut = components["schemas"]["MisconceptionOut"];
export type ObjectiveOut = components["schemas"]["ObjectiveOut"];
export type ObjectivePatch = components["schemas"]["ObjectivePatch"];
export type UnitOut = components["schemas"]["UnitOut"];
export type PlanOut = components["schemas"]["PlanOut"];
export type PlanEditOut = components["schemas"]["PlanEditOut"];
export type BlockOut = components["schemas"]["BlockOut"];

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

export function getPlan(planId: string) {
  return unwrap(client.GET("/plans/{plan_id}", { params: { path: { plan_id: planId } } }));
}

export function updateObjective(objectiveId: string, patch: ObjectivePatch) {
  return unwrap(
    client.PATCH("/objectives/{objective_id}", {
      params: { path: { objective_id: objectiveId } },
      body: patch,
    }),
  );
}

export function deleteObjective(objectiveId: string) {
  return unwrap(
    client.DELETE("/objectives/{objective_id}", { params: { path: { objective_id: objectiveId } } }),
  );
}

export function approvePlan(planId: string) {
  return unwrap(client.POST("/plans/{plan_id}/approve", { params: { path: { plan_id: planId } } }));
}

export function getPlanEdits(planId: string) {
  return unwrap(client.GET("/plans/{plan_id}/edits", { params: { path: { plan_id: planId } } }));
}
