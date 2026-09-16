import {
  CheckCircle2,
  Clock,
  Loader2,
  ShieldCheck,
  XCircle,
  type LucideIcon,
} from "lucide-react"

import type { Run } from "@/api/types"
import { Badge } from "@/components/ui/badge"
import { TONE_BADGE } from "@/components/run/tone"
import { describeError, STATUS_LABELS, type Tone } from "@/lib/labels"
import { runPhase, type RunPhase } from "@/lib/run-view"
import { cn } from "@/lib/utils"

const PHASE: Record<Exclude<RunPhase, "failed">, { icon: LucideIcon; tone: Tone; label: string }> = {
  queued: { icon: Clock, tone: "neutral", label: "Queued" },
  working: { icon: Loader2, tone: "info", label: "Working" },
  resuming: { icon: Loader2, tone: "info", label: "Resuming" },
  awaiting_approval: { icon: ShieldCheck, tone: "info", label: STATUS_LABELS.waiting_for_approval },
  completed: { icon: CheckCircle2, tone: "success", label: "Completed" },
}

export function StatusBadge({ run, className }: { run: Run; className?: string }) {
  const phase = runPhase(run)
  const view =
    phase === "failed"
      ? { icon: XCircle, tone: describeError(run.error).tone, label: describeError(run.error).title }
      : PHASE[phase]
  const Icon = view.icon
  const spinning = phase === "working" || phase === "resuming"

  return (
    <Badge variant="outline" className={cn("h-6 rounded-md px-2", TONE_BADGE[view.tone], className)}>
      <Icon className={cn(spinning && "animate-spin")} aria-hidden="true" />
      {view.label}
    </Badge>
  )
}
