"use client"

import { ChevronLeft, ChevronRight, FileSearch, FileSpreadsheet, FileText, FileType, type LucideIcon } from "lucide-react"
import Link from "next/link"
import { useState } from "react"

import { EmptyState } from "@/components/empty-state"
import { PageTitle, Toolbar } from "@/components/page-header"
import { RunPipelineButton } from "@/components/run-pipeline-button"
import { SearchField } from "@/components/search-field"
import { Segmented } from "@/components/segmented"
import { ConfidenceMeter, StatusBadge } from "@/components/status"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useDebouncedValue } from "@/hooks/use-debounced-value"
import { DOCUMENTS_PAGE_SIZE, useDocuments } from "@/lib/api/hooks"
import { formatRelative } from "@/lib/format"

const KINDS = [
  { value: "all", label: "All" },
  { value: "invoice", label: "Invoices" },
  { value: "contract", label: "Contracts" },
] as const
type Kind = (typeof KINDS)[number]["value"]

const FORMAT_ICONS = { pdf: FileText, docx: FileType, xlsx: FileSpreadsheet, csv: FileSpreadsheet } as const

function isKnownFormat(format: string): format is keyof typeof FORMAT_ICONS {
  return Object.hasOwn(FORMAT_ICONS, format)
}

function iconFor(format: string | null): LucideIcon {
  return format !== null && isKnownFormat(format) ? FORMAT_ICONS[format] : FileText
}

export default function DocumentsPage() {
  const [kind, setKind] = useState<Kind>("all")
  const [query, setQuery] = useState("")
  const [offset, setOffset] = useState(0)
  const filter = useDebouncedValue(query.trim())
  const { data, isLoading } = useDocuments({
    offset,
    ...(kind === "all" ? {} : { kind }),
    ...(filter ? { q: filter } : {}),
  })
  const shownTo = data ? Math.min(data.offset + data.items.length, data.total) : 0

  return (
    <>
      <Toolbar title="Documents">
        <RunPipelineButton />
      </Toolbar>
      <main className="mx-auto w-full max-w-6xl space-y-6 px-6 py-8">
        <PageTitle
          title="Documents"
          subtitle={data ? `${data.total} documents tracked by content hash` : "Loading documents"}
        >
          <SearchField
            value={query}
            onChange={(next) => {
              setQuery(next)
              setOffset(0)
            }}
            placeholder="Filter by path"
            className="w-64"
          />
        </PageTitle>
        <Segmented
          label="Document type"
          value={kind}
          options={KINDS}
          onChange={(next) => {
            setKind(next)
            setOffset(0)
          }}
        />

        <Card className="gap-0 overflow-hidden rounded-xl p-0 shadow-[var(--shadow-xs)]">
          <Table className="table-fixed">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="h-10 w-[46%] pl-5 text-[12px] font-medium text-muted-foreground">Name</TableHead>
                <TableHead className="h-10 w-[22%] text-[12px] font-medium text-muted-foreground">Extraction</TableHead>
                <TableHead className="h-10 w-[14%] text-[12px] font-medium text-muted-foreground">Confidence</TableHead>
                <TableHead className="h-10 w-[7%] text-right text-[12px] font-medium text-muted-foreground">
                  Version
                </TableHead>
                <TableHead className="h-10 w-[11%] pr-5 text-right text-[12px] font-medium text-muted-foreground">
                  Updated
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading
                ? Array.from({ length: 6 }, (_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={5} className="px-5">
                        <Skeleton className="h-8" />
                      </TableCell>
                    </TableRow>
                  ))
                : data?.items.map((doc) => {
                    const Icon = iconFor(doc.format)
                    return (
                      <TableRow key={doc.id} className="group h-14 hover:bg-accent/50">
                        <TableCell className="pl-5">
                          <Link
                            href={`/documents/${doc.id}`}
                            className="flex items-center gap-3 rounded-md outline-none focus-visible:ring-4 focus-visible:ring-ring"
                          >
                            <Icon className="size-5 shrink-0 text-muted-foreground" strokeWidth={1.5} aria-hidden />
                            <span className="min-w-0">
                              <span className="block truncate text-[14px] font-medium">{doc.filename}</span>
                              <span className="block truncate text-[12px] text-muted-foreground">
                                {doc.kind ? doc.kind.charAt(0).toUpperCase() + doc.kind.slice(1) : "Unclassified"} ·{" "}
                                {doc.uri}
                              </span>
                            </span>
                          </Link>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1.5">
                            {doc.status === "failed" ? (
                              <StatusBadge status="failed">Failed to process</StatusBadge>
                            ) : doc.extraction_status ? (
                              <StatusBadge status={doc.extraction_status} />
                            ) : (
                              <span className="text-[13px] text-muted-foreground">Indexed only</span>
                            )}
                            {doc.pending_reviews > 0 ? (
                              <span className="text-[12px] text-muted-foreground tabular-nums">
                                {doc.pending_reviews} to review
                              </span>
                            ) : null}
                          </div>
                        </TableCell>
                        <TableCell>
                          {doc.average_confidence !== null ? <ConfidenceMeter value={doc.average_confidence} /> : null}
                        </TableCell>
                        <TableCell className="text-right text-[13px] tabular-nums">
                          {doc.version_no ? `v${doc.version_no}` : "-"}
                        </TableCell>
                        <TableCell className="pr-5 text-right text-[13px] text-muted-foreground">
                          {formatRelative(doc.updated_at)}
                        </TableCell>
                      </TableRow>
                    )
                  })}
            </TableBody>
          </Table>
          {data && data.items.length === 0 ? (
            <EmptyState
              icon={FileSearch}
              title="No documents match"
              description="Try a different filter, or run the pipeline to ingest the source folder."
            />
          ) : null}
          {data && data.total > DOCUMENTS_PAGE_SIZE ? (
            <nav
              aria-label="Pages"
              className="flex items-center justify-end gap-2 border-t border-border/60 px-5 py-2.5 text-[12px] text-muted-foreground tabular-nums"
            >
              <span>
                Showing {data.offset + 1}–{shownTo} of {data.total}
              </span>
              <Button
                variant="ghost"
                size="icon"
                className="size-7"
                aria-label="Previous page"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - DOCUMENTS_PAGE_SIZE))}
              >
                <ChevronLeft className="size-4" strokeWidth={1.75} />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="size-7"
                aria-label="Next page"
                disabled={shownTo >= data.total}
                onClick={() => setOffset(offset + DOCUMENTS_PAGE_SIZE)}
              >
                <ChevronRight className="size-4" strokeWidth={1.75} />
              </Button>
            </nav>
          ) : null}
        </Card>
      </main>
    </>
  )
}
