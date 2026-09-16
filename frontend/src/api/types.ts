/**
 * TypeScript mirror of the FastAPI contract (backend/app/runs.py, state.py, main.py).
 *
 * Hand-maintained on purpose: the generated OpenAPI marks defaulted fields optional even
 * though the server always sends them, and types error codes as plain strings. Every key
 * below is always present in responses; nullable values are explicit.
 */

export type Language = "python" | "cpp"

export type RunStatus =
  | "queued"
  | "running"
  | "waiting_for_approval"
  | "completed"
  | "failed"

export type RunStage =
  | "queued"
  | "analyzing"
  | "generating_tests"
  | "generating_code"
  | "executing"
  | "reviewing"
  | "revising_code"
  | "revising_tests"
  | "waiting_for_approval"
  | "resuming"
  | "completed"
  | "failed"

export type ExecutionStatus =
  | "passed"
  | "failed"
  | "timed_out"
  | "resource_exceeded"
  | "infrastructure_error"

export type CriticVerdict =
  | "pass"
  | "code_failure"
  | "test_failure"
  | "execution_failure"
  | "ambiguous"

export type RecommendedAction =
  | "accept"
  | "revise_code"
  | "revise_tests"
  | "retry_execution"
  | "needs_human_review"

export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired"

export type ApprovalDecision = "approve" | "reject"

export type CaseCategory =
  | "basic"
  | "boundary"
  | "empty_or_small"
  | "duplicates"
  | "negative_or_zero"
  | "performance"
  | "invalid_input"

export const KNOWN_ERROR_CODES = [
  "llm_timeout",
  "llm_failed",
  "invalid_step_output",
  "internal_error",
  "run_timeout",
  "shutdown",
  "sandbox_unavailable",
  "needs_human_review",
  "revision_budget_exhausted",
  "retry_budget_exhausted",
  "approval_rejected",
  "approval_expired",
] as const

export type KnownErrorCode = (typeof KNOWN_ERROR_CODES)[number]

/** The backend types `RunError.code` as a string, so unknown codes must stay possible. */
export type ErrorCode = KnownErrorCode | (string & {})

/** Sandbox error types seen today; `error_type` is a free-form string on the server. */
export type ExecutionErrorType =
  | "compile_error"
  | "test_failure"
  | "runtime_error"
  | "timeout"
  | "out_of_memory"
  | "container_create_failed"
  | "container_start_failed"
  | "container_inspect_failed"
  | "container_attach_failed"
  | (string & {})

export interface Requirements {
  problem_summary: string
  functional_requirements: string[]
  edge_cases: string[]
  constraints: string[]
  expected_input: string
  expected_output: string
  relevant_language_requirements: string[]
}

export interface GeneratedTestCase {
  name: string
  category: CaseCategory
  description: string
  input: string
  input_generator: string
  expected_output: string
}

export interface GeneratedTests {
  interface: string
  comparison: string
  cases: GeneratedTestCase[]
}

export interface GeneratedCode {
  language: Language
  solution_code: string
  test_code: string
  explanation: string
}

export interface ExecutionResult {
  status: ExecutionStatus
  exit_code: number | null
  stdout: string
  stderr: string
  duration_ms: number
  tests_passed: number | null
  tests_failed: number | null
  error_type: ExecutionErrorType | null
  output_truncated: boolean
}

export interface CriticResult {
  verdict: CriticVerdict
  reason: string
  code_issue: string
  test_issue: string
  recommended_action: RecommendedAction
}

export interface ApprovalRequest {
  run_id: string
  task: string
  language: Language
  problem_summary: string
  execution_status: ExecutionStatus
  tests_passed: number | null
  tests_failed: number | null
  critic_reason: string
  revision_count: number
  execution_retry_count: number
  approval_means: string
}

export interface RunError {
  code: ErrorCode
  message: string
  stage: RunStage
}

/** Response of GET /runs/{run_id}. Timestamps are ISO-8601 UTC strings. */
export interface Run {
  run_id: string
  status: RunStatus
  stage: RunStage
  task: string
  language: Language
  created_at: string
  updated_at: string
  requirements: Requirements | null
  generated_tests: GeneratedTests | null
  generated_code: GeneratedCode | null
  execution_result: ExecutionResult | null
  critic_result: CriticResult | null
  revision_count: number
  execution_retry_count: number
  approval_status: ApprovalStatus | null
  /** Set when approval is first requested and never cleared: not a "pending" signal. */
  approval_request: ApprovalRequest | null
  approval_requested_at: string | null
  approval_expires_at: string | null
  error: RunError | null
  /** Computed by the server: exactly `status === "waiting_for_approval"`. */
  approval_required: boolean
}

export interface RunRequest {
  task: string
  language: Language
}

/** Response of POST /runs (status "queued") and POST /runs/{id}/approval. */
export interface RunAccepted {
  run_id: string
  status: RunStatus
}

export interface HealthResponse {
  status: "ok"
  service: string
}

/** Limits enforced by the backend (RunRequest, repair.py). Mirrored for presentation. */
export const TASK_MAX_LENGTH = 20_000
export const MAX_REVISIONS = 2
export const MAX_EXECUTION_RETRIES = 1
