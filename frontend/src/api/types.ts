/**
 * TypeScript mirror of the FastAPI contract (backend/app/runs.py, state.py, main.py).
 *
 * Hand-maintained on purpose: the generated OpenAPI marks defaulted fields optional even
 * though the server always sends them, and types error codes as plain strings. Every key
 * below is always present in responses; nullable values are explicit.
 */

export type Language = "python" | "cpp"

/** solve: write a function from scratch. develop: work in an existing GitHub repository. */
export type Mode = "solve" | "develop"

export type RunStatus =
  | "queued"
  | "running"
  | "waiting_for_approval"
  | "completed"
  | "failed"
  /** Nobody decided in time. Not a failure: the verified solution and evidence stay. */
  | "expired"

export type RunStage =
  | "queued"
  | "analyzing"
  | "generating_tests"
  | "generating_code"
  | "executing"
  | "reviewing"
  | "revising_code"
  | "revising_tests"
  | "fetching_repository"
  | "running_existing_tests"
  | "understanding_task"
  | "making_changes"
  | "running_tests"
  | "reviewing_changes"
  | "fixing_issue"
  | "waiting_for_approval"
  | "resuming"
  | "completed"
  | "failed"
  | "expired"

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
  "repository_not_found",
  "repository_not_public",
  "repository_empty",
  "github_unavailable",
  "repository_too_large",
  "repository_unsupported",
  "not_python",
  "no_pytest_tests",
  "needs_dependencies",
  "environment_unsupported",
  "no_relevant_files",
  "no_changes",
  "changes_not_applied",
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
  | "environment_error"
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
  /** A repository's pytest run: every failing test's id, or null if pytest's summary couldn't be read whole. */
  failed_tests?: string[] | null
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

/** The exact repository version a DEVELOP run works on. Internal: never shown as such. */
export interface RepositoryRef {
  full_name: string
  default_branch: string
  commit_sha: string
}

/** One changed file, as a unified diff against the repository as downloaded. */
export interface FileChange {
  path: string
  status: "modified" | "added"
  additions: number
  deletions: number
  diff: string
}

/** What AstraAi changed in a repository, files sorted by path. */
export interface ChangeSet {
  files: FileChange[]
  explanation: string
}

/** DEVELOP: how the first change fared, once one repair replaced it. */
/** DEVELOP: the tests after the change, compared with before it (by pytest id when `by_id`). */
export interface SuiteComparison {
  by_id: boolean
  /** The tests ran, and nothing fails now that didn't before the change. */
  clean: boolean
  broken: string[]
  new_failing: string[]
  still_failing: string[]
  fixed: string[]
  added: number | null
}

/** How a DEVELOP run ended, decided by the server: tests first, the AI review second. */
export type DevelopOutcome = "ready" | "needs_review" | "not_verified" | "no_changes"

export interface FirstAttempt {
  verification: ExecutionResult
  review: CriticResult
  checks?: SuiteComparison | null
  explanation?: string
  /** What the one repair corrected. */
  fix?: string
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
  mode: Mode
  /** DEVELOP: owner/name as submitted, the version it resolved to, and its own tests. */
  repository: string | null
  repository_ref: RepositoryRef | null
  existing_tests: ExecutionResult | null
  /** DEVELOP: the change as a diff, and the same tests run on the changed repository. */
  changes: ChangeSet | null
  verification: ExecutionResult | null
  /** DEVELOP: the first change's tests and review, when one repair replaced that change. */
  first_attempt: FirstAttempt | null
  checks: SuiteComparison | null
  outcome: DevelopOutcome | null
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
  /** Omitted, a run is SOLVE. DEVELOP needs a repository. */
  mode?: Mode
  repository?: string
}

/** Response of POST /runs (status "queued") and POST /runs/{id}/approval. */
export interface RunAccepted {
  run_id: string
  status: RunStatus
}

/** Response of POST /runs/{id}/approval/extend: a fresh window counted from now. */
export interface ApprovalExtended {
  run_id: string
  approval_expires_at: string
}

export interface HealthResponse {
  status: "ok"
  service: string
}

/**
 * RunRequest.task limit (backend/app/main.py), part of the public contract and mirrored for
 * immediate feedback; the server still validates. Counted in code points, like Python len().
 * Revision and retry budgets are deliberately not mirrored: the API doesn't expose them.
 */
export const TASK_MAX_LENGTH = 20_000
