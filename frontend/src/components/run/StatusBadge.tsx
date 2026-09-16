import { CheckCircle2, Clock, ShieldCheck } from "lucide-react"

import type { Run } from "@/api/types"
import { ActivityDot } from "@/components/run/ActivityDot"
import { TONE_BADGE, TONE_ICON } from "@/components/run/tone"
import { Badge } from "@/components/ui/badge"
import { describeError, STAGE_ACTIVITY } from "@/lib/labels"
import { runPhase } from "@/lib/run-view"
import { cn } from "@/lib/utils"

/** The run's state in the header: one short label with an icon or activity dot. */
export function StatusBadge({ run, className }: { run: Run; className?: string }) {
  const phase = runPhase(run)
  const classes = cn("h-6 max-w-full gap-1.5 rounded-md px-2", className)

  switch (phase) {
    case "working":
    case "resuming":
      return (
        <Badge variant="outline" className={cn(classes, TONE_BADGE.info)}>
          <ActivityDot className="size-1.5 [&>span]:size-1.5" />
          <span className="truncate">{STAGE_ACTIVITY[run.stage]}</span>
        </Badge>
      )
    case "queued":
      return (
        <Badge variant="outline" className={cn(classes, TONE_BADGE.neutral)}>
          <Clock aria-hidden="true" />
          Queued
        </Badge>
      )
    case "awaiting_approval":
      return (
        <Badge variant="outline" className={cn(classes, "border-brand/40 bg-brand/10 text-brand")}>
          <ShieldCheck aria-hidden="true" />
          Awaiting approval
        </Badge>
      )
    case "completed":
      return (
        <Badge variant="outline" className={cn(classes, TONE_BADGE.success)}>
          <CheckCircle2 aria-hidden="true" />
          Completed
        </Badge>
      )
    case "failed": {
      const outcome = describeError(run.error)
      const Icon = TONE_ICON[outcome.tone]
      return (
        <Badge variant="outline" className={cn(classes, TONE_BADGE[outcome.tone])}>
          <Icon aria-hidden="true" />
          <span className="truncate">{outcome.title}</span>
        </Badge>
      )
    }
  }
}
