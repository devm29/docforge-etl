"use client"

import dynamic from "next/dynamic"
import { useEffect, useState } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { useBlocks } from "@/lib/api/hooks"
import { documentFileUrl } from "@/lib/api/client"
import type { PageSize } from "@/lib/api/schemas"

import { fitWidth, type Highlight } from "./geometry"
import { ReconstructedPages } from "./reconstructed-pages"

const PdfPages = dynamic(() => import("./pdf-pages"), {
  ssr: false,
  loading: () => <Skeleton className="mx-auto aspect-[8.5/11] w-full max-w-3xl rounded-md" />,
})

function useWidth<T extends HTMLElement>() {
  const [element, setElement] = useState<T | null>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.floor(entry.contentRect.width))
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [element])
  return [setElement, element, width] as const
}

/**
 * Brings the first active highlight into view once, wherever it is. Highlights may mount later
 * than the selection (the PDF renderer loads lazily), so it waits for them to appear.
 */
function useScrollToActive(container: HTMLElement | null, activeId: string | null) {
  useEffect(() => {
    if (!container || activeId === null) return
    const scroll = () => {
      const target = container.querySelector("[data-highlight-active='true']")
      if (!target) return false
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
      target.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center", inline: "nearest" })
      return true
    }
    if (scroll()) return
    const observer = new MutationObserver(() => {
      if (scroll()) observer.disconnect()
    })
    observer.observe(container, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-highlight-active"] })
    const timeout = window.setTimeout(() => observer.disconnect(), 5000)
    return () => {
      observer.disconnect()
      window.clearTimeout(timeout)
    }
  }, [container, activeId])
}

export function DocumentViewer({
  documentId,
  versionId,
  format,
  pages,
  highlights,
  activeId,
  onSelect,
}: {
  documentId: string
  versionId?: string | undefined
  format: string | null
  pages: PageSize[]
  highlights: Highlight[]
  activeId: string | null
  onSelect?: ((id: string) => void) | undefined
}) {
  const [ref, container, containerWidth] = useWidth<HTMLDivElement>()
  const isPdf = format === "pdf"
  const blocks = useBlocks(documentId, versionId, !isPdf)
  const widest = Math.max(612, ...pages.map((p) => p.width))
  const width = containerWidth ? fitWidth(containerWidth, widest) : 0
  useScrollToActive(container, activeId)

  return (
    <div ref={ref} className="w-full">
      {width === 0 || pages.length === 0 ? (
        <Skeleton className="mx-auto aspect-[8.5/11] w-full max-w-3xl rounded-md" />
      ) : isPdf ? (
        <PdfPages
          url={documentFileUrl(documentId, versionId)}
          pages={pages}
          width={width}
          highlights={highlights}
          activeId={activeId}
          onSelect={onSelect}
        />
      ) : blocks.data ? (
        <ReconstructedPages
          pages={pages}
          blocks={blocks.data}
          width={width}
          highlights={highlights}
          activeId={activeId}
          onSelect={onSelect}
        />
      ) : (
        <Skeleton className="mx-auto aspect-[8.5/11] rounded-md" style={{ width }} />
      )}
    </div>
  )
}
