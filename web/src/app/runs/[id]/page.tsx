"use client"

import { ChevronLeft, ChevronRight, Download, RotateCcw, Workflow } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { use, useState } from "react"
import { toast } from "sonner"

import { EmptyState } from "@/components/empty-state"
import { Kpi } from "@/components/kpi"
import { PageTitle, Toolbar } from "@/components/page-header"
import { runTitle } from "@/components/runs-list"
import { StageStrip } from "@/components/runs/stage-strip"
import { RunTimeline } from "@/components/runs/timeline"
import { StatusBadge } from "@/components/status"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { exportUrl } from "@/lib/api/client"
import { TIMELINE_PAGE_SIZE, isActiveRun, useReplayDeadLetter, useRun, useTimeline } from "@/lib/api/hooks"
import { formatCompact, formatDateTime, formatDuration, formatInt, formatUsd, runDuration } from "@/lib/format"

export default function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const run = useRun(id)
  const active = run.data ? isActiveRun(run.data.run.status) : false
  const [offset, setOffset] = useState(0)
  const timeline = useTimeline(id, offset, active)
  const replay = useReplayDeadLetter()

  if (run.isError) {
    return (
      <>
        <Toolbar title="Run" />
        <EmptyState icon={Workflow} title="Run not found" description="The link may be out of date." />
      </>
    )
  }

  const data = run.data
  const summary = data?.run
  const duration = summary ? runDuration(summary.started_at, summary.finished_at) : null

  async function onReplay(deadLetterId: string) {
    try {
      const next = await replay.mutateAsync(deadLetterId)
      toast.success("Replay queued", {
        description: "Stages that already succeeded will be served from the cache.",
        action: { label: "View", onClick: () => router.push(`/runs/${next.id}`) },
      })
    } catch (error) {
      toast.error("Replay failed", { description: error instanceof Error ? error.message : undefined })
    }
  }

  return (
    <>
      <Toolbar
        leading={
          <Link
            href="/runs"
            className="-ml-1 rounded-md p-0.5 text-muted-foreground outline-none hover:text-foreground focus-visible:ring-4 focus-visible:ring-ring"
            aria-label="Back to runs"
          >
            <ChevronLeft className="size-4" strokeWidth={1.75} />
          </Link>
        }
        title={
          <span className="flex items-center gap-2">
            Run
            {summary ? <StatusBadge status={summary.status} /> : null}
          </span>
        }
      >
        {summary?.has_export ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="secondary" className="h-8 text-[13px]">
                <Download className="size-3.5" strokeWidth={1.75} />
                Parquet
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52 rounded-xl p-1">
              <DropdownMenuLabel className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                Export this run
              </DropdownMenuLabel>
              {(["chunks", "fields", "stages"] as const).map((table) => (
                <DropdownMenuItem key={table} asChild className="h-8 rounded-md text-[13px]">
                  <a href={exportUrl(id, table)} download>
                    {table === "chunks" ? "Chunks with vectors" : table === "fields" ? "Extracted fields" : "Stage ledger"}
                  </a>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </Toolbar>

      <main className="mx-auto w-full max-w-6xl space-y-8 px-6 py-8">
        {summary ? (
          <PageTitle
            title={runTitle(summary)}
            subtitle={
              <span className="flex flex-wrap items-center gap-2 tabular-nums">
                <StatusBadge status={summary.status} />
                {formatDateTime(summary.created_at)}
                {duration !== null ? ` · ${formatDuration(duration)}` : ""} · pipeline {summary.pipeline_version}
              </span>
            }
          />
        ) : (
          <Skeleton className="h-16 w-80 rounded-lg" />
        )}

        {summary?.error ? (
          <p role="alert" className="rounded-xl bg-destructive/8 px-4 py-3 text-[13px] text-destructive">
            {summary.error}
          </p>
        ) : null}

        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {summary ? (
            <>
              <Kpi
                label="Documents scanned"
                value={formatInt(summary.docs_seen)}
                footnote={`${summary.docs_changed} changed · ${summary.docs_unchanged} unchanged${
                  summary.docs_removed ? ` · ${summary.docs_removed} removed` : ""
                }`}
              />
              <Kpi
                label="Processed"
                value={`${summary.docs_succeeded + summary.docs_deduplicated}/${summary.docs_changed}`}
                tone={summary.docs_failed > 0 ? "warning" : undefined}
                footnote={summary.docs_failed ? `${summary.docs_failed} sent to the dead-letter queue` : "No failures"}
              />
              <Kpi
                label={summary.cost_estimated ? "Extraction spend (est.)" : "Extraction spend"}
                value={formatUsd(summary.cost_usd)}
                footnote={`${formatCompact(summary.input_tokens + summary.output_tokens)} tokens`}
              />
              <Kpi
                label="Saved"
                value={formatUsd(summary.cost_saved_usd)}
                tone="success"
                footnote="Unchanged documents and cache hits"
              />
            </>
          ) : (
            Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[118px] rounded-xl" />)
          )}
        </section>

        {data && data.stages.length > 0 ? (
          <section className="space-y-3">
            <h3 className="text-[17px] font-semibold tracking-tight">Stages</h3>
            <StageStrip stages={data.stages} />
          </section>
        ) : null}

        <Card className="gap-0 rounded-xl p-5 shadow-[var(--shadow-xs)]">
          <div className="mb-4 flex items-center gap-3">
            <h3 className="text-[17px] font-semibold tracking-tight">Timeline</h3>
            {timeline.data && timeline.data.total > TIMELINE_PAGE_SIZE ? (
              <div className="ml-auto flex items-center gap-2 text-[12px] text-muted-foreground tabular-nums">
                <span>
                  {offset + 1}–{Math.min(offset + TIMELINE_PAGE_SIZE, timeline.data.total)} of {timeline.data.total}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7"
                  aria-label="Previous documents"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - TIMELINE_PAGE_SIZE))}
                >
                  <ChevronLeft className="size-4" strokeWidth={1.75} />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7"
                  aria-label="Next documents"
                  disabled={offset + TIMELINE_PAGE_SIZE >= timeline.data.total}
                  onClick={() => setOffset(offset + TIMELINE_PAGE_SIZE)}
                >
                  <ChevronRight className="size-4" strokeWidth={1.75} />
                </Button>
              </div>
            ) : null}
          </div>
          {timeline.data && timeline.data.documents.length > 0 ? (
            <RunTimeline timeline={timeline.data} />
          ) : timeline.isLoading || active ? (
            <Skeleton className="h-40" />
          ) : (
            <p className="text-[13px] text-muted-foreground">
              {summary?.status === "failed" && summary.docs_changed === 0
                ? "The run stopped before any document was processed."
                : "No document changed, so no stage ran. That is the point of incremental processing."}
            </p>
          )}
        </Card>

        {data && data.dead_letters.length > 0 ? (
          <Card className="gap-0 overflow-hidden rounded-xl p-0 shadow-[var(--shadow-xs)]">
            <div className="px-5 pt-5 pb-3">
              <h3 className="text-[17px] font-semibold tracking-tight">Dead letters</h3>
              <p className="text-[13px] text-muted-foreground">
                Documents that failed after retries. Fix the cause, then replay them.
              </p>
            </div>
            <ul className="divide-y divide-border border-t border-border">
              {data.dead_letters.map((letter) => (
                <li key={letter.id} className="flex items-center gap-4 px-5 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-2 text-[14px] font-medium">
                      <span className="truncate">{letter.filename}</span>
                      <StatusBadge status={letter.status} />
                    </p>
                    <p className="truncate text-[12px] text-muted-foreground">
                      {letter.stage} stage · {letter.error_type} · {letter.attempts} attempt
                      {letter.attempts === 1 ? "" : "s"} · {letter.error}
                    </p>
                  </div>
                  {letter.status === "open" ? (
                    <Button
                      variant="secondary"
                      className="h-8 text-[13px]"
                      disabled={replay.isPending}
                      onClick={() => void onReplay(letter.id)}
                    >
                      <RotateCcw className="size-3.5" strokeWidth={1.75} />
                      Replay
                    </Button>
                  ) : letter.replay_run_id ? (
                    <Link href={`/runs/${letter.replay_run_id}`} className="text-[13px] text-primary hover:underline">
                      View replay
                    </Link>
                  ) : null}
                </li>
              ))}
            </ul>
          </Card>
        ) : null}
      </main>
    </>
  )
}
