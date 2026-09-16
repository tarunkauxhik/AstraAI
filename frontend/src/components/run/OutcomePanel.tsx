import type { ReactNode } from "react"
import { CheckCircle2 } from "lucide-react"

import type { Run } from "@/api/types"
import { MAX_EXECUTION_RETRIES, MAX_REVISIONS } from "@/api/types"
import { TONE_ACCENT, TONE_ICON, TONE_TEXT } from "@/components/run/tone"
import { formatDateTime, formatTestCounts } from "@/lib/format"
import { describeError, STAGE_LABELS, type Tone } from "@/lib/labels"
import { executionAttempt } from "@/lib/run-view"
import { cn } from "@/lib/utils"

function Frame({
  tone,
  eyebrow,
  title,
  icon,
  children,
}: {
  tone: Tone
  eyebrow: string
  title: string
  icon?: ReactNode
  children: ReactNode
}) {
  const Icon = TONE_ICON[tone]
  return (
    <section
      aria-labelledby="outcome-heading"
      className={cn("rounded-lg border border-l-2 bg-card p-4", TONE_ACCENT[tone])}
    >
      <div className="flex items-start gap-3">
        {icon ?? <Icon className={cn("mt-0.5 size-5 shrink-0", TONE_TEXT[tone])} aria-hidden="true" />}
        <div className="min-w-0 flex-1 space-y-2">
          <div>
            <p className="label-caps">{eyebrow}</p>
            <h2 id="outcome-heading" className="mt-1 font-semibold">
              {title}
            </h2>
          </div>
          {children}
        </div>
      </div>
    </section>
  )
}

function Facts({ children }: { children: ReactNode }) {
  return <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 border-t pt-2 text-xs">{children}</dl>
}

/** Terminal outcome, straight from status and error.code. */
export function OutcomePanel({ run }: { run: Run }) {
  const result = run.execution_result
  const counts = result ? formatTestCounts(result.tests_passed, result.tests_failed) : null
  const attempts = executionAttempt(run)

  if (run.status === "completed") {
    return (
      <Frame
        tone="success"
        eyebrow="Outcome"
        title="Completed"
        icon={<CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" aria-hidden="true" />}
      >
        <p className="text-sm text-muted-foreground">
          You approved the verified solution. It is the accepted result of this run.
        </p>
        <Facts>
          {counts && (
            <>
              <dt className="text-muted-foreground">Tests</dt>
              <dd>{counts}</dd>
            </>
          )}
          <dt className="text-muted-foreground">Attempts</dt>
          <dd>
            {attempts} · {run.revision_count}/{MAX_REVISIONS} revisions ·{" "}
            {run.execution_retry_count}/{MAX_EXECUTION_RETRIES} retries
          </dd>
          <dt className="text-muted-foreground">Completed</dt>
          <dd>{formatDateTime(run.updated_at)}</dd>
        </Facts>
      </Frame>
    )
  }

  const outcome = describeError(run.error)
  const { error } = run
  return (
    <Frame tone={outcome.tone} eyebrow="Outcome" title={outcome.title}>
      <p className="text-sm text-muted-foreground">{outcome.description}</p>
      {error && error.message !== outcome.description && outcome.category !== "decision" && (
        <p className="text-sm">{error.message}</p>
      )}
      {run.approval_status === "approved" && (
        <p className="text-sm text-muted-foreground">
          You approved this solution, but the run failed while finishing.
        </p>
      )}
      <Facts>
        {error && (
          <>
            <dt className="text-muted-foreground">Stopped during</dt>
            <dd>{STAGE_LABELS[error.stage]}</dd>
          </>
        )}
        {run.execution_result && (
          <>
            <dt className="text-muted-foreground">Attempts</dt>
            <dd>
              {attempts} · {run.revision_count}/{MAX_REVISIONS} revisions ·{" "}
              {run.execution_retry_count}/{MAX_EXECUTION_RETRIES} retries
            </dd>
          </>
        )}
        {error && (
          <>
            <dt className="text-muted-foreground">Code</dt>
            <dd className="font-mono">{error.code}</dd>
          </>
        )}
        <dt className="text-muted-foreground">Ended</dt>
        <dd>{formatDateTime(run.updated_at)}</dd>
      </Facts>
    </Frame>
  )
}
