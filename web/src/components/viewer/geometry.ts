import type { BBox } from "@/lib/api/schemas"

export type HighlightTone = "field" | "chunk" | "issue"

export interface Highlight {
  id: string
  page: number
  bbox: BBox
  tone: HighlightTone
  label?: string
}

export interface Rect {
  left: number
  top: number
  width: number
  height: number
}

const PADDING = 2

export function toScreenRect(bbox: BBox, scale: number): Rect {
  return {
    left: bbox.x0 * scale - PADDING,
    top: bbox.top * scale - PADDING,
    width: (bbox.x1 - bbox.x0) * scale + PADDING * 2,
    height: (bbox.bottom - bbox.top) * scale + PADDING * 2,
  }
}

export function pageScale(renderedWidth: number, pageWidth: number): number {
  return pageWidth > 0 ? renderedWidth / pageWidth : 1
}

export function fitWidth(containerWidth: number, pageWidth: number, maxWidth = 900): number {
  return Math.max(280, Math.min(containerWidth, maxWidth, pageWidth * 1.6))
}
