import { useCallback, useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Check, Loader2, ShieldCheck } from "lucide-react"

import type { ApprovalDecision, Run } from "@/api/types"
import { Disclosure } from "@/components/Disclosure"
import { ApprovalCountdown } from "@/components/run/ApprovalCountdown"
import { Alert, AlertDescription } from "@/components/ui/alert"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { useApproval } from "@/hooks/useApproval"
import { DESKTOP_QUERY, useMediaQuery } from "@/hooks/useMediaQuery"
import { boostRunPolling, runQueryKey } from "@/hooks/useRun"
import { formatCount, formatTestResult } from "@/lib/format"
import { EXECUTION_STATUS, VERDICTS } from "@/lib/labels"
import { describeApprovalError } from "@/lib/run-view"

interface ApprovalPanelProps {
  run: Run
  onShowDetails: () => void
}

/**
 * The decision, shown only while the server says the run is waiting. Nothing is applied
 * locally: the panel is replaced when a refetch shows the server moved on. Actions and the
 * countdown exist once: in this panel on desktop, in a sticky bar on smaller screens.
 */
export function ApprovalPanel({ run, onShowDetails }: ApprovalPanelProps) {
  const queryClient = useQueryClient()
  const approval = useApproval(run.run_id)
  const isDesktop = useMediaQuery(DESKTOP_QUERY)
  const [confirmReject, setConfirmReject] = useState(false)
  const [expiryReached, setExpiryReached] = useState(false)
  const bar = useRef<HTMLDivElement>(null)

  // The fixed bar overlays the page bottom: publish its rendered height (safe area included)
  // so the page reserves exactly that much room.
  useEffect(() => {
    const element = bar.current
    if (!element || typeof ResizeObserver === "undefined") return
    const root = document.documentElement
    const observer = new ResizeObserver(() =>
      root.style.setProperty("--approval-bar-height", `${element.offsetHeight}px`),
    )
    observer.observe(element)
    return () => {
      observer.disconnect()
      root.style.removeProperty("--approval-bar-height")
    }
  }, [isDesktop])

  // Zero on the countdown only means "check with the server"; the run stays as reported.
  const handleExpiryReached = useCallback(() => {
    setExpiryReached(true)
    boostRunPolling(run.run_id)
    void queryClient.invalidateQueries({ queryKey: runQueryKey(run.run_id) })
  }, [queryClient, run.run_id])

  const locked = approval.isPending || approval.isSuccess || expiryReached
  const request = run.approval_request
  const tests = request
    ? (formatTestResult(request.tests_passed, request.tests_failed) ??
      EXECUTION_STATUS[request.execution_status].label)
    : null
  const review = run.critic_result ? VERDICTS[run.critic_result.verdict].label : null
  const repairs = [
    run.revision_count > 0 ? formatCount(run.revision_count, "repair") : null,
    run.execution_retry_count > 0 ? formatCount(run.execution_retry_count, "retry", "retries") : null,
  ].filter(Boolean)
  const approving = approval.isPending && approval.variables === "approve"

  function decide(decision: ApprovalDecision) {
    if (locked) return
    approval.mutate(decision)
  }

  const countdown = run.approval_expires_at && (
    <ApprovalCountdown
      requestedAt={run.approval_requested_at}
      expiresAt={run.approval_expires_at}
      onReached={handleExpiryReached}
    />
  )

  const actions = (
    <div className="flex gap-2">
      <Button
        size="lg"
        onClick={() => decide("approve")}
        disabled={locked}
        aria-label="Approve this solution"
        className="flex-2"
      >
        {approving ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Check aria-hidden="true" />}
        {approving ? "Approving…" : "Approve"}
      </Button>
      <Button
        size="lg"
        variant="outline"
        onClick={() => setConfirmReject(true)}
        disabled={locked}
        aria-label="Reject this solution"
        className="flex-1"
      >
        Reject
      </Button>
    </div>
  )

  return (
    <section aria-labelledby="approval-heading" className="space-y-4">
      <div>
        <p className="flex items-center gap-1.5 text-sm font-medium text-success">
          <ShieldCheck className="size-4" aria-hidden="true" />
          Verified by AstraAi
        </p>
        <h2 id="approval-heading" className="mt-1 text-lg font-semibold">
          Ready for your approval
        </h2>
      </div>

      <ul className="space-y-1 text-sm">
        {tests && (
          <li className="flex items-center gap-2">
            <Check className="size-4 text-success" aria-hidden="true" />
            {tests}
          </li>
        )}
        {review && (
          <li className="flex items-center gap-2">
            <Check className="size-4 text-success" aria-hidden="true" />
            {review}
          </li>
        )}
        {repairs.length > 0 && <li className="pl-6 text-muted-foreground">After {repairs.join(" and ")}</li>}
      </ul>

      {isDesktop && (
        <div className="space-y-2">
          {actions}
          {countdown && <p className="text-center">{countdown}</p>}
        </div>
      )}

      {approval.error && !approval.isPending && (
        <Alert variant="destructive">
          <AlertDescription>{describeApprovalError(approval.error)}</AlertDescription>
        </Alert>
      )}
      {approval.isSuccess && (
        <p className="text-sm text-muted-foreground" role="status">
          Decision sent. Updating…
        </p>
      )}
      {expiryReached && !approval.isSuccess && (
        <p className="text-sm text-muted-foreground" role="status">
          Checking with the server whether the approval window has closed…
        </p>
      )}

      <div className="space-y-1 border-t pt-3">
        {request?.critic_reason && (
          <Disclosure summary="Why this was accepted">
            <p className="text-sm leading-relaxed">{request.critic_reason}</p>
            {request.approval_means && (
              <p className="mt-2 text-sm text-muted-foreground">{request.approval_means}</p>
            )}
          </Disclosure>
        )}
        <button
          type="button"
          onClick={onShowDetails}
          className="rounded-sm py-1 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          Verification details
        </button>
      </div>

      {!isDesktop && (
        <div
          ref={bar}
          role="region"
          aria-label="Approval actions"
          className="fixed inset-x-0 bottom-0 z-30 space-y-2 border-t bg-background/95 px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur"
        >
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-medium">Ready for your approval</span>
            {countdown}
          </div>
          {actions}
        </div>
      )}

      <AlertDialog open={confirmReject} onOpenChange={setConfirmReject}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reject this solution?</AlertDialogTitle>
            <AlertDialogDescription>This will end the run and cannot be undone.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => decide("reject")}>
              Reject
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}
