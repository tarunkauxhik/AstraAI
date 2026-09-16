import { Clock, Loader2 } from "lucide-react"

import type { Run } from "@/api/types"
import { ApprovalPanel } from "@/components/run/ApprovalPanel"
import { OutcomePanel } from "@/components/run/OutcomePanel"
import { STAGE_LABELS } from "@/lib/labels"
import { runPhase, verifyActivity } from "@/lib/run-view"

/** The one "what is happening now" panel: working, waiting for you, or the outcome. */
export function RunStatusPanel({ run }: { run: Run }) {
  const phase = runPhase(run)

  if (phase === "awaiting_approval") return <ApprovalPanel run={run} />
  if (phase === "completed" || phase === "failed") return <OutcomePanel run={run} />

  const queued = phase === "queued"
  const title = queued
    ? "Queued"
    : phase === "resuming"
      ? "Approved — finishing the run"
      : STAGE_LABELS[run.stage]
  const detail = queued
    ? "Waiting for a free worker. Runs execute one at a time."
    : phase === "resuming"
      ? "Your approval was recorded. AstraAi is completing the run."
      : (verifyActivity(run) ?? "AstraAi is working on this step.")

  return (
    <section className="rounded-lg border bg-card p-4" aria-labelledby="status-heading">
      <div className="flex items-start gap-3">
        {queued ? (
          <Clock className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
        ) : (
          <Loader2 className="mt-0.5 size-5 shrink-0 animate-spin text-info" aria-hidden="true" />
        )}
        <div className="min-w-0 space-y-1">
          <h2 id="status-heading" className="font-semibold">
            {title}
          </h2>
          <p className="text-sm text-muted-foreground">{detail}</p>
        </div>
      </div>
    </section>
  )
}
