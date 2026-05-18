import Link from "next/link"

import { StatusBadge } from "@/components/status"
import type { Version } from "@/lib/api/schemas"
import { formatBytes, formatDateTime, shortHash } from "@/lib/format"
import { cn } from "@/lib/utils"

export function VersionList({
  documentId,
  versions,
  activeVersionId,
}: {
  documentId: string
  versions: Version[]
  activeVersionId: string | undefined
}) {
  return (
    <ol className="divide-y divide-border overflow-hidden rounded-xl bg-card ring-1 ring-border/60">
      {versions.map((version) => {
        const viewable = version.status === "succeeded"
        const content = (
          <div className={cn("flex items-center gap-3 px-4 py-3", viewable && "hover:bg-accent/50")}>
            <span className="w-8 text-[13px] font-semibold tabular-nums">v{version.version_no}</span>
            <div className="min-w-0 flex-1">
              <p className="truncate font-mono text-[11px] text-muted-foreground">{shortHash(version.content_hash)}</p>
              <p className="text-[12px] text-muted-foreground">
                {formatDateTime(version.created_at)} · {formatBytes(version.size_bytes)}
              </p>
            </div>
            <StatusBadge status={version.status} />
          </div>
        )
        return (
          <li key={version.id} className={cn(version.id === activeVersionId && "bg-primary/10")}>
            {viewable ? (
              <Link href={`/documents/${documentId}?version=${version.id}`} className="block outline-none focus-visible:bg-accent">
                {content}
              </Link>
            ) : (
              content
            )}
          </li>
        )
      })}
    </ol>
  )
}
