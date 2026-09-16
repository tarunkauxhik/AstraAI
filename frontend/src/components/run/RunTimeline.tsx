import { useEffect, useRef } from "react"
import { Check, X } from "lucide-react"

import type { Run } from "@/api/types"
import { timeline, type StepState } from "@/lib/run-view"
import { cn } from "@/lib/utils"

const STATE_TEXT: Record<StepState, string> = {
  pending: "Not started",
  active: "In progress",
  done: "Done",
  failed: "Stopped here",
}

function StepMarker({ state }: { state: StepState }) {
  const base = "flex size-5 shrink-0 items-center justify-center rounded-full border"
  if (state === "done") {
    return (
      <span className={cn(base, "border-success/40 bg-success/15 text-success")}>
        <Check className="size-3" aria-hidden="true" />
      </span>
    )
  }
  if (state === "failed") {
    return (
      <span className={cn(base, "border-destructive/40 bg-destructive/15 text-destructive")}>
        <X className="size-3" aria-hidden="true" />
      </span>
    )
  }
  if (state === "active") {
    return (
      <span className={cn(base, "border-info/50 bg-info/10")}>
        <span className="size-2 animate-pulse rounded-full bg-info" />
      </span>
    )
  }
  return <span className={cn(base, "border-border")} />
}

/**
 * Where the run is, derived only from its current server state. The backend keeps no
 * event history, so repeated attempts are summarized by counters, not listed.
 */
export function RunTimeline({ run }: { run: Run }) {
  const steps = timeline(run)
  const list = useRef<HTMLOListElement>(null)
  const focus = steps.findLast((step) => step.state === "active" || step.state === "failed")?.id

  // On narrow screens the steps scroll sideways; keep the current one in view.
  useEffect(() => {
    const element = list.current
    const current = element?.querySelector<HTMLElement>(`[data-step="${focus}"]`)
    if (!element || !current || element.scrollWidth <= element.clientWidth) return
    element.scrollTo({ left: current.offsetLeft - element.offsetLeft - 8, behavior: "smooth" })
  }, [focus])

  return (
    <nav aria-label="Run progress">
      <h2 className="label-caps mb-3 hidden xl:block">Agent progress</h2>
      <ol ref={list} className="flex gap-1 overflow-x-auto pb-1 [scrollbar-width:thin] xl:flex-col xl:gap-0 xl:overflow-visible xl:pb-0">
        {steps.map((step, index) => (
          <li
            key={step.id}
            data-step={step.id}
            aria-current={step.state === "active" ? "step" : undefined}
            className="relative flex min-w-max items-start gap-2.5 rounded-md px-2 py-1.5 xl:min-w-0 xl:py-2"
          >
            <div className="flex flex-col items-center self-stretch">
              <StepMarker state={step.state} />
              {index < steps.length - 1 && (
                <span
                  aria-hidden="true"
                  className={cn(
                    "mt-1 hidden w-px flex-1 xl:block",
                    step.state === "done" ? "bg-success/30" : "bg-border",
                  )}
                />
              )}
            </div>
            <div className="min-w-0 pb-1">
              <p
                className={cn(
                  "text-sm leading-5 font-medium",
                  step.state === "pending" && "text-muted-foreground",
                  step.state === "failed" && "text-destructive",
                )}
              >
                {step.label}
                <span className="sr-only">: {STATE_TEXT[step.state]}</span>
              </p>
              {step.detail && (
                <p className="text-xs leading-4 text-muted-foreground xl:mt-0.5">
                  {step.detail}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
    </nav>
  )
}
