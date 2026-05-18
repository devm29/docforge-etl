"use client"

import { AlertTriangle, ChevronRight, Workflow } from "lucide-react"
import Link from "next/link"

import { EmptyState } from "@/components/empty-state"
import { Kpi } from "@/components/kpi"
import { PageTitle, Toolbar } from "@/components/page-header"
import { RunPipelineButton } from "@/components/run-pipeline-button"
import { RunRow } from "@/components/runs-list"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useOpenDeadLetters, useOverview } from "@/lib/api/hooks"
import { formatCompact, formatInt, formatPercent, formatUsd, humanize } from "@/lib/format"

export default function OverviewPage() {
  const { data, isLoading, isError } = useOverview()
  const deadLetters = useOpenDeadLetters()
  const latestLetter = deadLetters.data?.items[0]
  const totalSpend = data ? data.cost_total_usd + data.cost_saved_usd : 0

  return (
    <>
      <Toolbar title="Overview">{data && data.recent_runs.length === 0 ? null : <RunPipelineButton />}</Toolbar>
      <main className="mx-auto w-full max-w-6xl space-y-8 px-6 py-8">
        <PageTitle
          title="Overview"
          subtitle="Every document is parsed, chunked, embedded and extracted once per content change."
        />
        {isError ? (
          <Card className="rounded-xl p-0">
            <EmptyState
              icon={AlertTriangle}
              title="Can't reach the API"
              description="Start the backend on port 8103, then refresh. The web app proxies /api to it."
            />
          </Card>
        ) : null}

        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Key figures">
          {isLoading || !data ? (
            Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[118px] rounded-xl" />)
          ) : (
            <>
              <Kpi
                label="Documents"
                value={formatInt(data.documents_total)}
                footnote={Object.entries(data.documents_by_kind)
                  .map(([kind, count]) => `${count} ${kind === "unclassified" ? "other" : `${kind}s`}`)
                  .join(" · ")}
              />
              <Kpi
                label="Awaiting review"
                value={formatInt(data.pending_reviews)}
                tone={data.pending_reviews > 0 ? "warning" : undefined}
                footnote={
                  <Link href="/review" className="text-primary hover:underline">
                    Open the review queue
                  </Link>
                }
              />
              <Kpi
                label={data.cost_estimated ? "Extraction spend (est.)" : "Extraction spend"}
                value={formatUsd(data.cost_total_usd)}
                footnote={`${formatCompact(data.tokens_total)} tokens across ${data.runs_total} runs`}
              />
              <Kpi
                label="Saved by incrementality"
                value={formatUsd(data.cost_saved_usd)}
                tone="success"
                footnote={
                  totalSpend > 0
                    ? `${formatPercent(data.cost_saved_usd / totalSpend)} of the cost of reprocessing everything`
                    : "Nothing reprocessed yet"
                }
              />
            </>
          )}
        </section>

        <section className="grid gap-4 lg:grid-cols-3">
          <Card className="gap-0 overflow-hidden rounded-xl p-0 shadow-[var(--shadow-xs)] lg:col-span-2">
            <div className="flex items-center justify-between px-5 pt-5 pb-3">
              <h3 className="text-[17px] font-semibold tracking-tight">Recent runs</h3>
              <Link href="/runs" className="text-[13px] text-primary hover:underline">
                Show all
              </Link>
            </div>
            {data && data.recent_runs.length === 0 ? (
              <EmptyState
                icon={Workflow}
                title="No runs yet"
                description="Run the pipeline to ingest the documents in the source folder."
                action={<RunPipelineButton />}
              />
            ) : (
              <div className="divide-y divide-border border-t border-border">
                {(data?.recent_runs ?? []).map((run) => (
                  <RunRow key={run.id} run={run} />
                ))}
                {isLoading ? <Skeleton className="m-4 h-10" /> : null}
              </div>
            )}
          </Card>

          <div className="space-y-4">
            <Card className="gap-3 rounded-xl p-5 shadow-[var(--shadow-xs)]">
              <h3 className="text-[15px] font-semibold tracking-tight">Corpus</h3>
              <dl className="divide-y divide-border">
                {Object.entries(data?.documents_by_status ?? {}).map(([status, count]) => (
                  <div key={status} className="flex h-9 items-center justify-between text-[13px]">
                    <dt className="text-muted-foreground">{humanize(status)}</dt>
                    <dd className="tabular-nums">{formatInt(count)}</dd>
                  </div>
                ))}
                <div className="flex h-9 items-center justify-between text-[13px]">
                  <dt className="text-muted-foreground">Indexed chunks</dt>
                  <dd className="tabular-nums">{formatInt(data?.chunks_total ?? 0)}</dd>
                </div>
              </dl>
            </Card>
            <Card className="gap-3 rounded-xl p-5 shadow-[var(--shadow-xs)]">
              <h3 className="text-[15px] font-semibold tracking-tight">Stage cache</h3>
              <p className="text-[13px] text-muted-foreground">
                Outputs keyed by stage, content hash and configuration version.
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-[22px] leading-7 font-semibold tabular-nums">{formatInt(data?.cache_entries ?? 0)}</p>
                  <p className="text-[12px] text-muted-foreground">Entries</p>
                </div>
                <div>
                  <p className="text-[22px] leading-7 font-semibold tabular-nums">{formatInt(data?.cache_hits ?? 0)}</p>
                  <p className="text-[12px] text-muted-foreground">Hits</p>
                </div>
              </div>
            </Card>
            {data && data.open_dead_letters > 0 ? (
              <Link
                href={latestLetter ? `/runs/${latestLetter.run_id}` : "/runs"}
                className="flex items-center gap-3 rounded-xl border border-destructive/20 bg-destructive/5 p-4 text-[13px] transition-colors hover:bg-destructive/10"
              >
                <AlertTriangle className="size-4 text-destructive" strokeWidth={1.75} aria-hidden />
                <span className="flex-1">
                  {data.open_dead_letters} document{data.open_dead_letters === 1 ? "" : "s"} in the dead-letter queue
                </span>
                <ChevronRight className="size-4 text-muted-foreground" aria-hidden />
              </Link>
            ) : null}
          </div>
        </section>
      </main>
    </>
  )
}
