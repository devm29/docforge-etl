import { describe, expect, it } from "vitest"

import { isShortcut } from "./keyboard"

function press(init: KeyboardEventInit, target: EventTarget = document.body): KeyboardEvent {
  let captured: KeyboardEvent | null = null
  const listener = (event: Event) => {
    if (event instanceof KeyboardEvent) captured = event
  }
  document.addEventListener("keydown", listener)
  target.dispatchEvent(new KeyboardEvent("keydown", { key: "a", bubbles: true, ...init }))
  document.removeEventListener("keydown", listener)
  if (captured === null) throw new Error("no event")
  return captured
}

describe("isShortcut", () => {
  it("accepts a bare key on the page", () => {
    expect(isShortcut(press({}))).toBe(true)
  })

  it("ignores select-all and other modified presses", () => {
    expect(isShortcut(press({ metaKey: true }))).toBe(false)
    expect(isShortcut(press({ ctrlKey: true }))).toBe(false)
    expect(isShortcut(press({ altKey: true }))).toBe(false)
  })

  it("ignores auto-repeat from a held key", () => {
    expect(isShortcut(press({ repeat: true }))).toBe(false)
  })

  it("ignores keys typed into fields, buttons and editable regions", () => {
    for (const markup of ["<input />", "<textarea></textarea>", "<button>Go</button>", "<div contenteditable='true'><span>x</span></div>"]) {
      document.body.innerHTML = markup
      const host = document.body.firstElementChild
      if (host === null) throw new Error("no element")
      const target = host.firstElementChild ?? host
      expect(isShortcut(press({}, target))).toBe(false)
    }
  })
})
