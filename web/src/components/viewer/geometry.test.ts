import { describe, expect, it } from "vitest"

import { fitWidth, pageScale, toScreenRect } from "./geometry"

describe("provenance geometry", () => {
  it("scales PDF points to rendered pixels with a small padding", () => {
    const scale = pageScale(918, 612)
    expect(scale).toBe(1.5)
    expect(toScreenRect({ x0: 100, top: 200, x1: 150, bottom: 210 }, scale)).toEqual({
      left: 148,
      top: 298,
      width: 79,
      height: 19,
    })
  })

  it("keeps pages readable on narrow and very wide containers", () => {
    expect(fitWidth(200, 612)).toBe(280)
    expect(fitWidth(2000, 612)).toBe(900)
    expect(fitWidth(700, 612)).toBe(700)
  })

  it("does not divide by zero for malformed page sizes", () => {
    expect(pageScale(500, 0)).toBe(1)
  })
})
