"use client"

import { Table2 } from "lucide-react"

import type { Chunk } from "@/lib/api/schemas"
import { cn } from "@/lib/utils"

export function ChunkList({
  chunks,
  activeId,
  onSelect,
}: {
  chunks: Chunk[]
  activeId: string | null
  onSelect: (chunk: Chunk) => void
}) {
  return (
    <ul className="space-y-2">
      {chunks.map((chunk) => (
        <li key={chunk.id}>
          <button
            type="button"
            onClick={() => onSelect(chunk)}
            className={cn(
              "w-full rounded-xl px-3 py-2.5 text-left ring-1 ring-border/60 transition-colors duration-150 outline-none focus-visible:ring-4 focus-visible:ring-ring",
              chunk.id === activeId ? "bg-primary/10 ring-primary/30" : "bg-card hover:bg-accent/50"
            )}
          >
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <span className="font-medium tabular-nums">#{chunk.ordinal + 1}</span>
              {chunk.is_table ? <Table2 className="size-3" aria-label="Table chunk" /> : null}
              <span className="truncate">{chunk.heading_path.join(" › ") || "Document start"}</span>
              <span className="ml-auto shrink-0 tabular-nums">
                p.{chunk.page_start}
                {chunk.page_end !== chunk.page_start ? `-${chunk.page_end}` : ""} · {chunk.token_count} tok
              </span>
            </div>
            <p className="mt-1 line-clamp-3 text-[13px] leading-5 whitespace-pre-line">{chunk.text}</p>
          </button>
        </li>
      ))}
    </ul>
  )
}
