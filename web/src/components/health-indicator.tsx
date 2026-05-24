"use client"

import { cn } from "@/lib/utils"
import { useHealth } from "@/lib/api/hooks"

export function HealthIndicator() {
  const health = useHealth()
  const data = health.data
  const ok = data?.status === "ok"
  const label = health.isError ? "API unreachable" : ok ? "All systems normal" : data ? "Degraded" : "Connecting"

  return (
    <div className="rounded-lg px-2 py-2 text-[12px] leading-4 text-muted-foreground" aria-live="polite">
      <div className="flex items-center gap-2 text-foreground">
        <span
          className={cn(
            "size-2 rounded-full",
            ok ? "bg-success" : health.isError ? "bg-destructive" : "bg-warning"
          )}
          aria-hidden
        />
        <span className="text-[12px] font-medium">{label}</span>
      </div>
      {data ? (
        <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5">
          <dt>Extractor</dt>
          <dd className="truncate text-right font-mono text-[11px]">{data.model}</dd>
          <dt>Embeddings</dt>
          <dd className="truncate text-right font-mono text-[11px]" title={data.embedder}>
            {data.embedder.replace("fastembed:", "")}
          </dd>
        </dl>
      ) : null}
    </div>
  )
}
