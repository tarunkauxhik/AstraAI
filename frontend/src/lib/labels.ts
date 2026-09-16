import type {
  ApprovalStatus,
  CriticVerdict,
  ExecutionStatus,
  KnownErrorCode,
  Language,
  RecommendedAction,
  RunError,
  RunStage,
  RunStatus,
} from "@/api/types"
import { KNOWN_ERROR_CODES, MAX_REVISIONS } from "@/api/types"

/** Visual intent. Components map tones to colors and always pair them with text/icons. */
export type Tone = "neutral" | "info" | "success" | "warning" | "danger"

export const LANGUAGE_LABELS: Record<Language, string> = {
  python: "Python",
  cpp: "C++",
}

export const STATUS_LABELS: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  waiting_for_approval: "Awaiting approval",
  completed: "Completed",
  failed: "Failed",
}

export const STAGE_LABELS: Record<RunStage, string> = {
  queued: "Queued",
  analyzing: "Analyzing task",
  generating_tests: "Generating test plan",
  generating_code: "Generating code",
  executing: "Executing in sandbox",
  reviewing: "Reviewing results",
  revising_code: "Revising code",
  revising_tests: "Revising tests",
  waiting_for_approval: "Waiting for approval",
  resuming: "Resuming",
  completed: "Completed",
  failed: "Failed",
}

export const EXECUTION_STATUS: Record<ExecutionStatus, { label: string; tone: Tone }> = {
  passed: { label: "Passed", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  // A limit says nothing definite about the code, so it is a warning, not a failure.
  timed_out: { label: "Time limit reached", tone: "warning" },
  resource_exceeded: { label: "Resource limit reached", tone: "warning" },
  // Not the code's fault: the sandbox itself could not run it.
  infrastructure_error: { label: "Sandbox unavailable", tone: "neutral" },
}

const EXECUTION_ERROR_TYPES: Record<string, string> = {
  compile_error: "Compile error",
  test_failure: "Tests failed",
  runtime_error: "Runtime error",
  timeout: "Timed out",
  out_of_memory: "Memory limit exceeded",
}

export function executionErrorTypeLabel(errorType: string | null): string | null {
  if (errorType === null) return null
  if (errorType.startsWith("container_")) return "Sandbox could not run the code"
  return EXECUTION_ERROR_TYPES[errorType] ?? null
}

export const VERDICTS: Record<CriticVerdict, { label: string; tone: Tone }> = {
  pass: { label: "Pass", tone: "success" },
  code_failure: { label: "Code issue", tone: "danger" },
  test_failure: { label: "Test issue", tone: "warning" },
  execution_failure: { label: "No trustworthy evidence", tone: "neutral" },
  ambiguous: { label: "Inconclusive", tone: "warning" },
}

export const ACTION_LABELS: Record<RecommendedAction, string> = {
  accept: "Accept",
  revise_code: "Revise the code",
  revise_tests: "Revise the tests",
  retry_execution: "Retry execution",
  needs_human_review: "Needs human review",
}

export const APPROVAL_STATUS_LABELS: Record<ApprovalStatus, string> = {
  pending: "Waiting for your decision",
  approved: "Approved",
  rejected: "Rejected",
  expired: "Expired",
}

export type FailureCategory =
  | "decision"
  | "review"
  | "infrastructure"
  | "model"
  | "timeout"
  | "interrupted"
  | "internal"

export interface ErrorPresentation {
  title: string
  description: string
  tone: Tone
  category: FailureCategory
}

export const ERROR_PRESENTATION: Record<KnownErrorCode, ErrorPresentation> = {
  approval_rejected: {
    title: "Rejected",
    description: "You rejected the verified result, so it was not accepted.",
    tone: "neutral",
    category: "decision",
  },
  approval_expired: {
    title: "Approval expired",
    description: "No decision was received before the approval window closed.",
    tone: "warning",
    category: "decision",
  },
  needs_human_review: {
    title: "Needs human review",
    description: "AstraAi couldn't establish that the solution is correct.",
    tone: "warning",
    category: "review",
  },
  revision_budget_exhausted: {
    title: "Revision budget used",
    description: `AstraAi used all ${MAX_REVISIONS} revisions without reaching a verified solution.`,
    tone: "warning",
    category: "review",
  },
  retry_budget_exhausted: {
    title: "Execution retries used",
    description: "The code couldn't be executed, even after retrying.",
    tone: "neutral",
    category: "infrastructure",
  },
  sandbox_unavailable: {
    title: "Sandbox unavailable",
    description: "The code couldn't be executed because the sandbox is unavailable.",
    tone: "neutral",
    category: "infrastructure",
  },
  run_timeout: {
    title: "Run timed out",
    description: "Active work took longer than the run time limit.",
    tone: "danger",
    category: "timeout",
  },
  llm_timeout: {
    title: "Model timed out",
    description: "The language model took too long to respond.",
    tone: "danger",
    category: "model",
  },
  llm_failed: {
    title: "Model request failed",
    description: "The language model request failed or returned unusable output.",
    tone: "danger",
    category: "model",
  },
  shutdown: {
    title: "Interrupted",
    description: "The service stopped while this run was in progress.",
    tone: "neutral",
    category: "interrupted",
  },
  invalid_step_output: {
    title: "Unusable step output",
    description: "A step produced output that the next step couldn't use.",
    tone: "danger",
    category: "internal",
  },
  internal_error: {
    title: "Internal error",
    description: "The run failed because of an internal error.",
    tone: "danger",
    category: "internal",
  },
}

export const UNKNOWN_ERROR: ErrorPresentation = {
  title: "Run failed",
  description: "The run ended without a result.",
  tone: "danger",
  category: "internal",
}

function isKnownErrorCode(code: string): code is KnownErrorCode {
  return (KNOWN_ERROR_CODES as readonly string[]).includes(code)
}

/** Presentation for a run error; unknown or missing codes get a safe generic fallback. */
export function describeError(error: RunError | null): ErrorPresentation {
  if (error === null || !isKnownErrorCode(error.code)) return UNKNOWN_ERROR
  return ERROR_PRESENTATION[error.code]
}
