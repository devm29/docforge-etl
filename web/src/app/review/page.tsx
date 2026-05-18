"use client"

import { ChevronLeft, Inbox, Loader2 } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { EmptyState } from "@/components/empty-state"
import { Toolbar } from "@/components/page-header"
import { ReviewDetail } from "@/components/review/review-detail"
import { Segmented } from "@/components/segmented"
import { StatusBadge } from "@/components/status"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useReviews } from "@/lib/api/hooks"
import { humanize } from "@/lib/format"
import { cn } from "@/lib/utils"

const STATUSES = [
  { value: "pending", label: "To review" },
  { value: "approved", label: "Approved" },
  { value: "edited", label: "Corrected" },
] as const
type Status = (typeof STATUSES)[number]["value"]

export default function ReviewPage() {
  const [status, setStatus] = useState<Status>("pending")
  const reviews = useReviews(status)
  const items = useMemo(() => reviews.data?.pages.flatMap((page) => page.items) ?? [], [reviews.data])
  const total = reviews.data?.pages[0]?.total
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [mobileDetail, setMobileDetail] = useState(false)
  const selected = items.find((item) => item.id === selectedId) ?? items[0] ?? null

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return
      const target = event.target
      if (event.metaKey || event.ctrlKey || event.altKey) return
      if (target instanceof HTMLElement && target.closest("input, textarea, select, [contenteditable='true']")) return
      event.preventDefault()
      const index = items.findIndex((item) => item.id === selected?.id)
      const next = items[Math.min(items.length - 1, Math.max(0, index + (event.key === "ArrowDown" ? 1 : -1)))]
      if (next) setSelectedId(next.id)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [items, selected])

  function advance() {
    const index = items.findIndex((item) => item.id === selected?.id)
    const next = items[index + 1] ?? items[index - 1]
    setSelectedId(next?.id ?? null)
  }

  return (
    <>
      <Toolbar title="Review">
        <Segmented label="Review status" value={status} options={STATUSES} onChange={(value) => {
          setStatus(value)
          setSelectedId(null)
        }} />
      </Toolbar>
      <div className="grid h-[calc(100dvh-52px)] grid-cols-1 md:grid-cols-[340px_minmax(0,1fr)]">
        <aside
          className={cn("min-h-0 overflow-y-auto border-r border-border/60", mobileDetail && "hidden md:block")}
          aria-label="Review queue"
        >
          <div className="px-4 pt-5 pb-3">
            <h2 className="text-[22px] leading-7 font-semibold tracking-tight">
              {status === "pending" ? "To review" : status === "approved" ? "Approved" : "Corrected"}
            </h2>
            <p className="text-[13px] text-muted-foreground tabular-nums">
              {total !== undefined ? `${total} field${total === 1 ? "" : "s"}` : "Loading"}
              {status === "pending" ? " below the confidence threshold or failing validation" : ""}
            </p>
          </div>
          {reviews.isLoading ? (
            <div className="space-y-2 px-4">
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-14 rounded-lg" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <EmptyState
              icon={Inbox}
              title={status === "pending" ? "All caught up" : "Nothing here yet"}
              description={
                status === "pending"
                  ? "Every extracted field is above the confidence threshold and passes validation."
                  : "Resolved review items will appear here."
              }
            />
          ) : (
            <ul aria-label="Review items" className="space-y-0.5 px-2 pb-4">
              {items.map((item) => {
                const active = item.id === selected?.id
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      aria-current={active ? "true" : undefined}
                      onClick={() => {
                        setSelectedId(item.id)
                        setMobileDetail(true)
                      }}
                      className={cn(
                        "w-full rounded-lg px-3 py-2.5 text-left transition-colors duration-150 outline-none focus-visible:ring-4 focus-visible:ring-ring",
                        active ? "bg-primary/10" : "hover:bg-accent/50"
                      )}
                    >
                      <div className="flex items-center gap-2">
                        <span className="truncate text-[14px] font-medium">{humanize(item.field.path)}</span>
                        <span className="ml-auto text-[12px] text-muted-foreground tabular-nums">
                          {Math.round(item.field.confidence * 100)}%
                        </span>
                      </div>
                      <div className="mt-0.5 flex items-center gap-2">
                        <span className="truncate text-[12px] text-muted-foreground">{item.document.filename}</span>
                        <StatusBadge status={item.reason} className="ml-auto" />
                      </div>
                    </button>
                  </li>
                )
              })}
              {reviews.hasNextPage ? (
                <li className="px-1 pt-2">
                  <Button
                    variant="ghost"
                    className="h-8 w-full text-[13px] text-primary"
                    disabled={reviews.isFetchingNextPage}
                    onClick={() => void reviews.fetchNextPage()}
                  >
                    {reviews.isFetchingNextPage ? <Loader2 className="size-3.5 animate-spin" /> : null}
                    Show more ({items.length} of {total})
                  </Button>
                </li>
              ) : null}
            </ul>
          )}
        </aside>
        <section className={cn("min-h-0 md:flex md:flex-col", mobileDetail ? "flex flex-col" : "hidden")} aria-label="Review detail">
          {mobileDetail ? (
            <button
              type="button"
              onClick={() => setMobileDetail(false)}
              className="flex h-11 items-center gap-1 border-b border-border/60 px-4 text-[15px] text-primary md:hidden"
            >
              <ChevronLeft className="size-4" aria-hidden />
              Queue
            </button>
          ) : null}
          {selected ? (
            <div className="min-h-0 flex-1">
              <ReviewDetail key={selected.id} item={selected} onResolved={advance} />
            </div>
          ) : null}
        </section>
      </div>
    </>
  )
}
