import { useCallback, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Check, Loader2, ShieldCheck, X } from "lucide-react"

import type { ApprovalDecision, Run } from "@/api/types"
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
import { boostRunPolling, runQueryKey } from "@/hooks/useRun"
import { formatCount, formatDateTime, formatTestCounts } from "@/lib/format"
import { EXECUTION_STATUS, LANGUAGE_LABELS } from "@/lib/labels"
import { describeApprovalError } from "@/lib/run-view"

/**
 * Shown only while the server says the run is waiting. Decisions are never applied
 * locally: the panel is replaced when a refetch shows the server moved on.
 */
export function ApprovalPanel({ run }: { run: Run }) {
  const queryClient = useQueryClient()
  const approval = useApproval(run.run_id)
  const [confirmReject, setConfirmReject] = useState(false)
  const [expiryReached, setExpiryReached] = useState(false)

  // Zero on the countdown only means "check with the server"; the run stays as reported.
  const handleExpiryReached = useCallback(() => {
    setExpiryReached(true)
    boostRunPolling(run.run_id)
    void queryClient.invalidateQueries({ queryKey: runQueryKey(run.run_id) })
  }, [queryClient, run.run_id])

  const submitting = approval.isPending
  const locked = submitting || approval.isSuccess || expiryReached
  const request = run.approval_request
  const counts = request ? formatTestCounts(request.tests_passed, request.tests_failed) : null
  const expiresAt = run.approval_expires_at

  function decide(decision: ApprovalDecision) {
    if (locked) return
    approval.mutate(decision)
  }

  function actions(compact: boolean) {
    return (
      <div className="flex gap-2">
        <Button
          variant="ghost"
          size={compact ? "lg" : "default"}
          onClick={() => setConfirmReject(true)}
          disabled={locked}
          aria-label="Reject this solution"
          className="flex-1 border border-border text-muted-foreground sm:flex-none"
        >
          <X aria-hidden="true" />
          Reject
        </Button>
        <Button
          size={compact ? "lg" : "default"}
          onClick={() => decide("approve")}
          disabled={locked}
          aria-label="Approve this solution"
          className="flex-2 sm:flex-none sm:px-4"
        >
          {submitting && approval.variables === "approve" ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : (
            <Check aria-hidden="true" />
          )}
          {submitting && approval.variables === "approve" ? "Approving…" : "Approve"}
        </Button>
      </div>
    )
  }

  return (
    <section
      aria-labelledby="approval-heading"
      className="rounded-lg border border-brand/30 bg-card shadow-[0_0_0_1px_oklch(0.8_0.09_205/0.06)]"
    >
      <header className="flex items-start gap-3 border-b border-brand/20 bg-brand/4 px-4 py-3">
        <ShieldCheck className="mt-0.5 size-5 shrink-0 text-brand" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="label-caps text-brand">Verified by AstraAi</p>
          <h2 id="approval-heading" className="mt-1 font-semibold">
            Waiting for your approval
          </h2>
        </div>
        {expiresAt && (
          <div className="shrink-0 pt-0.5">
            <ApprovalCountdown
              requestedAt={run.approval_requested_at}
              expiresAt={expiresAt}
              onReached={handleExpiryReached}
            />
          </div>
        )}
      </header>

      <div className="space-y-4 p-4">
        <p className="text-sm text-muted-foreground">
          AstraAi generated tests and a solution, ran them in the sandbox, and its review accepted
          the result. Nothing is accepted until you approve.
        </p>

        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
          {request && (
            <>
              <dt className="text-muted-foreground">Problem</dt>
              <dd>{request.problem_summary}</dd>
            </>
          )}
          <dt className="text-muted-foreground">Language</dt>
          <dd>{LANGUAGE_LABELS[run.language]}</dd>
          {request && (
            <>
              <dt className="text-muted-foreground">Tests</dt>
              <dd>
                {EXECUTION_STATUS[request.execution_status].label}
                {counts && <span className="text-muted-foreground"> · {counts}</span>}
              </dd>
            </>
          )}
          <dt className="text-muted-foreground">Repairs</dt>
          <dd>
            {formatCount(run.revision_count, "revision")} ·{" "}
            {formatCount(run.execution_retry_count, "retry", "retries")}
          </dd>
          {expiresAt && (
            <>
              <dt className="text-muted-foreground">Expires</dt>
              <dd>
                <time dateTime={expiresAt}>{formatDateTime(expiresAt)}</time>
              </dd>
            </>
          )}
        </dl>

        {request?.critic_reason && (
          <section className="rounded-md bg-muted/50 px-3 py-2">
            <h3 className="label-caps mb-1">Review</h3>
            <p className="text-sm leading-relaxed">{request.critic_reason}</p>
          </section>
        )}
        {request?.approval_means && (
          <p className="text-xs text-muted-foreground">{request.approval_means}</p>
        )}

        {approval.error && !approval.isPending && (
          <Alert variant="destructive">
            <AlertDescription>{describeApprovalError(approval.error)}</AlertDescription>
          </Alert>
        )}
        {approval.isSuccess && (
          <p className="text-sm text-muted-foreground" role="status">
            Decision sent. Waiting for the server to update the run…
          </p>
        )}
        {expiryReached && !approval.isSuccess && (
          <p className="text-sm text-muted-foreground" role="status">
            The approval window has reached its end on this device. Checking with the server
            whether the run has expired…
          </p>
        )}

        {/* Inline actions on larger screens; a sticky bar keeps them in reach on phones. */}
        <div className="hidden justify-end md:flex">{actions(false)}</div>
      </div>

      <div
        role="region"
        aria-label="Approval actions"
        className="fixed inset-x-0 bottom-0 z-30 space-y-2 border-t bg-background/95 px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur md:hidden"
      >
        <div className="flex items-center justify-between gap-3 text-xs">
          <span className="font-medium text-brand">Verified · waiting for your approval</span>
          {expiresAt && (
            <ApprovalCountdown requestedAt={run.approval_requested_at} expiresAt={expiresAt} compact />
          )}
        </div>
        {actions(true)}
      </div>

      <AlertDialog open={confirmReject} onOpenChange={setConfirmReject}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reject this solution?</AlertDialogTitle>
            <AlertDialogDescription>
              Rejecting ends the run. The solution won't be accepted and can't be approved later.
              The generated code and results stay visible.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep reviewing</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => decide("reject")}>
              Reject solution
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}
