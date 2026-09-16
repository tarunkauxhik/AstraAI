/**
 * Pure presentation logic derived from one server Run. The backend is authoritative for
 * every business fact; nothing here decides pass/fail, approval or expiry.
 */
import type { ApiError } from "@/api/client"
import { NETWORK_ERROR_DETAIL } from "@/api/client"
import type { ApprovalStatus, ErrorCode, Run, RunStage } from "@/api/types"
import { MAX_EXECUTION_RETRIES, MAX_REVISIONS } from "@/api/types"
import { APPROVAL_STATUS_LABELS, describeError } from "@/lib/labels"

// ---------------------------------------------------------------------------------------
// Semantic state

export type RunPhase =
  | "queued"
  | "working"
  | "resuming"
  | "awaiting_approval"
  | "completed"
  | "failed"

/** Top-level status always wins; stage only refines a running run. */
export function runPhase(run: Run): RunPhase {
  switch (run.status) {
    case "failed":
      return "failed"
    case "completed":
      return "completed"
    case "waiting_for_approval":
      return "awaiting_approval"
    case "running":
      return run.stage === "resuming" ? "resuming" : "working"
    case "queued":
      return "queued"
  }
}

export function isTerminal(run: Run): boolean {
  return run.status === "completed" || run.status === "failed"
}

export type PageState =
  | { kind: "loading" }
  | { kind: "not_found" }
  | { kind: "unreachable"; error: ApiError }
  | { kind: "run"; run: Run; phase: RunPhase; connectionError: ApiError | null }

/**
 * Precedence: HTTP/network problems first, then the run's own status. A run that has been
 * loaded stays visible during a transient failure, flagged by `connectionError`.
 */
export function pageState(data: Run | undefined, error: ApiError | null): PageState {
  if (error?.isNotFound) return { kind: "not_found" }
  if (data === undefined) return error ? { kind: "unreachable", error } : { kind: "loading" }
  return { kind: "run", run: data, phase: runPhase(data), connectionError: error }
}

/** Approve/Reject controls exist only while the server says it is waiting. */
export function showApprovalControls(run: Run): boolean {
  return run.status === "waiting_for_approval"
}

/** True only when the server has accepted a verified solution (not merely a passing run). */
export function isVerified(run: Run): boolean {
  const phase = runPhase(run)
  return (
    phase === "awaiting_approval" ||
    phase === "resuming" ||
    phase === "completed" ||
    run.approval_status === "approved"
  )
}

// ---------------------------------------------------------------------------------------
// Attempts and staleness

/** Executions so far, counting the one in progress: the first run, each revision, each retry. */
export function executionAttempt(run: Run): number {
  return 1 + run.revision_count + run.execution_retry_count
}

/** Failures decided after a review: their evidence is the latest, not a previous attempt's. */
const DECIDED_AFTER_REVIEW: ReadonlySet<ErrorCode> = new Set([
  "needs_human_review",
  "revision_budget_exhausted",
  "retry_budget_exhausted",
  "sandbox_unavailable",
])

/** The stage whose data the evidence reflects: where a failed run actually stopped. */
function evidenceStage(run: Run): RunStage {
  if (run.status === "failed" && run.error && !DECIDED_AFTER_REVIEW.has(run.error.code)) {
    return run.error.stage
  }
  return run.stage
}

export type Freshness = "current" | "stale"

/**
 * The server keeps only the latest results. While a newer attempt executes, the stored
 * execution result belongs to the previous attempt and must not read as the current one.
 */
export function executionFreshness(run: Run): Freshness | null {
  if (run.execution_result === null) return null
  return evidenceStage(run) === "executing" ? "stale" : "current"
}

/** The stored review is the previous attempt's until the current execution is reviewed. */
export function criticFreshness(run: Run): Freshness | null {
  if (run.critic_result === null) return null
  const stage = evidenceStage(run)
  return stage === "executing" || stage === "reviewing" ? "stale" : "current"
}

/** A re-execution of unchanged code after a sandbox infrastructure error. */
export function isRetryingExecution(run: Run): boolean {
  return (
    evidenceStage(run) === "executing" &&
    run.execution_retry_count > 0 &&
    run.execution_result?.status === "infrastructure_error"
  )
}

// ---------------------------------------------------------------------------------------
// Timeline (derived from the current state only; there is no event history)

export type StepId = "analyze" | "test_plan" | "code" | "verify" | "approval" | "result"
export type StepState = "pending" | "active" | "done" | "failed"

export interface TimelineStep {
  id: StepId
  label: string
  state: StepState
  detail: string | null
}

const STEPS: readonly { id: StepId; label: string }[] = [
  { id: "analyze", label: "Analyze" },
  { id: "test_plan", label: "Test plan" },
  { id: "code", label: "Code" },
  { id: "verify", label: "Verify" },
  { id: "approval", label: "Approval" },
  { id: "result", label: "Result" },
]
const RESULT_INDEX = 5

/** Index of the step a stage belongs to; -1 before any step, 6 once everything is done. */
const STAGE_STEP: Record<RunStage, number> = {
  queued: -1,
  analyzing: 0,
  generating_tests: 1,
  generating_code: 2,
  executing: 3,
  reviewing: 3,
  revising_code: 3,
  revising_tests: 3,
  waiting_for_approval: 4,
  resuming: RESULT_INDEX,
  completed: 6,
  // Never an error.stage in practice; a failed run is placed by its error instead.
  failed: -1,
}

/** What the Verify step is doing right now, in words. */
export function verifyActivity(run: Run): string | null {
  const attempt = executionAttempt(run)
  switch (evidenceStage(run)) {
    case "executing":
      return isRetryingExecution(run)
        ? `Retrying execution (retry ${run.execution_retry_count} of ${MAX_EXECUTION_RETRIES})`
        : `Executing attempt ${attempt}`
    case "reviewing":
      return `Reviewing attempt ${attempt}`
    case "revising_code":
      return `Revising code (revision ${run.revision_count + 1} of ${MAX_REVISIONS})`
    case "revising_tests":
      return `Revising tests (revision ${run.revision_count + 1} of ${MAX_REVISIONS})`
    default:
      return null
  }
}

function verifyCounters(run: Run): string {
  const parts = [`Attempt ${executionAttempt(run)}`]
  if (run.revision_count > 0) parts.push(`${run.revision_count}/${MAX_REVISIONS} revisions`)
  if (run.execution_retry_count > 0) {
    parts.push(`${run.execution_retry_count}/${MAX_EXECUTION_RETRIES} retries`)
  }
  return parts.join(" · ")
}

function approvalDetail(status: ApprovalStatus | null): string | null {
  return status === null ? null : APPROVAL_STATUS_LABELS[status]
}

export function timeline(run: Run): TimelineStep[] {
  const failed = run.status === "failed"
  // A failed run marks the step it stopped in (from error.stage); a run that failed before
  // any step started (for example a shutdown while queued) marks only the result.
  const current = failed
    ? run.error
      ? STAGE_STEP[run.error.stage]
      : -1
    : STAGE_STEP[run.stage]

  return STEPS.map(({ id, label }, index) => {
    let state: StepState = "pending"
    if (index < current) state = "done"
    else if (index === current) state = failed ? "failed" : "active"
    if (failed && index === RESULT_INDEX) state = "failed"

    let detail: string | null = null
    if (id === "verify" && (state !== "pending" || run.execution_result !== null)) {
      const activity = state === "active" || state === "failed" ? verifyActivity(run) : null
      detail = activity ?? verifyCounters(run)
    } else if (id === "approval") {
      detail = approvalDetail(run.approval_status)
    } else if (id === "result" && run.status === "completed") {
      detail = "Approved and complete"
    } else if (id === "result" && failed) {
      detail = describeError(run.error).title
    }
    return { id, label, state, detail }
  })
}

// ---------------------------------------------------------------------------------------
// Polling policy

export const POLL_MS = {
  queued: 3_000,
  working: 2_000,
  awaitingApproval: 5_000,
  fast: 1_000,
  hidden: 15_000,
  backoffStart: 2_000,
  backoffMax: 30_000,
} as const

export interface PollContext {
  /** document.hidden */
  hidden: boolean
  /** Shortly after an approval decision: look for the server's reaction quickly. */
  boosted: boolean
  /** Consecutive failed polls. */
  failures: number
}

/** How long until the next poll; false stops polling. */
export function pollInterval(
  run: Run | undefined,
  error: ApiError | null,
  context: PollContext,
): number | false {
  if (error?.isNotFound) return false
  if (run && isTerminal(run)) return false
  if (context.failures > 0) {
    return Math.min(
      POLL_MS.backoffMax,
      POLL_MS.backoffStart * 2 ** (context.failures - 1),
    )
  }
  let interval: number
  if (!run) interval = POLL_MS.working
  else if (context.boosted || runPhase(run) === "resuming") interval = POLL_MS.fast
  else if (run.status === "queued") interval = POLL_MS.queued
  else if (run.status === "waiting_for_approval") interval = POLL_MS.awaitingApproval
  else interval = POLL_MS.working
  return context.hidden ? Math.max(interval, POLL_MS.hidden) : interval
}

// ---------------------------------------------------------------------------------------
// Approval request errors

/** What to tell the user when a decision request fails. The run is refetched regardless. */
export function describeApprovalError(error: ApiError): string {
  if (error.kind === "network") {
    return `${NETWORK_ERROR_DETAIL} Refreshing the run to see whether your decision was recorded.`
  }
  switch (error.status) {
    case 404:
      return "This run no longer exists on the server."
    case 409:
      // The server says why: expired, or no longer waiting (for example already decided).
      return error.detail
    case 422:
      return "The decision couldn't be sent. Please try again."
    case 429: {
      const wait = error.retryAfterSeconds ? ` in ${error.retryAfterSeconds} seconds` : " shortly"
      return `The run queue is full, so the approval wasn't accepted. The run is still waiting; try again${wait}.`
    }
    case 503:
      return "The service is shutting down, so the decision couldn't be recorded."
    default:
      return error.detail
  }
}
