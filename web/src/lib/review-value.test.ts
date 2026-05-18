import { describe, expect, it } from "vitest"

import { parseEdited, placeholderFor, toEditable } from "./review-value"

describe("review value editing", () => {
  it("round-trips scalars and clears to null", () => {
    expect(toEditable("2026-04-01")).toBe("2026-04-01")
    expect(parseEdited(" 6322.40 ", "6497.40")).toEqual({ ok: true, value: "6322.40" })
    expect(parseEdited("", "x")).toEqual({ ok: true, value: null })
  })

  it("parses booleans and rejects other words for boolean fields", () => {
    expect(parseEdited("false", true)).toEqual({ ok: true, value: false })
    expect(parseEdited("maybe", true).ok).toBe(false)
  })

  it("requires valid JSON for structured values", () => {
    const items = [{ description: "Widget", quantity: "1", unit_price: "5.00", amount: "5.00" }]
    expect(parseEdited(toEditable(items), items)).toEqual({ ok: true, value: items })
    expect(parseEdited("[{", items).ok).toBe(false)
  })

  it("hints the expected format", () => {
    expect(placeholderFor("due_date")).toBe("YYYY-MM-DD")
    expect(placeholderFor("total")).toBe("1234.50")
  })
})
