import type {
  CriticVerdict,
  ExecutionStatus,
  KnownErrorCode,
  Language,
  RecommendedAction,
  RunError,
  RunStage,
  RunStatus,
} from "@/api/types"
import { KNOWN_ERROR_CODES } from "@/api/types"

/** Visual intent. Components map tones to colors and always pair them with text/icons. */
export type Tone = "neutral" | "info" | "success" | "warning" | "danger"

export const LANGUAGE_LABELS: Record<Language, string> = {
  python: "Python",
  cpp: "C++",
}

/** Short run state for page titles and announcements. */
export const STATUS_LABELS: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Working",
  waiting_for_approval: "Ready for approval",
  completed: "Completed",
  failed: "Stopped",
}

/** What AstraAi is doing, in plain words. Internal stage names never reach the user. */
export const STAGE_ACTIVITY: Record<RunStage, string> = {
  queued: "Waiting to start",
  analyzing: "Understanding the problem",
  generating_tests: "Designing tests",
  generating_code: "Building the solution",
  executing: "Verifying the solution",
  reviewing: "Reviewing the result",
  revising_code: "Making a repair",
  revising_tests: "Making a repair",
  waiting_for_approval: "Ready for your approval",
  resuming: "Finishing up",
  completed: "Completed",
  failed: "Stopped",
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
  if (errorType.startsWith("container_")) return "The sandbox couldn't run the code"
  return EXECUTION_ERROR_TYPES[errorType] ?? null
}

export const VERDICTS: Record<CriticVerdict, { label: string; tone: Tone }> = {
  pass: { label: "Review passed", tone: "success" },
  code_failure: { label: "Found a code issue", tone: "danger" },
  test_failure: { label: "Found a test issue", tone: "warning" },
  execution_failure: { label: "No usable test result", tone: "neutral" },
  ambiguous: { label: "Inconclusive", tone: "warning" },
}

export const ACTION_LABELS: Record<RecommendedAction, string> = {
  accept: "Accept the solution",
  revise_code: "Repair the solution",
  revise_tests: "Repair the tests",
  retry_execution: "Run verification again",
  needs_human_review: "Hand over for human review",
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
    title: "Approval rejected",
    description: "You chose not to accept this solution.",
    tone: "neutral",
    category: "decision",
  },
  approval_expired: {
    title: "Approval expired",
    description: "The approval window ended before a decision was made.",
    tone: "warning",
    category: "decision",
  },
  needs_human_review: {
    title: "Needs human review",
    description: "AstraAi couldn't confirm that the solution is correct. Check it yourself before using it.",
    tone: "warning",
    category: "review",
  },
  revision_budget_exhausted: {
    title: "Couldn't complete the repair",
    description: "AstraAi tried to repair the solution but couldn't get it verified.",
    tone: "warning",
    category: "review",
  },
  retry_budget_exhausted: {
    title: "Sandbox unavailable",
    description:
      "AstraAi couldn't run the verification environment. This does not indicate a problem with your code.",
    tone: "neutral",
    category: "infrastructure",
  },
  sandbox_unavailable: {
    title: "Sandbox unavailable",
    description:
      "AstraAi couldn't run the verification environment. This does not indicate a problem with your code.",
    tone: "neutral",
    category: "infrastructure",
  },
  run_timeout: {
    title: "Run timed out",
    description: "AstraAi took longer than allowed and stopped the run.",
    tone: "danger",
    category: "timeout",
  },
  llm_timeout: {
    title: "AI service unavailable",
    description: "The AI service took too long to respond.",
    tone: "danger",
    category: "model",
  },
  llm_failed: {
    title: "AI service unavailable",
    description: "The AI service returned an error or an unusable answer.",
    tone: "danger",
    category: "model",
  },
  shutdown: {
    title: "Interrupted",
    description: "The service restarted while this run was in progress.",
    tone: "neutral",
    category: "interrupted",
  },
  invalid_step_output: {
    title: "Internal failure",
    description: "AstraAi ran into an internal problem and stopped.",
    tone: "danger",
    category: "internal",
  },
  internal_error: {
    title: "Internal failure",
    description: "AstraAi ran into an internal problem and stopped.",
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
