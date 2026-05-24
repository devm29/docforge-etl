"use client"

import Link from "next/link"

import { StatusBadge } from "@/components/status"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import type { StageRun, Timeline } from "@/lib/api/schemas"
import { formatDuration, formatInt, formatUsd, humanize } from "@/lib/format"
import { cn } from "@/lib/utils"

const STATUS_FILL: Record<StageRun["status"], string> = {
  succeeded: "bg-chart-1",
  cached: "bg-chart-2",
  failed: "bg-destructive",
  skipped: "bg-muted-foreground/25",
}

const LEGEND: { status: StageRun["status"]; label: string }[] = [
  { status: "succeeded", label: "Computed" },
  { status: "cached", label: "Cache hit" },
  { status: "failed", label: "Failed" },
  { status: "skipped", label: "Skipped" },
]

export function computeWindow(timeline: Timeline): { start: number; span: number } {
  const stages = timeline.documents.flatMap((doc) => doc.stages)
  if (stages.length === 0) return { start: 0, span: 1 }
  const start = Math.min(...stages.map((s) => Date.parse(s.started_at)))
  const end = Math.max(...stages.map((s) => Date.parse(s.finished_at ?? s.started_at) || Date.parse(s.started_at)))
  return { start, span: Math.max(end - start, 1) }
}

function Segment({ stage, start, span }: { stage: StageRun; start: number; span: number }) {
  const begin = Date.parse(stage.started_at)
  const finish = stage.finished_at ? Date.parse(stage.finished_at) : begin
  const left = ((begin - start) / span) * 100
  const width = Math.max(((finish - begin) / span) * 100, 0.6)
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          aria-label={`${humanize(stage.stage)}: ${stage.status}`}
          className={cn(
            "absolute top-1/2 h-3.5 -translate-y-1/2 rounded-[3px] ring-1 ring-background outline-none focus-visible:ring-4 focus-visible:ring-ring",
            STATUS_FILL[stage.status]
          )}
          style={{ left: `${Math.min(left, 99.4)}%`, width: `${width}%` }}
        />
      </TooltipTrigger>
      <TooltipContent className="text-[12px]">
        <p className="font-semibold">
          {humanize(stage.stage)} · {stage.status === "cached" ? "cache hit" : stage.status}
        </p>
        <p className="tabular-nums">
          {formatDuration(stage.duration_ms)} · {formatInt(stage.items_in)} → {formatInt(stage.items_out)} items
          {stage.attempts > 1 ? ` · ${stage.attempts} attempts` : ""}
        </p>
        {stage.input_tokens > 0 ? (
          <p className="tabular-nums">
            {formatInt(stage.input_tokens + stage.output_tokens)} tokens · {formatUsd(stage.cost_usd)}
          </p>
        ) : null}
        {stage.cost_saved_usd > 0 ? <p className="tabular-nums">Saved {formatUsd(stage.cost_saved_usd)}</p> : null}
        {stage.error ? <p className="max-w-64 text-destructive">{stage.error}</p> : null}
      </TooltipContent>
    </Tooltip>
  )
}

export function RunTimeline({ timeline }: { timeline: Timeline }) {
  const { start, span } = computeWindow(timeline)
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-4 text-[12px] text-muted-foreground">
        {LEGEND.map((item) => (
          <span key={item.status} className="flex items-center gap-1.5">
            <span className={cn("size-2.5 rounded-[3px]", STATUS_FILL[item.status])} aria-hidden />
            {item.label}
          </span>
        ))}
        <span className="ml-auto tabular-nums">Window {formatDuration(span)}</span>
      </div>
      <ul className="divide-y divide-border">
        {timeline.documents.map((doc) => (
          <li key={doc.version_id} className="grid h-10 grid-cols-[minmax(0,220px)_minmax(0,1fr)_auto] items-center gap-4">
            <Link
              href={`/documents/${doc.document_id}`}
              className="truncate text-[13px] hover:text-primary hover:underline"
              title={doc.uri}
            >
              {doc.filename}
            </Link>
            <div className="relative h-full">
              <span className="absolute inset-x-0 top-1/2 h-px bg-border" aria-hidden />
              {doc.stages.map((stage) => (
                <Segment key={stage.id} stage={stage} start={start} span={span} />
              ))}
            </div>
            <StatusBadge status={doc.version_status} className="w-[104px] justify-center" />
          </li>
        ))}
      </ul>
    </div>
  )
}
