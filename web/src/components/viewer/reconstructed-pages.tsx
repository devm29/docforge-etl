"use client"

import type { Block, PageSize } from "@/lib/api/schemas"
import { cn } from "@/lib/utils"

import { pageScale, type Highlight } from "./geometry"
import { HighlightLayer } from "./highlight-layer"

const HEADING_SIZES: Record<number, number> = { 1: 19, 2: 14, 3: 12 }

// Word boxes for flow documents are synthesized with Helvetica metrics on the server.
const METRIC_FONT = "Helvetica, Arial, sans-serif"

function BlockView({ block, scale, grid }: { block: Block; scale: number; grid: boolean }) {
  const style = {
    left: block.bbox.x0 * scale,
    top: block.bbox.top * scale,
    width: (block.bbox.x1 - block.bbox.x0) * scale,
    height: (block.bbox.bottom - block.bbox.top) * scale,
  }
  if (block.kind === "table" && block.rows) {
    const columns = Math.max(...block.rows.map((row) => row.length))
    return (
      <div
        className="absolute grid overflow-hidden text-neutral-800"
        style={{
          ...style,
          gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
          gridAutoRows: `${(style.height / block.rows.length).toFixed(2)}px`,
          fontSize: Math.max(7, 9 * scale),
        }}
      >
        {block.rows.flatMap((row, r) =>
          Array.from({ length: columns }, (_, c) => (
            <span
              key={`${r}-${c}`}
              className={cn(
                "truncate border-r border-b border-neutral-200 px-1 leading-none",
                "flex items-center",
                r === 0 && "bg-neutral-100 font-semibold"
              )}
            >
              {row[c] ?? ""}
            </span>
          ))
        )}
      </div>
    )
  }
  if (block.words.length > 0) {
    return (
      <>
        {block.words.map((word, index) => {
          const height = word.bbox.bottom - word.bbox.top
          const size = grid ? Math.min(height / 1.6, block.kind === "heading" ? 13 : 10) : height / 1.35
          return (
            <span
              key={index}
              className={cn(
                "absolute leading-none whitespace-nowrap text-neutral-800",
                "flex items-center",
                block.kind === "heading" && "font-semibold text-neutral-900"
              )}
              style={{
                left: word.bbox.x0 * scale + (grid ? 3 * scale : 0),
                top: word.bbox.top * scale,
                height: height * scale,
                fontSize: size * scale,
                fontFamily: METRIC_FONT,
              }}
            >
              {word.text}
            </span>
          )
        })}
      </>
    )
  }
  const size = block.kind === "heading" ? (HEADING_SIZES[block.heading_level ?? 2] ?? 12) : grid ? 9.5 : 10.5
  return (
    <p
      className={cn(
        "absolute overflow-hidden text-neutral-800",
        block.kind === "heading" && "font-semibold text-neutral-900",
        grid && "whitespace-nowrap"
      )}
      style={{ ...style, fontSize: size * scale, lineHeight: 1.33 }}
    >
      {block.text}
    </p>
  )
}

export function ReconstructedPages({
  pages,
  blocks,
  width,
  highlights,
  activeId,
  onSelect,
}: {
  pages: PageSize[]
  blocks: Block[]
  width: number
  highlights: Highlight[]
  activeId: string | null
  onSelect?: ((id: string) => void) | undefined
}) {
  return (
    <div className="flex flex-col items-center gap-6">
      {pages.map((page) => {
        const scale = pageScale(width, page.width)
        const pageBlocks = blocks.filter((b) => b.page === page.number)
        const grid = pageBlocks.some((b) => b.geometry === "grid")
        return (
          <div
            key={page.number}
            className="relative overflow-hidden rounded-[4px] bg-white shadow-[var(--shadow-md)] ring-1 ring-black/5"
            style={{ width, height: page.height * scale }}
            data-page={page.number}
          >
            {pageBlocks.map((block) => (
              <BlockView key={block.id} block={block} scale={scale} grid={grid} />
            ))}
            <HighlightLayer
              highlights={highlights.filter((h) => h.page === page.number)}
              scale={scale}
              activeId={activeId}
              onSelect={onSelect}
            />
            <span className="absolute right-2 bottom-2 rounded-full bg-black/55 px-2 py-0.5 text-[11px] font-medium text-white tabular-nums">
              {page.label ? `${page.label} · ` : ""}
              {page.number} / {pages.length}
            </span>
          </div>
        )
      })}
    </div>
  )
}
