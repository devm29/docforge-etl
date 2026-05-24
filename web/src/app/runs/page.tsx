"use client"

import { Workflow } from "lucide-react"
import { useState } from "react"

import { EmptyState } from "@/components/empty-state"
import { PageTitle, Toolbar } from "@/components/page-header"
import { RunPipelineButton } from "@/components/run-pipeline-button"
import { RunRow } from "@/components/runs-list"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useRuns } from "@/lib/api/hooks"

const PAGE_SIZE = 25

export default function RunsPage() {
  const [offset, setOffset] = useState(0)
  const { data, isLoading } = useRuns(offset)

  return (
    <>
      <Toolbar title="Runs">
        <RunPipelineButton />
      </Toolbar>
      <main className="mx-auto w-full max-w-6xl space-y-6 px-6 py-8">
        <PageTitle
          title="Runs"
          subtitle="Each run scans the source, diffs fingerprints and processes only what changed."
        />
        <Card className="gap-0 overflow-hidden rounded-xl p-0 shadow-[var(--shadow-xs)]">
          {isLoading ? (
            <div className="space-y-3 p-4">
              {Array.from({ length: 5 }, (_, i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          ) : data && data.items.length > 0 ? (
            <div className="divide-y divide-border">
              {data.items.map((run) => (
                <RunRow key={run.id} run={run} />
              ))}
            </div>
          ) : (
            <EmptyState
              icon={Workflow}
              title="No runs yet"
              description="Start a run to scan the source folder and process its documents."
              action={<RunPipelineButton />}
            />
          )}
        </Card>
        {data && data.total > PAGE_SIZE ? (
          <div className="flex items-center justify-between text-[13px] text-muted-foreground">
            <span className="tabular-nums">
              {offset + 1}-{Math.min(offset + PAGE_SIZE, data.total)} of {data.total}
            </span>
            <div className="flex gap-2">
              <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(offset - PAGE_SIZE)}>
                Previous
              </Button>
              <Button
                variant="secondary"
                disabled={offset + PAGE_SIZE >= data.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}
      </main>
    </>
  )
}
