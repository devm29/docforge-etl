import { z } from "zod"

import {
  apiErrorSchema,
  chunkSchema,
  blockSchema,
  deadLetterSchema,
  documentDetailSchema,
  documentSchema,
  extractionSchema,
  healthSchema,
  overviewSchema,
  pageOf,
  reviewItemSchema,
  reviewResultSchema,
  runDetailSchema,
  runSchema,
  searchSchema,
  timelineSchema,
  type JsonValue,
  type ReviewStatus,
} from "./schemas"

export const API_BASE = "/api"

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string
  ) {
    super(message)
    this.name = "ApiError"
  }
}

type Query = Record<string, string | number | boolean | null | undefined>

function withQuery(path: string, query?: Query): string {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value))
  }
  const encoded = params.toString()
  return encoded ? `${path}?${encoded}` : path
}

async function request<T extends z.ZodTypeAny>(
  schema: T,
  path: string,
  init?: { method?: "GET" | "POST"; body?: unknown; query?: Query }
): Promise<z.infer<T>> {
  const response = await fetch(`${API_BASE}${withQuery(path, init?.query)}`, {
    method: init?.method ?? "GET",
    headers: init?.body === undefined ? {} : { "content-type": "application/json" },
    ...(init?.body === undefined ? {} : { body: JSON.stringify(init.body) }),
  })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const parsed = apiErrorSchema.safeParse(payload)
    throw parsed.success
      ? new ApiError(response.status, parsed.data.error.code, parsed.data.error.message)
      : new ApiError(response.status, "http_error", `Request failed with status ${response.status}`)
  }
  return schema.parse(payload)
}

export const api = {
  health: () => request(healthSchema, "/health"),
  overview: () => request(overviewSchema, "/overview"),
  runs: (query: { limit?: number; offset?: number }) => request(pageOf(runSchema), "/runs", { query }),
  run: (id: string) => request(runDetailSchema, `/runs/${id}`),
  timeline: (id: string, query: { limit: number; offset: number }) =>
    request(timelineSchema, `/runs/${id}/timeline`, { query }),
  startRun: (body: { force?: boolean; bypass_cache?: boolean; source?: string }) =>
    request(runSchema, "/runs", { method: "POST", body }),
  documents: (query: { limit?: number; offset?: number; kind?: string; status?: string; q?: string }) =>
    request(pageOf(documentSchema), "/documents", { query }),
  document: (id: string) => request(documentDetailSchema, `/documents/${id}`),
  extraction: (id: string, versionId?: string) =>
    request(extractionSchema.nullable(), `/documents/${id}/extraction`, { query: { version_id: versionId } }),
  blocks: (id: string, versionId?: string) =>
    request(z.array(blockSchema), `/documents/${id}/blocks`, { query: { version_id: versionId } }),
  chunks: (id: string, versionId?: string) =>
    request(z.array(chunkSchema), `/documents/${id}/chunks`, { query: { version_id: versionId } }),
  reviews: (query: { status?: ReviewStatus; limit?: number; offset?: number }) =>
    request(pageOf(reviewItemSchema), "/reviews", { query }),
  approveReview: (id: string, body: { note?: string }) =>
    request(reviewResultSchema, `/reviews/${id}/approve`, { method: "POST", body }),
  editReview: (id: string, body: { value: JsonValue; note?: string }) =>
    request(reviewResultSchema, `/reviews/${id}/edit`, { method: "POST", body }),
  search: (query: { q: string; limit?: number; kind?: string }) => request(searchSchema, "/search", { query }),
  deadLetters: (query: { status?: string; limit?: number }) =>
    request(pageOf(deadLetterSchema), "/dead-letters", { query }),
  replayDeadLetter: (id: string) => request(runSchema, `/dead-letters/${id}/replay`, { method: "POST" }),
}

export function documentFileUrl(id: string, versionId?: string): string {
  return `${API_BASE}${withQuery(`/documents/${id}/file`, { version_id: versionId })}`
}

export function exportUrl(runId: string, table: "chunks" | "fields" | "stages"): string {
  return `${API_BASE}/runs/${runId}/export/${table}.parquet`
}
