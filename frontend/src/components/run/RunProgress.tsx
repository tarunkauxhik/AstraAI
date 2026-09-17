import { Check } from "lucide-react"

import type { Run } from "@/api/types"
import { TONE_ICON } from "@/components/run/tone"
import { progress, type ProgressState } from "@/lib/run-view"
import { cn } from "@/lib/utils"

const STATE_TEXT: Record<ProgressState, string> = {
  done: "done",
  current: "in progress",
  upcoming: "not started",
  stopped: "stopped here",
}

/**
 * Where the run is in four plain steps. Derived from the current server state only: it is
 * not a history, and the final outcome is shown by the decision panel, not as a step.
 */
export function RunProgress({ run }: { run: Run }) {
  const { steps, stopTone } = progress(run)
  const StopIcon = TONE_ICON[stopTone ?? "danger"]

  return (
    <nav aria-label="Progress">
      <ol className="flex items-center gap-2 sm:gap-3">
        {steps.map((step, index) => (
          <li
            key={step.id}
            aria-current={step.state === "current" ? "step" : undefined}
            className="flex min-w-0 items-center gap-2 sm:gap-3"
          >
            {index > 0 && (
              <span
                aria-hidden="true"
                className={cn(
                  "h-px w-4 shrink-0 sm:w-8",
                  step.state === "upcoming" ? "bg-border" : "bg-muted-foreground/40",
                )}
              />
            )}
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className={cn(
                  "flex size-4 shrink-0 items-center justify-center rounded-full border transition-colors duration-200",
                  step.state === "done" && "border-muted-foreground/40 text-muted-foreground",
                  step.state === "current" && "border-brand bg-brand/15",
                  step.state === "upcoming" && "border-dashed border-muted-foreground/30",
                  step.state === "stopped" &&
                    (stopTone === "neutral"
                      ? "border-muted-foreground/50 text-muted-foreground"
                      : stopTone === "warning"
                        ? "border-warning/60 text-warning"
                        : "border-destructive/60 text-destructive"),
                )}
              >
                {step.state === "done" && <Check className="size-2.5" />}
                {step.state === "current" && (
                  <span className="size-1.5 animate-pulse rounded-full bg-brand motion-reduce:animate-none" />
                )}
                {step.state === "stopped" && <StopIcon className="size-2.5" />}
              </span>
              <span
                className={cn(
                  "text-sm whitespace-nowrap",
                  step.state === "current" ? "font-medium text-foreground" : "text-muted-foreground",
                  // On phones only the current (or stopped) step keeps its label.
                  step.state !== "current" && step.state !== "stopped" && "sr-only sm:not-sr-only",
                )}
              >
                {step.label}
                <span className="sr-only">: {STATE_TEXT[step.state]}</span>
              </span>
            </span>
          </li>
        ))}
      </ol>
    </nav>
  )
}
