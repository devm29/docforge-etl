"use client"

import { Loader2, Play } from "lucide-react"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { useStartRun } from "@/lib/api/hooks"

export function RunPipelineButton() {
  const router = useRouter()
  const start = useStartRun()
  const [open, setOpen] = useState(false)
  const [force, setForce] = useState(false)
  const [bypassCache, setBypassCache] = useState(false)

  async function submit() {
    try {
      const run = await start.mutateAsync({ force, bypass_cache: bypassCache })
      setOpen(false)
      toast.success("Run started", {
        description: "Scanning the source for changed documents.",
        action: { label: "View", onClick: () => router.push(`/runs/${run.id}`) },
      })
    } catch (error) {
      toast.error("Could not start the run", {
        description: error instanceof Error ? error.message : "Check that the API is running.",
      })
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="h-8 rounded-lg px-3.5 text-[13px] active:scale-[0.98]">
          <Play className="size-3.5" strokeWidth={2} />
          Run pipeline
        </Button>
      </DialogTrigger>
      <DialogContent className="rounded-2xl sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-[17px]">Run the pipeline</DialogTitle>
          <DialogDescription className="text-[13px]">
            Only documents whose fingerprint changed are processed. Unchanged documents cost nothing.
          </DialogDescription>
        </DialogHeader>
        <div className="divide-y divide-border rounded-xl bg-secondary/60">
          <div className="flex min-h-14 items-center justify-between gap-4 px-4 py-3">
            <Label htmlFor="force" className="flex flex-col items-start gap-0.5">
              <span className="text-[13px] font-medium">Reprocess every document</span>
              <span className="text-[12px] font-normal text-muted-foreground">
                Stage outputs are still reused when inputs are identical.
              </span>
            </Label>
            <Switch id="force" checked={force} onCheckedChange={setForce} />
          </div>
          <div className="flex min-h-14 items-center justify-between gap-4 px-4 py-3">
            <Label htmlFor="bypass" className="flex flex-col items-start gap-0.5">
              <span className="text-[13px] font-medium">Recompute every stage</span>
              <span className="text-[12px] font-normal text-muted-foreground">
                Ignores the stage cache. Extraction is billed again.
              </span>
            </Label>
            <Switch id="bypass" checked={bypassCache} onCheckedChange={setBypassCache} />
          </div>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="secondary" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} disabled={start.isPending}>
            {start.isPending ? <Loader2 className="size-3.5 animate-spin" /> : null}
            Start run
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
