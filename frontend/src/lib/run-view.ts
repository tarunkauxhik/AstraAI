/**
 * Pure presentation logic derived from one server Run. The backend is authoritative for
 * every business fact; nothing here decides pass/fail, approval or expiry.
 */
import type { ApiError } from "@/api/client"
import { NETWORK_ERROR_DETAIL } from "@/api/client"
import type { ErrorCode, Run, RunStage } from "@/api/types"
import { describeError, type Tone } from "@/lib/labels"

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

/**
 * The attempt a stored result belongs to: the current attempt, or the one before it while
 * a newer attempt is in progress (or was in progress when the run stopped).
 */
export function evidenceAttempt(run: Run, freshness: Freshness): number {
  const attempt = executionAttempt(run)
  return freshness === "stale" ? attempt - 1 : attempt
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
// Progress (derived from the current state only; there is no event history)

export type ProgressStepId = "understand" | "build" | "verify" | "approve"
/** "stopped" marks where a failed run ended; its tone says how serious that is. */
export type ProgressState = "done" | "current" | "upcoming" | "stopped"

export interface ProgressStep {
  id: ProgressStepId
  label: string
  state: ProgressState
}

export interface Progress {
  steps: ProgressStep[]
  /** Tone of the stop, when the run failed inside a step. A rejection is neutral. */
  stopTone: Tone | null
}

const PROGRESS_STEPS: readonly { id: ProgressStepId; label: string }[] = [
  { id: "understand", label: "Understand" },
  { id: "build", label: "Build" },
  { id: "verify", label: "Verify" },
  { id: "approve", label: "Approve" },
]

/** Step index per backend stage: -1 before any step, 4 once every step is done. */
const STAGE_PROGRESS: Record<RunStage, number> = {
  queued: -1,
  analyzing: 0,
  generating_tests: 1,
  generating_code: 1,
  executing: 2,
  reviewing: 2,
  revising_code: 2,
  revising_tests: 2,
  waiting_for_approval: 3,
  resuming: 3,
  completed: 4,
  // Never an error.stage in practice; a failed run is placed by its error instead.
  failed: -1,
}

export function progress(run: Run): Progress {
  const failed = run.status === "failed"
  const at = failed ? (run.error ? STAGE_PROGRESS[run.error.stage] : -1) : STAGE_PROGRESS[run.stage]
  const steps = PROGRESS_STEPS.map(({ id, label }, index): ProgressStep => {
    let state: ProgressState = "upcoming"
    if (index < at) state = "done"
    else if (index === at) state = failed ? "stopped" : "current"
    return { id, label, state }
  })
  const stopped = failed && at >= 0 && at < PROGRESS_STEPS.length
  return { steps, stopTone: stopped ? describeError(run.error).tone : null }
}

/**
 * One sentence of context while AstraAi repeats verification, or null on a first attempt.
 * Everything here comes from server counters and stage; nothing is inferred beyond them.
 */
export function workingNote(run: Run): string | null {
  const attempt = executionAttempt(run)
  switch (run.stage) {
    case "revising_code":
      return `Found an issue — repairing the solution (attempt ${attempt + 1}).`
    case "revising_tests":
      return `Found an issue — repairing the tests (attempt ${attempt + 1}).`
    case "executing":
    case "reviewing":
      if (attempt === 1) return null
      if (isRetryingExecution(run)) return `Verification didn't run — trying again (attempt ${attempt}).`
      return run.revision_count > 0
        ? `Checking the repaired version (attempt ${attempt}).`
        : `Verifying again (attempt ${attempt}).`
    default:
      return null
  }
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
// Approval countdown (display only: the server alone decides expiry)

export interface Countdown {
  remainingMs: number
  /** The expiry time has been reached on the (skew-corrected) clock. Not "expired". */
  reached: boolean
  /** "9:41", or "1:02:03" for an hour or more. */
  label: string
  /** Share of the approval window left, 0–1, when the start time is known. */
  fraction: number | null
}

export function approvalCountdown(
  requestedAt: string | null,
  expiresAt: string,
  nowMs: number,
): Countdown {
  const end = Date.parse(expiresAt)
  const remainingMs = Number.isNaN(end) ? 0 : Math.max(0, end - nowMs)
  const totalSeconds = Math.ceil(remainingMs / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = String(totalSeconds % 60).padStart(2, "0")
  const label =
    hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${seconds}` : `${minutes}:${seconds}`
  const start = requestedAt === null ? Number.NaN : Date.parse(requestedAt)
  const window = end - start
  const fraction =
    Number.isNaN(window) || window <= 0 ? null : Math.min(1, Math.max(0, remainingMs / window))
  return { remainingMs, reached: remainingMs === 0, label, fraction }
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
