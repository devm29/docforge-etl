import { AlertTriangle, type LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { ApiError } from "@/lib/api/client"

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  role,
}: {
  icon: LucideIcon
  title: string
  description: string
  action?: ReactNode
  role?: "alert" | "status"
}) {
  return (
    <div role={role} className="flex flex-col items-center justify-center px-6 py-16 text-center">
      <Icon className="size-11 text-muted-foreground/60" strokeWidth={1.5} aria-hidden />
      <h3 className="mt-4 font-heading text-[19px] font-semibold">{title}</h3>
      <p className="mt-1 max-w-sm text-[13px] text-muted-foreground">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  )
}

export function describeLoadError(error: unknown): string {
  if (error instanceof ApiError && (error.code === "api_unreachable" || error.status === 502)) {
    return "The DocForge API is not reachable. Start the backend on port 8103, then refresh."
  }
  return error instanceof Error ? error.message : "The request failed. Try again in a moment."
}

/** Shown instead of an empty list when a query failed, so an outage never reads as "nothing here". */
export function LoadError({ what, error }: { what: string; error: unknown }) {
  return (
    <EmptyState role="alert" icon={AlertTriangle} title={`Couldn't load ${what}`} description={describeLoadError(error)} />
  )
}
