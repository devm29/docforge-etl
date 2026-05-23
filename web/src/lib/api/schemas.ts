import { z } from "zod"

const uuid = z.string().uuid()
const timestamp = z.string()

export const jsonSchema: z.ZodType<JsonValue> = z.lazy(() =>
  z.union([z.string(), z.number(), z.boolean(), z.null(), z.array(jsonSchema), z.record(z.string(), jsonSchema)])
)
const json = jsonSchema
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }

export const RUN_STATUSES = ["queued", "scanning", "running", "finalizing", "succeeded", "partial", "failed"] as const
export const runStatusSchema = z.enum(RUN_STATUSES)
export type RunStatus = z.infer<typeof runStatusSchema>
export const runTriggerSchema = z.enum(["api", "schedule", "replay", "cli"])
export const documentStatusSchema = z.enum(["pending", "processing", "ready", "failed", "removed"])
export type DocumentStatus = z.infer<typeof documentStatusSchema>
export const versionStatusSchema = z.enum(["queued", "processing", "succeeded", "failed", "deduplicated"])
export type VersionStatus = z.infer<typeof versionStatusSchema>
export const extractionStatusSchema = z.enum(["valid", "needs_review", "invalid", "approved"])
export type ExtractionStatus = z.infer<typeof extractionStatusSchema>
export const fieldStatusSchema = z.enum(["accepted", "needs_review", "approved", "edited"])
export type FieldStatus = z.infer<typeof fieldStatusSchema>
export const REVIEW_STATUSES = ["pending", "approved", "edited", "superseded"] as const
export const reviewStatusSchema = z.enum(REVIEW_STATUSES)
export type ReviewStatus = z.infer<typeof reviewStatusSchema>
export const deadLetterStatusSchema = z.enum(["open", "resolved", "superseded", "replayed"])
export const matchKindSchema = z.enum(["exact", "fuzzy", "block", "none"])
export type MatchKind = z.infer<typeof matchKindSchema>

export const pageOf = <T extends z.ZodTypeAny>(item: T) =>
  z.object({ items: z.array(item), total: z.number(), limit: z.number(), offset: z.number() })

export const bboxSchema = z.object({ x0: z.number(), top: z.number(), x1: z.number(), bottom: z.number() })
export type BBox = z.infer<typeof bboxSchema>

export const runSchema = z.object({
  id: uuid,
  trigger: runTriggerSchema,
  source: z.string(),
  prefix: z.string(),
  force: z.boolean(),
  bypass_cache: z.boolean(),
  status: runStatusSchema,
  pipeline_version: z.string(),
  docs_seen: z.number(),
  docs_changed: z.number(),
  docs_unchanged: z.number(),
  docs_removed: z.number(),
  docs_succeeded: z.number(),
  docs_failed: z.number(),
  docs_deduplicated: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  cost_usd: z.number(),
  cost_saved_usd: z.number(),
  cost_estimated: z.boolean(),
  error: z.string().nullable(),
  created_at: timestamp,
  started_at: timestamp.nullable(),
  finished_at: timestamp.nullable(),
  has_export: z.boolean(),
})
export type Run = z.infer<typeof runSchema>

export const stageSummarySchema = z.object({
  stage: z.string(),
  executed: z.number(),
  cached: z.number(),
  failed: z.number(),
  skipped: z.number(),
  items_in: z.number(),
  items_out: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  cost_usd: z.number(),
  cost_saved_usd: z.number(),
  duration_ms: z.number(),
})
export type StageSummary = z.infer<typeof stageSummarySchema>

export const deadLetterSchema = z.object({
  id: uuid,
  run_id: uuid,
  version_id: uuid,
  document_id: uuid,
  filename: z.string(),
  uri: z.string(),
  stage: z.string(),
  error_type: z.string(),
  error: z.string(),
  attempts: z.number(),
  retryable: z.boolean(),
  status: deadLetterStatusSchema,
  created_at: timestamp,
  replayed_at: timestamp.nullable(),
  replay_run_id: uuid.nullable(),
})
export type DeadLetter = z.infer<typeof deadLetterSchema>

export const runDetailSchema = z.object({
  run: runSchema,
  stages: z.array(stageSummarySchema),
  dead_letters: z.array(deadLetterSchema),
})
export type RunDetail = z.infer<typeof runDetailSchema>

export const stageRunSchema = z.object({
  id: uuid,
  stage: z.string(),
  status: z.enum(["succeeded", "cached", "failed", "skipped"]),
  attempts: z.number(),
  items_in: z.number(),
  items_out: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  cost_usd: z.number(),
  cost_saved_usd: z.number(),
  duration_ms: z.number(),
  started_at: timestamp,
  finished_at: timestamp.nullable(),
  error: z.string().nullable(),
  detail: z.record(z.string(), json),
})
export type StageRun = z.infer<typeof stageRunSchema>

export const timelineSchema = z.object({
  run_id: uuid,
  documents: z.array(
    z.object({
      version_id: uuid,
      document_id: uuid,
      filename: z.string(),
      uri: z.string(),
      version_no: z.number(),
      version_status: versionStatusSchema,
      stages: z.array(stageRunSchema),
    })
  ),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
})
export type Timeline = z.infer<typeof timelineSchema>

export const pageSizeSchema = z.object({
  number: z.number(),
  width: z.number(),
  height: z.number(),
  label: z.string().nullable().optional(),
})
export type PageSize = z.infer<typeof pageSizeSchema>

export const versionSchema = z.object({
  id: uuid,
  run_id: uuid,
  version_no: z.number(),
  status: versionStatusSchema,
  content_hash: z.string().nullable(),
  size_bytes: z.number(),
  format: z.string().nullable(),
  page_count: z.number().nullable(),
  pages: z.array(pageSizeSchema),
  error: z.string().nullable(),
  created_at: timestamp,
  processed_at: timestamp.nullable(),
})
export type Version = z.infer<typeof versionSchema>

export const documentSchema = z.object({
  id: uuid,
  source: z.string(),
  uri: z.string(),
  filename: z.string(),
  format: z.string().nullable(),
  kind: z.string().nullable(),
  status: documentStatusSchema,
  version_no: z.number().nullable(),
  page_count: z.number().nullable(),
  extraction_status: extractionStatusSchema.nullable(),
  average_confidence: z.number().nullable(),
  pending_reviews: z.number(),
  updated_at: timestamp,
})
export type DocumentSummary = z.infer<typeof documentSchema>

export const documentDetailSchema = documentSchema.extend({
  content_hash: z.string().nullable(),
  current_version: versionSchema.nullable(),
  versions: z.array(versionSchema),
  pages: z.array(pageSizeSchema),
})
export type DocumentDetail = z.infer<typeof documentDetailSchema>

export const fieldSchema = z.object({
  id: uuid,
  path: z.string(),
  value: json,
  confidence: z.number(),
  model_confidence: z.number(),
  status: fieldStatusSchema,
  repaired: z.boolean(),
  issues: z.array(z.string()),
  evidence: z.string().nullable(),
  match: matchKindSchema,
  block_key: z.string().nullable(),
  page: z.number().nullable(),
  bbox: bboxSchema.nullable(),
  review_item_id: uuid.nullable(),
})
export type ExtractedField = z.infer<typeof fieldSchema>

export const extractionSchema = z.object({
  id: uuid,
  version_id: uuid,
  schema_name: z.string(),
  schema_version: z.string(),
  status: extractionStatusSchema,
  data: z.record(z.string(), json),
  attempts: z.number(),
  repaired: z.boolean(),
  provider: z.string(),
  model: z.string(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  cost_usd: z.number(),
  attempt_log: z.array(z.object({ attempt: z.number(), errors: z.array(z.string()) })),
  created_at: timestamp,
  fields: z.array(fieldSchema),
})
export type Extraction = z.infer<typeof extractionSchema>

export const blockSchema = z.object({
  id: z.string(),
  page: z.number(),
  kind: z.enum(["heading", "paragraph", "table"]),
  geometry: z.enum(["layout", "flow", "grid"]),
  text: z.string(),
  bbox: bboxSchema,
  heading_level: z.number().nullable(),
  rows: z.array(z.array(z.string())).nullable(),
  cell_range: z.string().nullable(),
  words: z.array(z.object({ text: z.string(), bbox: bboxSchema })),
})
export type Block = z.infer<typeof blockSchema>

export const chunkSpanSchema = z.object({ block_id: z.string(), page: z.number(), bbox: bboxSchema })
export type ChunkSpan = z.infer<typeof chunkSpanSchema>

export const chunkSchema = z.object({
  id: uuid,
  ordinal: z.number(),
  text: z.string(),
  heading_path: z.array(z.string()),
  token_count: z.number(),
  page_start: z.number(),
  page_end: z.number(),
  spans: z.array(chunkSpanSchema),
  is_table: z.boolean(),
})
export type Chunk = z.infer<typeof chunkSchema>

export const documentRefSchema = z.object({
  id: uuid,
  filename: z.string(),
  uri: z.string(),
  kind: z.string().nullable(),
})

export const reviewItemSchema = z.object({
  id: uuid,
  status: reviewStatusSchema,
  reason: z.enum(["low_confidence", "validation_failed"]),
  created_at: timestamp,
  resolved_at: timestamp.nullable(),
  reviewer: z.string().nullable(),
  note: z.string().nullable(),
  original_value: json,
  resolved_value: json,
  schema_name: z.string(),
  extraction_id: uuid,
  extraction_status: extractionStatusSchema,
  document: documentRefSchema,
  version_id: uuid,
  field: fieldSchema,
})
export type ReviewItem = z.infer<typeof reviewItemSchema>

export const reviewResultSchema = z.object({ item: reviewItemSchema, extraction_status: extractionStatusSchema })

export const searchSchema = z.object({
  query: z.string(),
  model: z.string(),
  hits: z.array(
    z.object({
      chunk_id: uuid,
      document: documentRefSchema,
      score: z.number(),
      text: z.string(),
      heading_path: z.array(z.string()),
      page_start: z.number(),
      spans: z.array(chunkSpanSchema),
    })
  ),
})
export type SearchResult = z.infer<typeof searchSchema>

export const overviewSchema = z.object({
  documents_total: z.number(),
  documents_by_status: z.record(z.string(), z.number()),
  documents_by_kind: z.record(z.string(), z.number()),
  chunks_total: z.number(),
  runs_total: z.number(),
  tokens_total: z.number(),
  cost_total_usd: z.number(),
  cost_saved_usd: z.number(),
  cost_estimated: z.boolean(),
  pending_reviews: z.number(),
  open_dead_letters: z.number(),
  cache_entries: z.number(),
  cache_hits: z.number(),
  recent_runs: z.array(runSchema),
})
export type Overview = z.infer<typeof overviewSchema>

export const healthSchema = z.object({
  status: z.enum(["ok", "degraded"]),
  database: z.boolean(),
  queue: z.boolean(),
  provider: z.string(),
  model: z.string(),
  embedder: z.string(),
})
export type Health = z.infer<typeof healthSchema>

export const apiErrorSchema = z.object({
  error: z.object({ code: z.string(), message: z.string(), details: z.unknown().optional() }),
})
