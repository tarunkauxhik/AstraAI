import { History } from "lucide-react"

import type { Run } from "@/api/types"
import { Panel } from "@/components/run/Panel"
import { TONE_BADGE } from "@/components/run/tone"
import { Badge } from "@/components/ui/badge"
import { ACTION_LABELS, VERDICTS } from "@/lib/labels"
import { criticFreshness, executionAttempt } from "@/lib/run-view"
import { cn } from "@/lib/utils"

export function CriticPanel({ run }: { run: Run }) {
  const critic = run.critic_result
  const freshness = criticFreshness(run)

  if (critic === null || freshness === null) {
    return (
      <Panel title="Review">
        <p className="text-sm text-muted-foreground">
          {run.stage === "reviewing"
            ? "Reviewing the execution against the requirements…"
            : "No review yet."}
        </p>
      </Panel>
    )
  }

  const stale = freshness === "stale"
  const verdict = VERDICTS[critic.verdict]
  const current = executionAttempt(run)

  return (
    <Panel title="Review">
      {stale && (
        <p className="flex items-start gap-2 rounded-md bg-muted px-2.5 py-2 text-xs text-muted-foreground">
          <History className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          Review of the previous attempt ({current - 1}). Attempt {current}{" "}
          {run.status === "running" ? "hasn't been reviewed yet" : "was never reviewed"}, so
          this is not the current verdict.
        </p>
      )}
      <div className={cn("space-y-3", stale && "opacity-70")}>
        <div className="flex flex-wrap items-center gap-2">
          <Badge
            variant="outline"
            className={cn("h-6 rounded-md px-2", TONE_BADGE[stale ? "neutral" : verdict.tone])}
          >
            {verdict.label}
          </Badge>
          <span className="text-xs text-muted-foreground">
            Next step: {ACTION_LABELS[critic.recommended_action]}
          </span>
        </div>
        <p className="text-sm leading-relaxed">{critic.reason}</p>
        {critic.code_issue && (
          <div>
            <h3 className="label-caps mb-1">Code issue</h3>
            <p className="text-sm text-muted-foreground">{critic.code_issue}</p>
          </div>
        )}
        {critic.test_issue && (
          <div>
            <h3 className="label-caps mb-1">Test issue</h3>
            <p className="text-sm text-muted-foreground">{critic.test_issue}</p>
          </div>
        )}
      </div>
    </Panel>
  )
}
