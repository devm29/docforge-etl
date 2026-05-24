import { ChevronRight } from "lucide-react"
import { Fragment } from "react"

import type { StageSummary } from "@/lib/api/schemas"
import { formatDuration, formatInt, formatUsd, humanize } from "@/lib/format"

const DESCRIPTIONS: Record<string, string> = {
  detect: "Fetch, hash, sniff format",
  parse: "Pages, blocks, boxes",
  chunk: "Structure-aware chunks",
  embed: "Vectors, reused by hash",
  extract: "Schema-locked fields",
  load: "pgvector, entities, reviews",
}

export function StageStrip({ stages }: { stages: StageSummary[] }) {
  return (
    <div className="flex items-stretch gap-1 overflow-x-auto pb-1" role="list" aria-label="Pipeline stages">
      {stages.map((stage, index) => (
        <Fragment key={stage.stage}>
          {index > 0 ? (
            <ChevronRight className="size-4 shrink-0 self-center text-muted-foreground/60" aria-hidden />
          ) : null}
          <div role="listitem" className="min-w-[150px] flex-1 rounded-xl bg-card p-4 ring-1 ring-border/60">
            <p className="text-[15px] font-semibold tracking-tight">{humanize(stage.stage)}</p>
            <p className="text-[12px] text-muted-foreground">{DESCRIPTIONS[stage.stage] ?? ""}</p>
            <dl className="mt-3 space-y-1 text-[12px]">
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Ran</dt>
                <dd className="tabular-nums">{stage.executed}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Cache hits</dt>
                <dd className="text-chart-2 tabular-nums">{stage.cached}</dd>
              </div>
              {stage.failed > 0 ? (
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Failed</dt>
                  <dd className="text-destructive tabular-nums">{stage.failed}</dd>
                </div>
              ) : null}
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Items</dt>
                <dd className="tabular-nums">
                  {formatInt(stage.items_in)} → {formatInt(stage.items_out)}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Time</dt>
                <dd className="tabular-nums">{formatDuration(stage.duration_ms)}</dd>
              </div>
              {stage.cost_usd > 0 || stage.cost_saved_usd > 0 ? (
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">{stage.cost_usd > 0 ? "Cost" : "Saved"}</dt>
                  <dd className={stage.cost_usd > 0 ? "tabular-nums" : "text-success-foreground tabular-nums"}>
                    {formatUsd(stage.cost_usd > 0 ? stage.cost_usd : stage.cost_saved_usd)}
                  </dd>
                </div>
              ) : null}
            </dl>
          </div>
        </Fragment>
      ))}
    </div>
  )
}
