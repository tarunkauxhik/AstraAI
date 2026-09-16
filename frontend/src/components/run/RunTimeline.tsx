import { useEffect, useRef } from "react"
import { Check } from "lucide-react"

import type { Run } from "@/api/types"
import { TONE_ICON, TONE_TEXT } from "@/components/run/tone"
import type { Tone } from "@/lib/labels"
import { timeline, type StepState, type TimelineStep } from "@/lib/run-view"
import { cn } from "@/lib/utils"

const STATE_TEXT: Record<StepState, string> = {
  pending: "Upcoming",
  active: "Current",
  done: "Completed",
  failed: "Stopped here",
}

const STOP_MARKER: Record<Tone, string> = {
  neutral: "border-muted-foreground/40 bg-muted text-muted-foreground",
  info: "border-info/40 bg-info/15 text-info",
  success: "border-success/40 bg-success/15 text-success",
  warning: "border-warning/40 bg-warning/15 text-warning",
  danger: "border-destructive/40 bg-destructive/15 text-destructive",
}

function StepMarker({ step }: { step: TimelineStep }) {
  const base =
    "relative z-10 flex size-5 shrink-0 items-center justify-center rounded-full border bg-background transition-colors duration-200"
  switch (step.state) {
    case "done":
      return (
        <span className={cn(base, "border-success/40 bg-success/15 text-success")}>
          <Check className="size-3" aria-hidden="true" />
        </span>
      )
    case "failed": {
      const tone = step.tone ?? "danger"
      const Icon = TONE_ICON[tone]
      return (
        <span className={cn(base, STOP_MARKER[tone])}>
          <Icon className="size-3" aria-hidden="true" />
        </span>
      )
    }
    case "active":
      return (
        <span className={cn(base, "border-info/60 bg-info/10")}>
          <span className="size-2 animate-pulse rounded-full bg-info motion-reduce:animate-none" />
        </span>
      )
    case "pending":
      return <span className={cn(base, "border-dashed border-muted-foreground/30")} />
  }
}

/**
 * Where the run is, derived only from its current server state. The backend keeps no
 * event history, so this is not a log: repeated attempts are summarized by counters.
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
      <ol
        ref={list}
        className="flex gap-1 overflow-x-auto pb-1 scrollbar-thin xl:flex-col xl:gap-0 xl:overflow-visible xl:pb-0"
      >
        {steps.map((step, index) => {
          const stopTone = step.state === "failed" ? (step.tone ?? "danger") : null
          return (
            <li
              key={step.id}
              data-step={step.id}
              data-state={step.state}
              aria-current={step.state === "active" ? "step" : undefined}
              className={cn(
                "relative flex min-w-max items-start gap-2.5 rounded-md px-2 py-1.5 transition-colors duration-200 xl:min-w-0 xl:py-2",
                step.state === "active" && "bg-info/5",
              )}
            >
              <div className="flex flex-col items-center self-stretch">
                <StepMarker step={step} />
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
                    stopTone && stopTone !== "neutral" && TONE_TEXT[stopTone],
                  )}
                >
                  {step.label}
                  <span className="sr-only">: {STATE_TEXT[step.state]}</span>
                </p>
                {step.detail && (
                  <p
                    className={cn(
                      "text-xs leading-4 text-muted-foreground xl:mt-0.5",
                      step.state === "active" && "text-foreground/80",
                    )}
                  >
                    {step.detail}
                  </p>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
