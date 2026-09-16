import { useEffect, useState } from "react"

import { approvalCountdown } from "@/lib/run-view"
import { serverNow } from "@/lib/server-clock"
import { cn } from "@/lib/utils"

/** Server-clock time, refreshed every second. Only the component using it re-renders. */
function useServerNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => serverNow())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(serverNow()), intervalMs)
    return () => window.clearInterval(timer)
  }, [intervalMs])
  return now
}

interface ApprovalCountdownProps {
  requestedAt: string | null
  expiresAt: string
  /** Called once when the countdown reaches zero. It must not treat the run as expired. */
  onReached?: () => void
  compact?: boolean
}

/**
 * Time left to decide, counted against the server's clock. Display only: reaching zero
 * means "ask the server", never "expired".
 */
export function ApprovalCountdown({ requestedAt, expiresAt, onReached, compact }: ApprovalCountdownProps) {
  const countdown = approvalCountdown(requestedAt, expiresAt, useServerNow())

  useEffect(() => {
    if (countdown.reached) onReached?.()
  }, [countdown.reached, onReached])

  if (countdown.reached) {
    return (
      // Visual only: the approval panel announces the pending expiry check once.
      <span className="text-xs text-warning">Expiry being confirmed…</span>
    )
  }

  const low = countdown.remainingMs < 60_000
  return (
    <span className={cn("flex items-center gap-2", compact ? "text-xs" : "text-sm")}>
      {/* role=timer is not live by default, so seconds ticking by are not announced. */}
      <span role="timer" aria-label="Time left to decide" className={cn("font-mono tabular-nums", low && "text-warning")}>
        {countdown.label}
      </span>
      {!compact && countdown.fraction !== null && (
        <span aria-hidden="true" className="h-1 w-20 overflow-hidden rounded-full bg-muted">
          <span
            className={cn("block h-full rounded-full transition-[width] duration-1000 ease-linear", low ? "bg-warning" : "bg-brand/70")}
            style={{ width: `${countdown.fraction * 100}%` }}
          />
        </span>
      )}
    </span>
  )
}
