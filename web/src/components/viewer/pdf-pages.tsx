"use client"

import { useEffect, useRef, useState, type ReactNode } from "react"
import { Document, Page, pdfjs } from "react-pdf"

import { Skeleton } from "@/components/ui/skeleton"
import type { PageSize } from "@/lib/api/schemas"

import { pageScale, type Highlight } from "./geometry"
import { HighlightLayer } from "./highlight-layer"

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString()

/** Renders its children only once the page is near the viewport, and keeps them afterwards. */
function WhenNear({ children, fallback }: { children: ReactNode; fallback: ReactNode }) {
  const ref = useRef<HTMLDivElement | null>(null)
  const [near, setNear] = useState(false)
  useEffect(() => {
    const element = ref.current
    if (!element || near) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) setNear(true)
      },
      { rootMargin: "800px 0px" }
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [near])
  return (
    <div ref={ref} className="h-full w-full">
      {near ? children : fallback}
    </div>
  )
}

export default function PdfPages({
  url,
  pages,
  width,
  highlights,
  activeId,
  onSelect,
}: {
  url: string
  pages: PageSize[]
  width: number
  highlights: Highlight[]
  activeId: string | null
  onSelect?: ((id: string) => void) | undefined
}) {
  const [failed, setFailed] = useState<string | null>(null)

  if (failed) {
    return (
      <p role="alert" className="py-10 text-center text-[13px] text-destructive">
        The PDF could not be rendered: {failed}
      </p>
    )
  }

  return (
    <Document
      file={url}
      onLoadError={(error) => setFailed(error.message)}
      loading={<Skeleton className="mx-auto aspect-[8.5/11] rounded-md" style={{ width }} />}
      className="flex flex-col items-center gap-6"
    >
      {pages.map((page) => {
        const scale = pageScale(width, page.width)
        return (
          <div
            key={page.number}
            className="relative overflow-hidden rounded-[4px] bg-white shadow-[var(--shadow-md)] ring-1 ring-black/5"
            style={{ width, height: page.height * scale }}
            data-page={page.number}
          >
            <WhenNear fallback={<Skeleton className="h-full w-full rounded-none" />}>
              <Page
                pageNumber={page.number}
                width={width}
                renderTextLayer={false}
                renderAnnotationLayer={false}
                loading={<Skeleton className="h-full w-full" />}
              />
            </WhenNear>
            <HighlightLayer
              highlights={highlights.filter((h) => h.page === page.number)}
              scale={scale}
              activeId={activeId}
              onSelect={onSelect}
            />
            <span className="absolute right-2 bottom-2 rounded-full bg-black/55 px-2 py-0.5 text-[11px] font-medium text-white tabular-nums">
              {page.number} / {pages.length}
            </span>
          </div>
        )
      })}
    </Document>
  )
}
