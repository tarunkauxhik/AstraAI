import { useEffect } from "react"

import { Button } from "@/components/ui/button"
import { useServerNow } from "@/hooks/useServerNow"
import { approvalCountdown } from "@/lib/run-view"
import { cn } from "@/lib/utils"

/** From here on the time left shows in seconds and more time can be requested. */
const WARN_MS = 120_000

interface ApprovalCountdownProps {
  expiresAt: string
  /** Called once when the countdown reaches zero. It must not treat the run as expired. */
  onReached: () => void
  onMoreTime: () => void
  extending: boolean
  disabled: boolean
}

/**
 * Time left to review, counted against the server's clock. Calm minutes until the last two,
 * then seconds and a way to ask for more time (WCAG 2.2.1). Display only: reaching zero
 * means "ask the server", never "expired".
 */
export function ApprovalCountdown({
  expiresAt,
  onReached,
  onMoreTime,
  extending,
  disabled,
}: ApprovalCountdownProps) {
  const countdown = approvalCountdown(expiresAt, useServerNow())
  const low = countdown.remainingMs <= WARN_MS

  useEffect(() => {
    if (countdown.reached) onReached()
  }, [countdown.reached, onReached])

  return (
    <div className="flex min-h-8 items-center justify-between gap-3 text-sm">
      {countdown.reached ? (
        <p className="text-muted-foreground">Closing the review…</p>
      ) : (
        <p className={cn("text-muted-foreground", low && "text-warning")}>
          Review closes in{" "}
          {/* role=timer is not live by default, so the passing time is not announced. */}
          <span role="timer" aria-label="Time left to review" className="tabular-nums">
            {low ? countdown.label : `${Math.ceil(countdown.remainingMs / 60_000)} min`}
          </span>
        </p>
      )}
      {low && !countdown.reached && (
        <Button
          variant="ghost"
          size="sm"
          onClick={onMoreTime}
          disabled={disabled || extending}
          className="h-11 lg:h-8"
        >
          {extending ? "Adding time…" : "More time"}
        </Button>
      )}
      {/* Announced once when the warning starts, so nobody runs out of time unwarned. */}
      <p className="sr-only" role="status">
        {low && !countdown.reached
          ? "The review closes in less than 2 minutes. Choose More time to keep reviewing."
          : ""}
      </p>
    </div>
  )
}
