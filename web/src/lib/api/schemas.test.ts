import { describe, expect, it } from "vitest"

import { fieldSchema, pageOf, runSchema } from "./schemas"

const run = {
  id: "8e2db3c1-5076-4320-a289-194e586f85cb",
  trigger: "api",
  source: "fs",
  prefix: "",
  force: false,
  bypass_cache: false,
  status: "succeeded",
  pipeline_version: "65c8037b3466bcd8",
  docs_seen: 14,
  docs_changed: 1,
  docs_unchanged: 13,
  docs_removed: 0,
  docs_succeeded: 1,
  docs_failed: 0,
  docs_deduplicated: 0,
  input_tokens: 3522,
  output_tokens: 774,
  cost_usd: 0.0296,
  cost_saved_usd: 0.6033,
  cost_estimated: true,
  error: null,
  created_at: "2026-10-04T19:05:17.958524Z",
  started_at: "2026-10-04T19:05:17.979757Z",
  finished_at: "2026-10-04T19:05:18.471901Z",
  has_export: true,
}

describe("API boundary validation", () => {
  it("accepts a page of runs", () => {
    const parsed = pageOf(runSchema).parse({ items: [run], total: 1, limit: 25, offset: 0 })
    expect(parsed.items[0]?.docs_unchanged).toBe(13)
  })

  it("rejects responses that drift from the contract", () => {
    expect(runSchema.safeParse({ ...run, docs_seen: "14" }).success).toBe(false)
  })

  it("accepts nested JSON field values", () => {
    const field = fieldSchema.parse({
      id: "93ccf22f-9934-4261-aaf9-2833173d472e",
      path: "line_items",
      value: [{ description: "Freight", amount: "5625.00" }],
      confidence: 0.87,
      model_confidence: 0.9,
      status: "accepted",
      repaired: true,
      issues: [],
      evidence: "Freight, Oakland to Reno",
      match: "exact",
      block_key: "p1-b6",
      page: 1,
      bbox: { x0: 1, top: 2, x1: 3, bottom: 4 },
      review_item_id: null,
    })
    expect(Array.isArray(field.value)).toBe(true)
  })
})
