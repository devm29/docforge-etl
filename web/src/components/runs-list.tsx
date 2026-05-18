import { ChevronRight } from "lucide-react"
import Link from "next/link"

import { StatusBadge } from "@/components/status"
import type { Run } from "@/lib/api/schemas"
import { formatDuration, formatRelative, formatUsd, runDuration } from "@/lib/format"

const TRIGGERS: Record<string, string> = {
  api: "Manual run",
  schedule: "Scheduled scan",
  replay: "Dead-letter replay",
  cli: "CLI run",
}

export function runTitle(run: Run): string {
  const base = TRIGGERS[run.trigger] ?? run.trigger
  if (run.force) return `${base}, full reprocess`
  return base
}

export function RunRow({ run }: { run: Run }) {
  const duration = runDuration(run.started_at, run.finished_at)
  return (
    <Link
      href={`/runs/${run.id}`}
      className="flex min-h-14 items-center gap-4 px-4 py-2.5 transition-colors duration-150 hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none"
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[14px] font-medium">{runTitle(run)}</span>
          <StatusBadge status={run.status} />
        </div>
        <p className="mt-0.5 truncate text-[12px] text-muted-foreground tabular-nums">
          {run.docs_changed} changed · {run.docs_unchanged} unchanged
          {run.docs_failed ? ` · ${run.docs_failed} failed` : ""}
          {duration !== null ? ` · ${formatDuration(duration)}` : ""}
        </p>
      </div>
      <div className="hidden text-right sm:block">
        <p className="text-[13px] tabular-nums">{formatUsd(run.cost_usd)}</p>
        <p className="text-[12px] text-success-foreground tabular-nums">
          {run.cost_saved_usd > 0 ? `${formatUsd(run.cost_saved_usd)} saved` : " "}
        </p>
      </div>
      <span className="w-20 text-right text-[12px] text-muted-foreground">{formatRelative(run.created_at)}</span>
      <ChevronRight className="size-4 text-muted-foreground/70" strokeWidth={1.75} aria-hidden />
    </Link>
  )
}
