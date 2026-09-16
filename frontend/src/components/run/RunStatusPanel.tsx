import { Clock } from "lucide-react"

import type { Run } from "@/api/types"
import { ActivityDot } from "@/components/run/ActivityDot"
import { ApprovalPanel } from "@/components/run/ApprovalPanel"
import { OutcomePanel } from "@/components/run/OutcomePanel"
import { STAGE_ACTIVITY, STAGE_DESCRIPTION } from "@/lib/labels"
import { executionAttempt, isRetryingExecution, runPhase } from "@/lib/run-view"

const VERIFY_STAGES = new Set(["executing", "reviewing", "revising_code", "revising_tests"])

/** The one "what is happening now" panel: working, waiting for you, or the outcome. */
export function RunStatusPanel({ run }: { run: Run }) {
  const phase = runPhase(run)

  if (phase === "awaiting_approval") return <ApprovalPanel run={run} />
  if (phase === "completed" || phase === "failed") return <OutcomePanel run={run} />

  const queued = phase === "queued"
  const inVerify = VERIFY_STAGES.has(run.stage)
  const description = isRetryingExecution(run)
    ? "The sandbox couldn't run the previous attempt, so the same code is being run again."
    : STAGE_DESCRIPTION[run.stage]

  return (
    <section
      aria-labelledby="status-heading"
      className="rounded-lg border border-l-2 border-l-info bg-card p-4 data-[queued=true]:border-l-muted-foreground/40"
      data-queued={queued}
    >
      <p className="label-caps mb-2 flex items-center gap-2">
        {queued ? (
          <Clock className="size-3.5" aria-hidden="true" />
        ) : (
          <ActivityDot />
        )}
        {queued ? "Waiting" : "AstraAi is working"}
      </p>
      <h2 id="status-heading" className="text-base font-semibold">
        {STAGE_ACTIVITY[run.stage]}
        {inVerify && (
          <span className="font-normal text-muted-foreground"> · attempt {executionAttempt(run)}</span>
        )}
      </h2>
      {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      {!queued && (
        <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t pt-3 text-xs">
          <div className="flex gap-1.5">
            <dt className="text-muted-foreground">Attempt</dt>
            <dd className="font-mono">{executionAttempt(run)}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt className="text-muted-foreground">Revisions</dt>
            <dd className="font-mono">{run.revision_count}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt className="text-muted-foreground">Retries</dt>
            <dd className="font-mono">{run.execution_retry_count}</dd>
          </div>
        </dl>
      )}
    </section>
  )
}
