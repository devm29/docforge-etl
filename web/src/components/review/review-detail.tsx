"use client"

import { CheckCircle2, ExternalLink, Loader2 } from "lucide-react"
import Link from "next/link"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { ConfidenceMeter, StatusBadge } from "@/components/status"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Kbd } from "@/components/ui/kbd"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { DocumentViewer } from "@/components/viewer/document-viewer"
import { useDocument, useResolveReview } from "@/lib/api/hooks"
import type { ReviewItem } from "@/lib/api/schemas"
import { displayValue, formatRelative, humanize } from "@/lib/format"
import { isShortcut } from "@/lib/keyboard"
import { parseEdited, placeholderFor, toEditable } from "@/lib/review-value"
import { cn } from "@/lib/utils"

export function ReviewDetail({ item, onResolved }: { item: ReviewItem; onResolved: () => void }) {
  const resolve = useResolveReview()
  const document = useDocument(item.document.id)
  const [draft, setDraft] = useState(() => toEditable(item.field.value))
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const pending = item.status === "pending"
  const complex = Array.isArray(item.field.value)
  const version = document.data?.versions.find((v) => v.id === item.version_id)

  async function submit(action: "approve" | "edit") {
    setError(null)
    if (action === "edit") {
      const parsed = parseEdited(draft, item.field.value)
      if (!parsed.ok) {
        setError(parsed.error)
        return
      }
      try {
        const result = await resolve.mutateAsync({ id: item.id, action: "edit", value: parsed.value })
        toast.success("Correction saved", { description: `Record is now ${humanize(result.extraction_status).toLowerCase()}.` })
        onResolved()
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : "The correction was rejected.")
      }
      return
    }
    try {
      const result = await resolve.mutateAsync({ id: item.id, action: "approve" })
      toast.success("Approved", { description: `Record is now ${humanize(result.extraction_status).toLowerCase()}.` })
      onResolved()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The approval was rejected.")
    }
  }

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!pending || resolve.isPending || !isShortcut(event)) return
      if (event.key === "a") {
        event.preventDefault()
        void submit("approve")
      } else if (event.key === "e") {
        event.preventDefault()
        ;(inputRef.current ?? textareaRef.current)?.focus()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  })

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-border/60 px-6 py-5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-[22px] leading-7 font-semibold tracking-tight">{humanize(item.field.path)}</h2>
          <StatusBadge status={item.reason} />
          <span className="ml-auto">
            <ConfidenceMeter value={item.field.confidence} />
          </span>
        </div>
        <p className="mt-1 flex items-center gap-1.5 text-[13px] text-muted-foreground">
          {humanize(item.schema_name)} ·{" "}
          <Link
            href={`/documents/${item.document.id}?field=${item.field.path}`}
            className="inline-flex items-center gap-1 text-primary hover:underline"
          >
            {item.document.filename}
            <ExternalLink className="size-3" aria-hidden />
          </Link>
        </p>
        <dl className="mt-4 grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl bg-secondary/70 px-4 py-3">
            <dt className="text-[12px] text-muted-foreground">{pending ? "Extracted value" : "Original value"}</dt>
            <dd className={cn("mt-0.5 text-[17px] font-semibold", item.original_value === null && "text-muted-foreground italic")}>
              {displayValue(item.original_value)}
            </dd>
          </div>
          <div className="rounded-xl bg-secondary/70 px-4 py-3">
            <dt className="text-[12px] text-muted-foreground">Evidence</dt>
            <dd className="mt-0.5 truncate font-mono text-[12px]" title={item.field.evidence ?? undefined}>
              {item.field.evidence ? `“${item.field.evidence}”` : "No supporting quote"}
              {item.field.page ? ` · p.${item.field.page}` : ""}
            </dd>
          </div>
        </dl>
        {item.field.issues.length > 0 ? (
          <ul className="mt-3 space-y-1 rounded-xl bg-destructive/8 px-4 py-3 text-[13px] text-destructive">
            {item.field.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto bg-secondary/60 px-6 py-6 dark:bg-background">
        {version ? (
          <DocumentViewer
            documentId={item.document.id}
            versionId={item.version_id}
            format={version.format}
            pages={version.pages}
            highlights={
              item.field.bbox && item.field.page
                ? [
                    {
                      id: item.field.id,
                      page: item.field.page,
                      bbox: item.field.bbox,
                      tone: item.reason === "validation_failed" ? "issue" : "field",
                      label: humanize(item.field.path),
                    },
                  ]
                : []
            }
            activeId={item.field.id}
          />
        ) : (
          <Skeleton className="mx-auto aspect-[8.5/11] w-full max-w-2xl rounded-md" />
        )}
      </div>

      {pending ? (
        <form
          className="material border-t border-border/60 bg-background/80 px-6 py-4 backdrop-blur-xl"
          onSubmit={(event) => {
            event.preventDefault()
            void submit("edit")
          }}
        >
          <Label htmlFor="correction" className="text-[13px] font-medium">
            Correct the value
          </Label>
          <div className="mt-1.5 flex flex-col gap-2 sm:flex-row sm:items-start">
            {complex ? (
              <Textarea
                id="correction"
                ref={textareaRef}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                className="min-h-28 flex-1 rounded-lg font-mono text-[12px]"
                aria-invalid={error !== null}
              />
            ) : (
              <Input
                id="correction"
                ref={inputRef}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder={placeholderFor(item.field.path)}
                className="h-9 flex-1 rounded-lg text-[14px] focus-visible:border-primary focus-visible:ring-4 focus-visible:ring-ring"
                aria-invalid={error !== null}
              />
            )}
            <div className="flex gap-2">
              <Button type="submit" variant="secondary" className="h-9" disabled={resolve.isPending}>
                Save correction
              </Button>
              <Button type="button" className="h-9" disabled={resolve.isPending} onClick={() => void submit("approve")}>
                {resolve.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <CheckCircle2 className="size-3.5" />}
                Approve
              </Button>
            </div>
          </div>
          {error ? (
            <p role="alert" className="mt-2 text-[12px] text-destructive">
              {error}
            </p>
          ) : (
            <p className="mt-2 hidden text-[12px] text-muted-foreground sm:block">
              <Kbd>A</Kbd> approve · <Kbd>E</Kbd> edit · <Kbd>↵</Kbd> save · <Kbd>↑</Kbd> <Kbd>↓</Kbd> move
            </p>
          )}
        </form>
      ) : (
        <div className="border-t border-border/60 px-6 py-4 text-[13px] text-muted-foreground">
          {item.status === "edited" ? "Corrected" : "Approved"} by {item.reviewer ?? "a reviewer"}
          {item.resolved_at ? ` ${formatRelative(item.resolved_at)}` : ""}
          {item.status === "edited" ? ` to ${displayValue(item.resolved_value)}` : ""}.
        </div>
      )}
    </div>
  )
}
