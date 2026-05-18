import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import { ApiError } from "@/lib/api/client"

import { LoadError, describeLoadError } from "./empty-state"

afterEach(cleanup)

describe("describeLoadError", () => {
  it("points at the backend when the proxy cannot reach it", () => {
    const error = new ApiError(502, "api_unreachable", "The DocForge API at http://api:8103 is not reachable.")
    expect(describeLoadError(error)).toMatch(/port 8103/)
  })

  it("passes through the API's own message", () => {
    expect(describeLoadError(new ApiError(404, "not_found", "run 42 not found"))).toBe("run 42 not found")
  })

  it("falls back to a generic message for non-errors", () => {
    expect(describeLoadError(undefined)).toMatch(/try again/i)
  })
})

describe("LoadError", () => {
  it("announces the failure instead of an empty list", () => {
    render(<LoadError what="the review queue" error={new Error("boom")} />)
    expect(screen.getByRole("alert").textContent).toContain("Couldn't load the review queue")
    expect(screen.getByText("boom")).toBeTruthy()
  })
})
