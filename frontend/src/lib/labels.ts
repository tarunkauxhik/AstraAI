import type {
  CriticVerdict,
  ExecutionStatus,
  KnownErrorCode,
  Language,
  RecommendedAction,
  RunError,
  RunStage,
} from "@/api/types"
import { KNOWN_ERROR_CODES } from "@/api/types"

export const LANGUAGE_LABELS: Record<Language, string> = {
  python: "Python",
  cpp: "C++",
}

/** The files the sandbox runs, named as the backend names them. */
export const FILE_NAMES: Record<Language, { solution: string; tests: string }> = {
  python: { solution: "solution.py", tests: "test_solution.py" },
  cpp: { solution: "solution.cpp", tests: "test_solution.cpp" },
}

/** What AstraAi is doing, in plain words. Internal stage names never reach the user. */
export const STAGE_ACTIVITY: Record<RunStage, string> = {
  queued: "Waiting to start",
  analyzing: "Analyzing the task",
  generating_tests: "Writing tests",
  generating_code: "Writing the solution",
  executing: "Running the tests",
  reviewing: "Reviewing the solution",
  revising_code: "Fixing the solution",
  revising_tests: "Fixing the tests",
  waiting_for_approval: "Ready for review",
  resuming: "Accepting",
  completed: "Accepted",
  failed: "Stopped",
  expired: "Not reviewed in time",
}

// Run log vocabulary: precise, for people who open the log to dig in.

export const EXECUTION_STATUS: Record<ExecutionStatus, string> = {
  passed: "Passed",
  failed: "Failed",
  timed_out: "Time limit reached",
  resource_exceeded: "Resource limit reached",
  // Not the code's fault: the sandbox itself could not run it.
  infrastructure_error: "Sandbox unavailable",
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

export const VERDICTS: Record<CriticVerdict, string> = {
  pass: "No issues found",
  code_failure: "Found a problem in the code",
  test_failure: "Found a problem in the tests",
  execution_failure: "No usable test result",
  ambiguous: "Inconclusive",
}

export const ACTION_LABELS: Record<RecommendedAction, string> = {
  accept: "Accept the solution",
  revise_code: "Fix the code",
  revise_tests: "Fix the tests",
  retry_execution: "Run the tests again",
  needs_human_review: "Hand over for human review",
}

// Endings: a short title and one sentence. Error codes, stages and budgets stay in the log.

export type FailureKind =
  | "rejected"
  | "unverified"
  | "sandbox"
  | "service"
  | "timeout"
  | "interrupted"
  | "internal"

export interface FailureCopy {
  kind: FailureKind
  title: string
  description: string
}

const SANDBOX: FailureCopy = {
  kind: "sandbox",
  title: "Couldn't run the tests",
  description: "AstraAi couldn't start the test sandbox, so the solution hasn't been checked.",
}

const INTERNAL: FailureCopy = {
  kind: "internal",
  title: "Something went wrong",
  description: "AstraAi hit an internal problem and stopped.",
}

export const FAILURES: Record<KnownErrorCode, FailureCopy> = {
  approval_rejected: {
    kind: "rejected",
    title: "Rejected",
    description: "The solution wasn't accepted.",
  },
  needs_human_review: {
    kind: "unverified",
    title: "Couldn't verify",
    description: "AstraAi couldn't confirm that the solution is correct.",
  },
  revision_budget_exhausted: {
    kind: "unverified",
    title: "Couldn't verify",
    description: "AstraAi couldn't get the solution to pass its checks.",
  },
  retry_budget_exhausted: SANDBOX,
  sandbox_unavailable: SANDBOX,
  run_timeout: {
    kind: "timeout",
    title: "Took too long",
    description: "The run hit its time limit before it finished.",
  },
  llm_timeout: {
    kind: "service",
    title: "AI service unavailable",
    description: "The AI service didn't respond in time.",
  },
  llm_failed: {
    kind: "service",
    title: "AI service unavailable",
    description: "The AI service returned an error or an unusable answer.",
  },
  shutdown: {
    kind: "interrupted",
    title: "Interrupted",
    description: "The service restarted during this run.",
  },
  invalid_step_output: INTERNAL,
  internal_error: INTERNAL,
}

function isKnownErrorCode(code: string): code is KnownErrorCode {
  return (KNOWN_ERROR_CODES as readonly string[]).includes(code)
}

/** Presentation for a run error; unknown or missing codes get a safe generic fallback. */
export function describeFailure(error: RunError | null): FailureCopy {
  if (error === null || !isKnownErrorCode(error.code)) return INTERNAL
  return FAILURES[error.code]
}
