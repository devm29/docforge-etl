import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import type { ReviewItem } from "@/lib/api/schemas"

import { ReviewDetail } from "./review-detail"

const mutateAsync = vi.fn()
const resolveState = { isPending: false }

vi.mock("@/lib/api/hooks", () => ({
  useResolveReview: () => ({ mutateAsync, isPending: resolveState.isPending }),
  useDocument: () => ({ data: undefined }),
}))

vi.mock("@/components/viewer/document-viewer", () => ({ DocumentViewer: () => null }))

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const item: ReviewItem = {
  id: "8d3c1f6e-0b0a-4f55-9a1c-1f1b2c3d4e5f",
  status: "pending",
  reason: "low_confidence",
  created_at: "2026-10-04T10:00:00Z",
  resolved_at: null,
  reviewer: null,
  note: null,
  original_value: null,
  resolved_value: null,
  schema_name: "invoice",
  extraction_id: "1a2b3c4d-0000-4000-8000-000000000001",
  extraction_status: "needs_review",
  document: { id: "1a2b3c4d-0000-4000-8000-000000000002", filename: "quantum-print.pdf", uri: "invoices/quantum-print.pdf", kind: "invoice" },
  version_id: "1a2b3c4d-0000-4000-8000-000000000003",
  field: {
    id: "1a2b3c4d-0000-4000-8000-000000000004",
    path: "due_date",
    value: null,
    confidence: 0.54,
    model_confidence: 0.6,
    status: "needs_review",
    repaired: false,
    issues: [],
    evidence: null,
    match: "none",
    block_key: null,
    page: null,
    bbox: null,
    review_item_id: "8d3c1f6e-0b0a-4f55-9a1c-1f1b2c3d4e5f",
  },
}

async function press(init: KeyboardEventInit, target: Element = document.body) {
  await act(async () => {
    fireEvent.keyDown(target, { key: "a", ...init })
  })
}

describe("ReviewDetail keyboard shortcuts", () => {
  beforeEach(() => {
    mutateAsync.mockReset()
    mutateAsync.mockResolvedValue({ item, extraction_status: "approved" })
    resolveState.isPending = false
  })
  afterEach(cleanup)

  it("approves on a bare A", async () => {
    render(<ReviewDetail item={item} onResolved={() => undefined} />)
    await press({})
    expect(mutateAsync).toHaveBeenCalledTimes(1)
    expect(mutateAsync).toHaveBeenCalledWith({ id: item.id, action: "approve" })
  })

  it("does not approve on Cmd+A, Ctrl+A or a held key", async () => {
    render(<ReviewDetail item={item} onResolved={() => undefined} />)
    await press({ metaKey: true })
    await press({ ctrlKey: true })
    await press({ repeat: true })
    expect(mutateAsync).not.toHaveBeenCalled()
  })

  it("does not approve while typing a correction or while a decision is in flight", async () => {
    const { rerender } = render(<ReviewDetail item={item} onResolved={() => undefined} />)
    await press({}, screen.getByLabelText("Correct the value"))
    expect(mutateAsync).not.toHaveBeenCalled()

    resolveState.isPending = true
    rerender(<ReviewDetail item={item} onResolved={() => undefined} />)
    await press({})
    expect(mutateAsync).not.toHaveBeenCalled()
  })

  it("focuses the correction field on E", async () => {
    render(<ReviewDetail item={item} onResolved={() => undefined} />)
    await press({ key: "e" })
    expect(document.activeElement).toBe(screen.getByLabelText("Correct the value"))
  })
})
