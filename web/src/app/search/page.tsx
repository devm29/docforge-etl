"use client"

import { FileText, SearchX, Table2 } from "lucide-react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { useState } from "react"

import { EmptyState } from "@/components/empty-state"
import { PageTitle, Toolbar } from "@/components/page-header"
import { SearchField } from "@/components/search-field"
import { Segmented } from "@/components/segmented"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useDebouncedValue } from "@/hooks/use-debounced-value"
import { useSearch } from "@/lib/api/hooks"
import { humanize } from "@/lib/format"

const KINDS = [
  { value: "all", label: "Everything" },
  { value: "invoice", label: "Invoices" },
  { value: "contract", label: "Contracts" },
] as const
type Kind = (typeof KINDS)[number]["value"]

const SUGGESTIONS = ["governing law", "automatic renewal notice", "freight surcharge", "payment terms net 30"]

export default function SearchPage() {
  const initial = useSearchParams().get("q") ?? ""
  const [query, setQuery] = useState(initial)
  const [kind, setKind] = useState<Kind>("all")
  const debounced = useDebouncedValue(query.trim())
  const results = useSearch(debounced, kind === "all" ? undefined : kind)
  const searching = debounced.length >= 2

  return (
    <>
      <Toolbar title="Search" />
      <main className="mx-auto w-full max-w-3xl space-y-6 px-6 py-8">
        <PageTitle
          title="Search"
          subtitle={
            results.data
              ? `Semantic retrieval over current chunks with ${results.data.model.replace("fastembed:", "")}`
              : "Semantic retrieval over every current chunk, the same read path a RAG app would use"
          }
        />
        <SearchField value={query} onChange={setQuery} placeholder="Ask about your documents" autoFocus />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Segmented label="Document type" value={kind} options={KINDS} onChange={setKind} />
          {!searching ? (
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => setQuery(suggestion)}
                  className="h-7 rounded-full bg-secondary px-3 text-[12px] transition-colors hover:bg-accent"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        {searching && results.isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }, (_, i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
          </div>
        ) : null}

        {results.data && searching ? (
          results.data.hits.length === 0 ? (
            <EmptyState icon={SearchX} title="No matches" description="Try different words, or widen the filter." />
          ) : (
            <ol className="space-y-3" aria-live="polite">
              {results.data.hits.map((hit) => (
                <li key={hit.chunk_id}>
                  <Link
                    href={`/documents/${hit.document.id}?panel=chunks&chunk=${hit.chunk_id}`}
                    className="block rounded-xl outline-none focus-visible:ring-4 focus-visible:ring-ring"
                  >
                    <Card className="gap-1.5 rounded-xl p-4 shadow-[var(--shadow-xs)] transition-colors hover:bg-accent/40">
                      <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
                        <FileText className="size-3.5" strokeWidth={1.75} aria-hidden />
                        <span className="truncate font-medium text-foreground">{hit.document.filename}</span>
                        {hit.document.kind ? <span>· {humanize(hit.document.kind)}</span> : null}
                        <span>· page {hit.page_start}</span>
                        <span className="ml-auto font-medium text-primary tabular-nums">{hit.score.toFixed(3)}</span>
                      </div>
                      {hit.heading_path.length > 0 ? (
                        <p className="text-[12px] text-muted-foreground">{hit.heading_path.join(" › ")}</p>
                      ) : null}
                      <p className="line-clamp-3 text-[14px] leading-[21px] whitespace-pre-line">
                        {hit.text.includes(" | ") ? <Table2 className="mr-1 inline size-3.5 text-muted-foreground" aria-hidden /> : null}
                        {hit.text}
                      </p>
                    </Card>
                  </Link>
                </li>
              ))}
            </ol>
          )
        ) : null}
      </main>
    </>
  )
}
