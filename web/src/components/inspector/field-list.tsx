"use client"

import { AlertCircle, Link2, Link2Off, Wrench } from "lucide-react"

import { ConfidenceMeter, StatusBadge } from "@/components/status"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import type { ExtractedField, JsonValue } from "@/lib/api/schemas"
import { displayValue, humanize } from "@/lib/format"
import { cn } from "@/lib/utils"

const MATCH_LABEL = {
  exact: "Quote found word for word on the page",
  fuzzy: "Quote found with small differences",
  block: "Traced to a block, not to exact words",
  none: "Could not be traced to the document",
} as const

function LineItems({ value }: { value: JsonValue }) {
  if (!Array.isArray(value) || value.length === 0) return null
  return (
    <div className="mt-2 overflow-hidden rounded-lg border border-border/80">
      <table className="w-full text-[12px]">
        <thead className="bg-secondary/80 text-muted-foreground">
          <tr>
            <th className="px-2 py-1 text-left font-medium">Description</th>
            <th className="px-2 py-1 text-right font-medium">Qty</th>
            <th className="px-2 py-1 text-right font-medium">Amount</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {value.map((item, index) => {
            const row = item !== null && typeof item === "object" && !Array.isArray(item) ? item : {}
            return (
              <tr key={index}>
                <td className="max-w-0 truncate px-2 py-1">{String(row.description ?? "")}</td>
                <td className="px-2 py-1 text-right tabular-nums">{String(row.quantity ?? "")}</td>
                <td className="px-2 py-1 text-right tabular-nums">{String(row.amount ?? "")}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function FieldList({
  fields,
  activeId,
  onSelect,
  threshold = 0.8,
}: {
  fields: ExtractedField[]
  activeId: string | null
  onSelect: (field: ExtractedField) => void
  threshold?: number
}) {
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-xl bg-card ring-1 ring-border/60" aria-label="Extracted fields">
      {fields.map((field) => {
        const active = field.id === activeId
        const MatchIcon = field.match === "none" ? Link2Off : Link2
        return (
          <li key={field.id}>
            <button
              type="button"
              aria-pressed={active}
              onClick={() => onSelect(field)}
              className={cn(
                "w-full px-4 py-3 text-left transition-colors duration-150 outline-none focus-visible:ring-4 focus-visible:ring-ring focus-visible:ring-inset",
                active ? "bg-primary/10" : "hover:bg-accent/50"
              )}
            >
              <div className="flex items-center gap-2">
                <span className="text-[12px] font-medium text-muted-foreground">{humanize(field.path)}</span>
                {field.repaired ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Wrench className="size-3 text-muted-foreground" strokeWidth={1.75} aria-label="Repaired" />
                    </TooltipTrigger>
                    <TooltipContent>Normalized by the repair loop after a validation error</TooltipContent>
                  </Tooltip>
                ) : null}
                <span className="ml-auto flex items-center gap-2">
                  {field.status === "needs_review" ? <StatusBadge status="needs_review" /> : null}
                  {field.status === "approved" || field.status === "edited" ? (
                    <StatusBadge status={field.status}>{field.status === "edited" ? "Corrected" : "Approved"}</StatusBadge>
                  ) : null}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <MatchIcon
                        className={cn("size-3.5", field.match === "none" ? "text-muted-foreground/60" : "text-primary")}
                        strokeWidth={1.75}
                        aria-label={MATCH_LABEL[field.match]}
                      />
                    </TooltipTrigger>
                    <TooltipContent>{MATCH_LABEL[field.match]}</TooltipContent>
                  </Tooltip>
                </span>
              </div>
              <div className="mt-1 flex items-start justify-between gap-3">
                <span
                  className={cn(
                    "min-w-0 text-[14px] break-words",
                    field.value === null ? "text-muted-foreground italic" : "font-medium"
                  )}
                >
                  {displayValue(field.value)}
                </span>
                <ConfidenceMeter value={field.confidence} threshold={threshold} />
              </div>
              {field.path === "line_items" && active ? <LineItems value={field.value} /> : null}
              {field.issues.map((issue) => (
                <p key={issue} className="mt-1.5 flex items-start gap-1.5 text-[12px] text-destructive">
                  <AlertCircle className="mt-0.5 size-3 shrink-0" aria-hidden />
                  {issue}
                </p>
              ))}
              {active && field.evidence ? (
                <p className="mt-2 rounded-md bg-secondary px-2 py-1.5 font-mono text-[11px] leading-4 text-muted-foreground">
                  “{field.evidence}”{field.page ? ` · page ${field.page}` : ""}
                </p>
              ) : null}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
