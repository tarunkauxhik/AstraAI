import { useEffect, useState } from "react"
import { Check, Loader2, ShieldCheck, X } from "lucide-react"
import { toast } from "sonner"

import type { ApprovalDecision, Run } from "@/api/types"
import { MAX_EXECUTION_RETRIES, MAX_REVISIONS } from "@/api/types"
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
import { formatDateTime, formatRelative, formatTestCounts } from "@/lib/format"
import { EXECUTION_STATUS, LANGUAGE_LABELS } from "@/lib/labels"
import { describeApprovalError } from "@/lib/run-view"

/** Wall-clock time, refreshed every 15 seconds for the relative expiry text. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 15_000)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

/**
 * Shown only while the server says the run is waiting. Decisions are never applied
 * locally: the panel disappears when a refetch shows the server moved on.
 */
export function ApprovalPanel({ run }: { run: Run }) {
  const approval = useApproval(run.run_id)
  const [confirmReject, setConfirmReject] = useState(false)
  const now = useNow()
  // Locked from the first click until the server's new state replaces this panel.
  const locked = approval.isPending || approval.isSuccess
  const request = run.approval_request
  const counts = request ? formatTestCounts(request.tests_passed, request.tests_failed) : null
  const expiresAt = run.approval_expires_at
  const pastExpiry = expiresAt !== null && new Date(expiresAt).getTime() <= now

  function decide(decision: ApprovalDecision) {
    if (locked) return
    approval.mutate(decision, {
      onError: (error) => toast.error(describeApprovalError(error)),
    })
  }

  const actions = (
    <div className="flex gap-2">
      <Button
        variant="outline"
        onClick={() => setConfirmReject(true)}
        disabled={locked}
        aria-label="Reject this solution"
        className="flex-1 sm:flex-none"
      >
        <X aria-hidden="true" />
        Reject
      </Button>
      <Button
        onClick={() => decide("approve")}
        disabled={locked}
        aria-label="Approve this solution"
        className="flex-1 sm:flex-none"
      >
        {approval.isPending && approval.variables === "approve" ? (
          <Loader2 className="animate-spin" aria-hidden="true" />
        ) : (
          <Check aria-hidden="true" />
        )}
        {approval.isPending && approval.variables === "approve" ? "Approving…" : "Approve"}
      </Button>
    </div>
  )

  return (
    <section
      aria-labelledby="approval-heading"
      className="rounded-lg border border-l-2 border-l-brand bg-card p-4"
    >
      <div className="flex items-start gap-3">
        <ShieldCheck className="mt-0.5 size-5 shrink-0 text-brand" aria-hidden="true" />
        <div className="min-w-0 space-y-1">
          <h2 id="approval-heading" className="font-semibold">
            Verified — waiting for your approval
          </h2>
          <p className="text-sm text-muted-foreground">
            AstraAi generated tests and code, ran them in the sandbox, and its review accepted the
            result. Nothing is final until you decide.
          </p>
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
        {request && (
          <>
            <dt className="text-muted-foreground">Problem</dt>
            <dd>{request.problem_summary}</dd>
            <dt className="text-muted-foreground">Execution</dt>
            <dd>
              {EXECUTION_STATUS[request.execution_status].label}
              {counts && ` · ${counts}`}
            </dd>
          </>
        )}
        <dt className="text-muted-foreground">Language</dt>
        <dd>{LANGUAGE_LABELS[run.language]}</dd>
        <dt className="text-muted-foreground">Revisions</dt>
        <dd>
          {run.revision_count} of {MAX_REVISIONS} · retries {run.execution_retry_count} of{" "}
          {MAX_EXECUTION_RETRIES}
        </dd>
        {expiresAt && (
          <>
            <dt className="text-muted-foreground">Expires</dt>
            <dd>
              <time dateTime={expiresAt}>{formatDateTime(expiresAt)}</time>
              <span className="text-muted-foreground">
                {pastExpiry
                  ? " · time reached; the server will confirm"
                  : ` · ${formatRelative(expiresAt, now)}`}
              </span>
            </dd>
          </>
        )}
      </dl>

      {request?.critic_reason && (
        <div className="mt-3">
          <h3 className="label-caps mb-1">Review</h3>
          <p className="text-sm">{request.critic_reason}</p>
        </div>
      )}
      {request?.approval_means && (
        <p className="mt-3 text-xs text-muted-foreground">{request.approval_means}</p>
      )}

      {approval.isSuccess && (
        <p className="mt-3 text-sm text-muted-foreground" role="status">
          Decision sent. Waiting for the server to update the run…
        </p>
      )}

      {/* Inline actions on larger screens; a sticky bar keeps them reachable on phones. */}
      <div className="mt-4 hidden justify-end md:flex">{actions}</div>
      <div className="fixed inset-x-0 bottom-0 z-30 border-t bg-background/95 p-3 backdrop-blur md:hidden">
        {actions}
      </div>

      <AlertDialog open={confirmReject} onOpenChange={setConfirmReject}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reject this solution?</AlertDialogTitle>
            <AlertDialogDescription>
              The run ends as rejected and can't be approved afterwards. The generated code stays
              visible for reference.
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
