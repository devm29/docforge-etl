import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

type Tone = "neutral" | "info" | "success" | "warning" | "danger"

const TONES: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground",
  info: "bg-primary/12 text-primary",
  success: "bg-success/15 text-success-foreground",
  warning: "bg-warning/15 text-warning-foreground",
  danger: "bg-destructive/12 text-destructive",
}

const DOTS: Record<Tone, string> = {
  neutral: "bg-muted-foreground/60",
  info: "bg-primary",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-destructive",
}

const STATUS_TONES: Record<string, Tone> = {
  succeeded: "success",
  ready: "success",
  valid: "success",
  approved: "success",
  edited: "success",
  accepted: "success",
  cached: "info",
  running: "info",
  scanning: "info",
  queued: "neutral",
  finalizing: "info",
  processing: "info",
  partial: "warning",
  needs_review: "warning",
  pending: "warning",
  low_confidence: "warning",
  deduplicated: "neutral",
  skipped: "neutral",
  superseded: "neutral",
  removed: "neutral",
  failed: "danger",
  invalid: "danger",
  validation_failed: "danger",
  open: "danger",
  replayed: "neutral",
  resolved: "success",
}

const LABELS: Record<string, string> = {
  needs_review: "Needs review",
  low_confidence: "Low confidence",
  validation_failed: "Fails validation",
  succeeded: "Succeeded",
  deduplicated: "Same content",
}

export function toneFor(status: string): Tone {
  return STATUS_TONES[status] ?? "neutral"
}

export function StatusBadge({ status, children, className }: { status: string; children?: ReactNode; className?: string }) {
  const tone = toneFor(status)
  const label = children ?? LABELS[status] ?? status.charAt(0).toUpperCase() + status.slice(1).replace(/_/g, " ")
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center gap-1.5 rounded-full px-2 text-[11px] font-medium whitespace-nowrap",
        TONES[tone],
        className
      )}
    >
      <span className={cn("size-1.5 rounded-full", DOTS[tone])} aria-hidden />
      {label}
    </span>
  )
}

export function ConfidenceMeter({ value, threshold = 0.8 }: { value: number; threshold?: number }) {
  const tone: Tone = value >= threshold ? "success" : value >= 0.5 ? "warning" : "danger"
  return (
    <span className="inline-flex items-center gap-2" title={`Confidence ${Math.round(value * 100)}%`}>
      <span className="relative h-1.5 w-12 overflow-hidden rounded-full bg-muted" aria-hidden>
        <span className={cn("absolute inset-y-0 left-0 rounded-full", DOTS[tone])} style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      <span className="w-8 text-right text-[12px] text-muted-foreground tabular-nums">{Math.round(value * 100)}%</span>
    </span>
  )
}
