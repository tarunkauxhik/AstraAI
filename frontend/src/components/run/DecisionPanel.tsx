import { CheckCircle2, Clock } from "lucide-react"

import type { Run } from "@/api/types"
import { Disclosure } from "@/components/Disclosure"
import { ActivityDot } from "@/components/run/ActivityDot"
import { ApprovalPanel } from "@/components/run/ApprovalPanel"
import { TONE_ICON, TONE_TEXT } from "@/components/run/tone"
import { formatCount, formatDateTime, formatTestResult } from "@/lib/format"
import { describeError, STAGE_ACTIVITY } from "@/lib/labels"
import {
  criticFreshness,
  executionAttempt,
  executionFreshness,
  runPhase,
  workingNote,
} from "@/lib/run-view"
import { cn } from "@/lib/utils"

interface DecisionPanelProps {
  run: Run
  /** Opens verification details in the main content area. */
  onShowDetails: () => void
}

function DetailsLink({ onClick, children }: { onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-sm text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
    >
      {children}
    </button>
  )
}

function Working({ run, onShowDetails }: DecisionPanelProps) {
  const phase = runPhase(run)
  const note = workingNote(run)
  const hasPrevious = executionFreshness(run) === "stale" || criticFreshness(run) === "stale"

  if (phase === "queued") {
    return (
      <section aria-labelledby="status-heading" className="space-y-1">
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Clock className="size-4" aria-hidden="true" />
          Queued
        </p>
        <h2 id="status-heading" className="text-lg font-semibold">
          Waiting to start
        </h2>
        <p className="text-sm text-muted-foreground">AstraAi will begin as soon as a worker is free.</p>
      </section>
    )
  }

  return (
    <section aria-labelledby="status-heading" className="space-y-3">
      <div>
        <h2 id="status-heading" className="flex items-center gap-2 text-lg font-semibold">
          <ActivityDot />
          {phase === "resuming" ? "Approved" : "AstraAi is working"}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">{STAGE_ACTIVITY[run.stage]}…</p>
      </div>
      {note && <p className="text-sm">{note}</p>}
      {hasPrevious && <DetailsLink onClick={onShowDetails}>Previous attempt</DetailsLink>}
    </section>
  )
}

function Outcome({ run, onShowDetails }: DecisionPanelProps) {
  const hasEvidence = run.execution_result !== null || run.critic_result !== null

  if (run.status === "completed") {
    const result = run.execution_result
    const tests = result ? formatTestResult(result.tests_passed, result.tests_failed) : null
    const attempts = executionAttempt(run)
    return (
      <section aria-labelledby="outcome-heading" className="space-y-3">
        <h2 id="outcome-heading" className={cn("flex items-center gap-2 text-lg font-semibold", TONE_TEXT.success)}>
          <CheckCircle2 className="size-5" aria-hidden="true" />
          Completed
        </h2>
        <p className="text-sm text-muted-foreground">You approved this solution.</p>
        {(tests || attempts > 1) && (
          <p className="text-sm">
            {tests}
            {attempts > 1 && (
              <span className="text-muted-foreground">
                {tests ? " · " : ""}verified on attempt {attempts}
              </span>
            )}
          </p>
        )}
        {hasEvidence && <DetailsLink onClick={onShowDetails}>Verification details</DetailsLink>}
      </section>
    )
  }

  const outcome = describeError(run.error)
  const Icon = TONE_ICON[outcome.tone]
  const { error } = run
  const technical = outcome.category !== "decision" && error !== null

  return (
    <section aria-labelledby="outcome-heading" className="space-y-3">
      <h2
        id="outcome-heading"
        className={cn("flex items-center gap-2 text-lg font-semibold", outcome.tone !== "neutral" && TONE_TEXT[outcome.tone])}
      >
        <Icon className="size-5 shrink-0" aria-hidden="true" />
        {outcome.title}
      </h2>
      <p className="text-sm text-muted-foreground">{outcome.description}</p>
      {run.approval_status === "approved" && (
        <p className="text-sm text-muted-foreground">You had approved it, but the run couldn't finish.</p>
      )}
      <div className="space-y-1">
        {technical && (
          <Disclosure summary="Technical details">
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
              <dt className="text-muted-foreground">Stopped while</dt>
              <dd>{STAGE_ACTIVITY[error.stage].toLowerCase()}</dd>
              {(run.revision_count > 0 || run.execution_retry_count > 0) && (
                <>
                  <dt className="text-muted-foreground">Attempts</dt>
                  <dd>
                    {executionAttempt(run)}
                    {run.revision_count > 0 && ` · ${formatCount(run.revision_count, "repair")}`}
                    {run.execution_retry_count > 0 &&
                      ` · ${formatCount(run.execution_retry_count, "retry", "retries")}`}
                  </dd>
                </>
              )}
              <dt className="text-muted-foreground">Error code</dt>
              <dd className="font-mono text-xs leading-5">{error.code}</dd>
              {error.message && error.message !== outcome.description && (
                <>
                  <dt className="text-muted-foreground">Message</dt>
                  <dd>{error.message}</dd>
                </>
              )}
              <dt className="text-muted-foreground">Ended</dt>
              <dd>{formatDateTime(run.updated_at)}</dd>
            </dl>
          </Disclosure>
        )}
        {hasEvidence && <DetailsLink onClick={onShowDetails}>Verification details</DetailsLink>}
      </div>
    </section>
  )
}

/** The one place that says what is happening and what the user can do about it. */
export function DecisionPanel(props: DecisionPanelProps) {
  const phase = runPhase(props.run)
  return (
    <div
      className={cn(
        "rounded-lg border bg-card p-4",
        phase === "awaiting_approval" && "border-success/30",
      )}
    >
      {phase === "awaiting_approval" ? (
        <ApprovalPanel {...props} />
      ) : phase === "completed" || phase === "failed" ? (
        <Outcome {...props} />
      ) : (
        <Working {...props} />
      )}
    </div>
  )
}
