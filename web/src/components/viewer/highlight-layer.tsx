"use client"

import { cn } from "@/lib/utils"

import { toScreenRect, type Highlight } from "./geometry"

const TONES = {
  field: "border-highlight/70 bg-highlight/10",
  chunk: "border-chart-2/70 bg-chart-2/10",
  issue: "border-destructive/80 bg-destructive/10",
} as const

export function isActiveHighlight(highlight: Highlight, activeId: string | null): boolean {
  return activeId !== null && (highlight.id === activeId || highlight.id.startsWith(`${activeId}:`))
}

export function HighlightLayer({
  highlights,
  scale,
  activeId,
  onSelect,
}: {
  highlights: Highlight[]
  scale: number
  activeId: string | null
  onSelect?: ((id: string) => void) | undefined
}) {
  return (
    <div className="pointer-events-none absolute inset-0">
      {highlights.map((highlight) => {
        const rect = toScreenRect(highlight.bbox, scale)
        const active = isActiveHighlight(highlight, activeId)
        return (
          <button
            key={highlight.id}
            type="button"
            data-highlight-active={active ? "true" : undefined}
            aria-label={highlight.label ?? "Highlighted region"}
            aria-pressed={active}
            title={highlight.label}
            onClick={() => onSelect?.(highlight.id)}
            className={cn(
              "pointer-events-auto absolute rounded-[3px] border outline-none transition-[opacity,box-shadow] duration-200 ease-[var(--ease-apple)] focus-visible:opacity-100 focus-visible:ring-4 focus-visible:ring-ring motion-reduce:transition-none",
              TONES[highlight.tone],
              active
                ? "z-10 border-2 opacity-100 shadow-[0_0_0_4px_color-mix(in_oklch,var(--highlight)_22%,transparent)]"
                : activeId
                  ? "opacity-35 hover:opacity-80"
                  : "opacity-80 hover:opacity-100"
            )}
            style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
          />
        )
      })}
    </div>
  )
}
