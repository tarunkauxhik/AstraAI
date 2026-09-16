import type { ReactNode } from "react"
import { AlertTriangle, CheckCircle2, CircleSlash, XCircle, type LucideIcon } from "lucide-react"

import type { Run } from "@/api/types"
import { TONE_ACCENT, TONE_TEXT } from "@/components/run/tone"
import { formatDateTime, formatTestCounts } from "@/lib/format"
import { describeError, STAGE_LABELS, type Tone } from "@/lib/labels"
import { executionAttempt } from "@/lib/run-view"
import { cn } from "@/lib/utils"

const TONE_ICON: Record<Tone, LucideIcon> = {
  neutral: CircleSlash,
  info: CheckCircle2,
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: XCircle,
}

function Frame({
  tone,
  title,
  children,
}: {
  tone: Tone
  title: string
  children: ReactNode
}) {
  const Icon = TONE_ICON[tone]
  return (
    <section
      aria-labelledby="outcome-heading"
      className={cn("rounded-lg border border-l-2 bg-card p-4", TONE_ACCENT[tone])}
    >
      <div className="flex items-start gap-3">
        <Icon className={cn("mt-0.5 size-5 shrink-0", TONE_TEXT[tone])} aria-hidden="true" />
        <div className="min-w-0 space-y-1.5">
          <h2 id="outcome-heading" className="font-semibold">
            {title}
          </h2>
          {children}
        </div>
      </div>
    </section>
  )
}

/** Terminal outcome, straight from status and error.code. */
export function OutcomePanel({ run }: { run: Run }) {
  if (run.status === "completed") {
    const result = run.execution_result
    const counts = result ? formatTestCounts(result.tests_passed, result.tests_failed) : null
    return (
      <Frame tone="success" title="Approved and complete">
        <p className="text-sm text-muted-foreground">
          You approved the verified solution. It passed{counts ? ` (${counts})` : ""} after{" "}
          {executionAttempt(run) === 1 ? "one attempt" : `${executionAttempt(run)} attempts`}.
        </p>
        {run.critic_result && <p className="text-sm">{run.critic_result.reason}</p>}
      </Frame>
    )
  }

  const presentation = describeError(run.error)
  const { error } = run
  return (
    <Frame tone={presentation.tone} title={presentation.title}>
      <p className="text-sm text-muted-foreground">{presentation.description}</p>
      {error && error.message !== presentation.description && (
        <p className="text-sm">{error.message}</p>
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 pt-1 text-xs">
        {error && (
          <>
            <dt className="text-muted-foreground">Stopped during</dt>
            <dd>{STAGE_LABELS[error.stage]}</dd>
            <dt className="text-muted-foreground">Code</dt>
            <dd className="font-mono">{error.code}</dd>
          </>
        )}
        <dt className="text-muted-foreground">Ended</dt>
        <dd>{formatDateTime(run.updated_at)}</dd>
      </dl>
      {run.approval_status === "approved" && (
        <p className="text-xs text-muted-foreground">
          You approved this solution, but the run failed while finishing.
        </p>
      )}
    </Frame>
  )
}
