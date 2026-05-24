import { StatusBadge } from "@/components/status"
import type { Extraction } from "@/lib/api/schemas"
import { formatInt, formatUsd, humanize } from "@/lib/format"

export function ExtractionSummary({ extraction }: { extraction: Extraction }) {
  const repairs = extraction.attempt_log.filter((attempt) => attempt.errors.length > 0)
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <h3 className="text-[17px] font-semibold tracking-tight">{humanize(extraction.schema_name)}</h3>
        <StatusBadge status={extraction.status} />
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[12px]">
        <dt className="text-muted-foreground">Model</dt>
        <dd className="truncate text-right font-mono text-[11px]">{extraction.model}</dd>
        <dt className="text-muted-foreground">Attempts</dt>
        <dd className="text-right tabular-nums">
          {extraction.attempts}
          {extraction.repaired ? " (repaired)" : ""}
        </dd>
        <dt className="text-muted-foreground">Tokens</dt>
        <dd className="text-right tabular-nums">
          {formatInt(extraction.input_tokens)} in · {formatInt(extraction.output_tokens)} out
        </dd>
        <dt className="text-muted-foreground">Cost</dt>
        <dd className="text-right tabular-nums">
          {formatUsd(extraction.cost_usd)}
          {extraction.provider === "offline" ? " est." : ""}
        </dd>
        <dt className="text-muted-foreground">Schema version</dt>
        <dd className="text-right font-mono text-[11px]">{extraction.schema_version}</dd>
      </dl>
      {repairs.length > 0 ? (
        <details className="rounded-lg bg-secondary/70 px-3 py-2 text-[12px]">
          <summary className="cursor-pointer font-medium select-none">
            Repair loop: {repairs.length} failed attempt{repairs.length === 1 ? "" : "s"}
          </summary>
          <ol className="mt-2 space-y-2">
            {repairs.map((attempt) => (
              <li key={attempt.attempt}>
                <p className="font-medium">Attempt {attempt.attempt}</p>
                <ul className="mt-0.5 space-y-0.5 text-muted-foreground">
                  {attempt.errors.slice(0, 4).map((error) => (
                    <li key={error} className="break-words">
                      {error}
                    </li>
                  ))}
                  {attempt.errors.length > 4 ? <li>and {attempt.errors.length - 4} more</li> : null}
                </ul>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </div>
  )
}
