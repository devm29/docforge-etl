"use client"

import { ChevronLeft, FileWarning } from "lucide-react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { use, useMemo } from "react"

import { EmptyState } from "@/components/empty-state"
import { ChunkList } from "@/components/inspector/chunk-list"
import { ExtractionSummary } from "@/components/inspector/extraction-summary"
import { FieldList } from "@/components/inspector/field-list"
import { VersionList } from "@/components/inspector/version-list"
import { Toolbar } from "@/components/page-header"
import { StatusBadge } from "@/components/status"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { DocumentViewer } from "@/components/viewer/document-viewer"
import type { Highlight } from "@/components/viewer/geometry"
import { useChunks, useDocument, useExtraction } from "@/lib/api/hooks"
import { humanize } from "@/lib/format"

type Panel = "fields" | "json" | "chunks" | "versions"
const PANELS: readonly Panel[] = ["fields", "json", "chunks", "versions"]

export default function DocumentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const pathname = usePathname()
  const search = useSearchParams()
  const versionParam = search.get("version") ?? undefined
  const selectedField = search.get("field")
  const selectedChunk = search.get("chunk")
  const panelParam = search.get("panel")
  const panel: Panel = PANELS.find((p) => p === panelParam) ?? (selectedChunk ? "chunks" : "fields")

  const document = useDocument(id)
  const versionId = versionParam ?? document.data?.current_version?.id
  const extraction = useExtraction(id, versionParam)
  const chunks = useChunks(id, versionParam)

  const version = document.data?.versions.find((v) => v.id === versionId) ?? document.data?.current_version ?? null
  const isHistorical = Boolean(versionParam && versionParam !== document.data?.current_version?.id)

  function update(next: Record<string, string | null>) {
    const params = new URLSearchParams(search.toString())
    for (const [key, value] of Object.entries(next)) {
      if (value === null) params.delete(key)
      else params.set(key, value)
    }
    router.replace(`${pathname}?${params.toString()}`, { scroll: false })
  }

  const highlights = useMemo<Highlight[]>(() => {
    if (panel === "chunks") {
      return (chunks.data ?? []).flatMap((chunk) =>
        chunk.spans.map((span, index) => ({
          id: `${chunk.id}:${index}`,
          page: span.page,
          bbox: span.bbox,
          tone: "chunk" as const,
          label: `Chunk ${chunk.ordinal + 1}`,
        }))
      )
    }
    return (extraction.data?.fields ?? []).flatMap((field) =>
      field.bbox && field.page
        ? [
            {
              id: field.id,
              page: field.page,
              bbox: field.bbox,
              tone: field.issues.length > 0 ? ("issue" as const) : ("field" as const),
              label: humanize(field.path),
            },
          ]
        : []
    )
  }, [panel, chunks.data, extraction.data])

  const activeHighlight =
    panel === "chunks"
      ? selectedChunk
      : (extraction.data?.fields.find((f) => f.path === selectedField)?.id ?? null)

  function selectHighlight(highlightId: string) {
    if (panel === "chunks") {
      update({ chunk: highlightId.split(":")[0] ?? null })
      return
    }
    const field = extraction.data?.fields.find((f) => f.id === highlightId)
    if (field) update({ field: field.path })
  }

  if (document.isError) {
    return (
      <>
        <Toolbar title="Document" />
        <EmptyState
          icon={FileWarning}
          title="Document not found"
          description="It may have been removed from the source, or the link is out of date."
          action={
            <Button asChild variant="secondary">
              <Link href="/documents">Back to documents</Link>
            </Button>
          }
        />
      </>
    )
  }

  const doc = document.data
  return (
    <>
      <Toolbar
        title={
          <span className="flex items-center gap-2">
            <Link
              href="/documents"
              className="-ml-1 rounded-md p-0.5 text-muted-foreground hover:text-foreground"
              aria-label="Back to documents"
            >
              <ChevronLeft className="size-4" strokeWidth={1.75} />
            </Link>
            <span className="truncate">{doc?.filename ?? "Document"}</span>
            {doc ? <StatusBadge status={doc.status} /> : null}
          </span>
        }
      >
        {version ? (
          <span className="hidden text-[12px] text-muted-foreground tabular-nums sm:inline">
            v{version.version_no} of {doc?.versions.length ?? 1}
            {isHistorical ? " · historical" : ""}
          </span>
        ) : null}
      </Toolbar>

      <div className="grid min-h-[calc(100dvh-52px)] grid-cols-1 xl:grid-cols-[minmax(0,1fr)_420px]">
        <section className="min-w-0 bg-secondary/60 px-4 py-6 sm:px-8 dark:bg-background" aria-label="Document preview">
          {isHistorical ? (
            <div className="mx-auto mb-4 flex max-w-3xl items-center justify-between rounded-xl bg-warning/12 px-4 py-2 text-[13px]">
              <span>You are viewing an earlier version of this document.</span>
              <Link href={`/documents/${id}`} className="font-medium text-primary hover:underline">
                Show current
              </Link>
            </div>
          ) : null}
          {doc && version ? (
            <DocumentViewer
              documentId={id}
              versionId={versionParam}
              format={version.format}
              pages={version.pages}
              highlights={highlights}
              activeId={activeHighlight}
              onSelect={selectHighlight}
            />
          ) : doc && !version ? (
            <EmptyState
              icon={FileWarning}
              title="Nothing to show yet"
              description="This document has not been processed successfully. Check the dead-letter queue on the run page."
            />
          ) : (
            <Skeleton className="mx-auto aspect-[8.5/11] w-full max-w-3xl rounded-md" />
          )}
        </section>

        <aside className="border-l border-border/60 bg-background xl:sticky xl:top-13 xl:h-[calc(100dvh-52px)] xl:overflow-y-auto">
          <div className="space-y-5 p-5">
            {extraction.data ? (
              <ExtractionSummary extraction={extraction.data} />
            ) : extraction.isLoading ? (
              <Skeleton className="h-28 rounded-xl" />
            ) : (
              <div>
                <h3 className="text-[17px] font-semibold tracking-tight">Indexed for retrieval</h3>
                <p className="mt-1 text-[13px] text-muted-foreground">
                  No registered schema matched this document, so it was chunked and embedded without extraction.
                </p>
              </div>
            )}

            <Tabs value={panel} onValueChange={(value) => update({ panel: value })}>
              <TabsList className="grid h-8 w-full grid-cols-4 rounded-lg bg-secondary p-0.5">
                {PANELS.map((value) => (
                  <TabsTrigger
                    key={value}
                    value={value}
                    className="rounded-md text-[13px] data-[state=active]:bg-background data-[state=active]:shadow-[var(--shadow-sm)]"
                  >
                    {value === "json" ? "JSON" : humanize(value)}
                  </TabsTrigger>
                ))}
              </TabsList>
              <TabsContent value="fields" className="mt-4">
                {extraction.data ? (
                  <FieldList
                    fields={extraction.data.fields}
                    activeId={activeHighlight}
                    onSelect={(field) => update({ field: field.path })}
                  />
                ) : extraction.isLoading ? (
                  <Skeleton className="h-64 rounded-xl" />
                ) : (
                  <p className="text-[13px] text-muted-foreground">No extracted fields.</p>
                )}
              </TabsContent>
              <TabsContent value="json" className="mt-4">
                <pre className="overflow-x-auto rounded-xl bg-secondary p-4 font-mono text-[12px] leading-5">
                  {JSON.stringify(extraction.data?.data ?? null, null, 2)}
                </pre>
              </TabsContent>
              <TabsContent value="chunks" className="mt-4">
                {chunks.data ? (
                  <ChunkList
                    chunks={chunks.data}
                    activeId={selectedChunk}
                    onSelect={(chunk) => update({ chunk: chunk.id })}
                  />
                ) : (
                  <Skeleton className="h-40 rounded-xl" />
                )}
              </TabsContent>
              <TabsContent value="versions" className="mt-4">
                {doc ? <VersionList documentId={id} versions={doc.versions} activeVersionId={versionId} /> : null}
              </TabsContent>
            </Tabs>
          </div>
        </aside>
      </div>
    </>
  )
}
