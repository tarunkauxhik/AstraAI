import { ChevronRight, History } from "lucide-react"

import type { CriticResult, Run } from "@/api/types"
import { ActivityDot } from "@/components/run/ActivityDot"
import { Panel } from "@/components/run/Panel"
import { TONE_BADGE, TONE_ICON } from "@/components/run/tone"
import { Badge } from "@/components/ui/badge"
import { ACTION_LABELS, VERDICT_MEANING, VERDICTS } from "@/lib/labels"
import { criticFreshness, evidenceAttempt, executionAttempt } from "@/lib/run-view"
import { cn } from "@/lib/utils"

/** Why a recommended action wasn't carried out, when the run's own outcome explains it. */
function actionNote(run: Run, critic: CriticResult): string | null {
  const code = run.error?.code
  if (code === "revision_budget_exhausted" && critic.recommended_action.startsWith("revise_")) {
    return "Not carried out: the revision budget was used up."
  }
  if (code === "sandbox_unavailable" && critic.recommended_action === "retry_execution") {
    return "Not carried out: the retry budget was used up."
  }
  return null
}

function ReviewBody({
  critic,
  historical,
  note,
}: {
  critic: CriticResult
  historical: boolean
  note: string | null
}) {
  const verdict = VERDICTS[critic.verdict]
  const tone = historical ? "neutral" : verdict.tone
  const Icon = TONE_ICON[tone]

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Badge variant="outline" className={cn("h-6 gap-1.5 rounded-md px-2", TONE_BADGE[tone])}>
          <Icon aria-hidden="true" />
          {verdict.label}
        </Badge>
        <p className="text-xs text-muted-foreground">{VERDICT_MEANING[critic.verdict]}</p>
      </div>

      <p className="text-sm leading-relaxed">{critic.reason}</p>

      {critic.code_issue && (
        <section className="rounded-md border-l-2 border-l-destructive/50 bg-muted/50 px-3 py-2">
          <h3 className="label-caps mb-1">Code issue</h3>
          <p className="text-sm">{critic.code_issue}</p>
        </section>
      )}
      {critic.test_issue && (
        <section className="rounded-md border-l-2 border-l-warning/50 bg-muted/50 px-3 py-2">
          <h3 className="label-caps mb-1">Test issue</h3>
          <p className="text-sm">{critic.test_issue}</p>
        </section>
      )}

      {!historical && (
        <p className="text-xs text-muted-foreground">
          Recommended: <span className="text-foreground">{ACTION_LABELS[critic.recommended_action]}</span>
          {note && <span className="block">{note}</span>}
        </p>
      )}
    </div>
  )
}

export function CriticPanel({ run }: { run: Run }) {
  const critic = run.critic_result
  const freshness = criticFreshness(run)
  const attempt = executionAttempt(run)
  const reviewing = run.stage === "reviewing" && run.status === "running"

  if (critic === null || freshness === null) {
    return (
      <Panel title="Review">
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          {reviewing && <ActivityDot />}
          {reviewing ? `Reviewing attempt ${attempt} against the requirements…` : "No review yet."}
        </p>
      </Panel>
    )
  }

  if (freshness === "current") {
    return (
      <Panel
        title="Review"
        action={<span className="text-xs text-muted-foreground">Attempt {evidenceAttempt(run, freshness)}</span>}
      >
        <ReviewBody critic={critic} historical={false} note={actionNote(run, critic)} />
      </Panel>
    )
  }

  const previous = evidenceAttempt(run, freshness)
  const running = run.status === "running"
  return (
    <Panel title="Review" action={<span className="text-xs text-muted-foreground">Attempt {attempt}</span>}>
      <p className="flex items-center gap-2 text-sm">
        {reviewing && <ActivityDot />}
        {reviewing
          ? `Reviewing attempt ${attempt} against the requirements…`
          : running
            ? `Attempt ${attempt} hasn't been reviewed yet.`
            : `Attempt ${attempt} was never reviewed.`}
      </p>
      <details className="group rounded-md border">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-2 text-xs text-muted-foreground select-none [&::-webkit-details-marker]:hidden">
          <ChevronRight
            className="size-3.5 transition-transform duration-150 group-open:rotate-90"
            aria-hidden="true"
          />
          <History className="size-3.5" aria-hidden="true" />
          Previous attempt ({previous}) · not the current verdict
        </summary>
        <div className="border-t p-3 opacity-80">
          <ReviewBody critic={critic} historical note={null} />
        </div>
      </details>
    </Panel>
  )
}
