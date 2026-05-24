import type { ReactNode } from "react"

import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export function Kpi({
  label,
  value,
  footnote,
  tone,
}: {
  label: string
  value: ReactNode
  footnote?: ReactNode
  tone?: "success" | "warning" | undefined
}) {
  return (
    <Card className="gap-1 rounded-xl p-5 shadow-[var(--shadow-xs)]">
      <p className="text-[13px] text-muted-foreground">{label}</p>
      <p
        className={cn(
          "text-[28px] leading-[34px] font-semibold tracking-tight tabular-nums",
          tone === "success" && "text-success-foreground",
          tone === "warning" && "text-warning-foreground"
        )}
      >
        {value}
      </p>
      {footnote ? <p className="text-[12px] leading-4 text-muted-foreground">{footnote}</p> : null}
    </Card>
  )
}
