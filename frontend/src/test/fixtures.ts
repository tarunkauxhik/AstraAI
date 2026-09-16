/**
 * Run snapshots for the important states, shaped exactly like GET /runs/{id} responses.
 * Values follow the backend's own test fixtures (backend/tests/fake_llm.py). The `Run`
 * type requires every key, so a field the server does not send cannot sneak in.
 */
import type {
  CriticResult,
  ExecutionResult,
  GeneratedCode,
  GeneratedTests,
  Requirements,
  Run,
} from "@/api/types"

const RUN_ID = "3f2b8c1e-5d4a-4e7b-9c1d-2a6f8e0b7c55"
const CREATED = "2026-09-16T11:25:00.000000Z"

export const REQUIREMENTS: Requirements = {
  problem_summary: "Reverse a string.",
  functional_requirements: ["Return the characters of s in reverse order."],
  edge_cases: ["Empty string."],
  constraints: [],
  expected_input: "A string s.",
  expected_output: "The reversed string.",
  relevant_language_requirements: ["Function reverse(s: str) -> str."],
}

export const GENERATED_TESTS: GeneratedTests = {
  interface: "Function reverse(s: string) -> string.",
  comparison: "Exact match.",
  cases: [
    {
      name: "basic_word",
      category: "basic",
      description: "Reverses a typical word.",
      input: 's = "abc"',
      input_generator: "",
      expected_output: '"cba"',
    },
    {
      name: "empty_string",
      category: "empty_or_small",
      description: "An empty string stays empty.",
      input: 's = ""',
      input_generator: "",
      expected_output: '""',
    },
  ],
}

export const GENERATED_CODE: GeneratedCode = {
  language: "python",
  solution_code: "def reverse(s: str) -> str:\n    return s[::-1]\n",
  test_code:
    'import sys\n\nfrom solution import reverse\n\nCASES = [("basic_word", "abc", "cba"), ("empty_string", "", "")]\n\nfailures = 0\nfor name, value, expected in CASES:\n    actual = reverse(value)\n    if actual != expected:\n        print(f"FAIL {name}: expected {expected!r}, got {actual!r}")\n        failures += 1\n\nif failures:\n    sys.exit(1)\nprint(f"PASSED {len(CASES)} tests")\n',
  explanation: "Slicing with a negative step reverses the string.",
}

export const PASSED: ExecutionResult = {
  status: "passed",
  exit_code: 0,
  stdout: "PASSED 2 tests\n",
  stderr: "",
  duration_ms: 842,
  tests_passed: 2,
  tests_failed: 0,
  error_type: null,
  output_truncated: false,
}

export const FAILED: ExecutionResult = {
  status: "failed",
  exit_code: 1,
  stdout: "FAIL basic_word: expected 'cba', got 'abc'\n",
  stderr: "",
  duration_ms: 790,
  tests_passed: null,
  tests_failed: 1,
  error_type: "test_failure",
  output_truncated: false,
}

export const INFRASTRUCTURE_ERROR: ExecutionResult = {
  status: "infrastructure_error",
  exit_code: 125,
  stdout: "",
  stderr: "",
  duration_ms: 120,
  tests_passed: null,
  tests_failed: null,
  error_type: "container_create_failed",
  output_truncated: false,
}

export const PASS_VERDICT: CriticResult = {
  verdict: "pass",
  reason: "Every test passed and the implementation reverses the string as required.",
  code_issue: "",
  test_issue: "",
  recommended_action: "accept",
}

export const CODE_FAILURE_VERDICT: CriticResult = {
  verdict: "code_failure",
  reason: "The tests pass, but they never cover multi-byte characters the task requires.",
  code_issue: "Reversal must operate on characters, not bytes.",
  test_issue: "",
  recommended_action: "revise_code",
}

const BASE: Run = {
  run_id: RUN_ID,
  status: "queued",
  stage: "queued",
  task: "Write a function reverse(s) that returns the string reversed.",
  language: "python",
  created_at: CREATED,
  updated_at: CREATED,
  requirements: null,
  generated_tests: null,
  generated_code: null,
  execution_result: null,
  critic_result: null,
  revision_count: 0,
  execution_retry_count: 0,
  approval_status: null,
  approval_request: null,
  approval_requested_at: null,
  approval_expires_at: null,
  error: null,
  approval_required: false,
}

function run(changes: Partial<Run>): Run {
  return { ...BASE, updated_at: "2026-09-16T11:26:00.000000Z", ...changes }
}

export const queuedRun: Run = BASE

export const generatingRun = run({
  status: "running",
  stage: "generating_code",
  requirements: REQUIREMENTS,
  generated_tests: GENERATED_TESTS,
})

export const executingRun = run({
  status: "running",
  stage: "executing",
  requirements: REQUIREMENTS,
  generated_tests: GENERATED_TESTS,
  generated_code: GENERATED_CODE,
})

/** Mid-review of attempt 1: the critic has not judged this execution yet. */
export const reviewingRun = run({
  ...executingRun,
  stage: "reviewing",
  execution_result: PASSED,
})

/** The critic asked for a code revision even though the tests passed. */
export const revisingRun = run({
  ...executingRun,
  stage: "revising_code",
  execution_result: PASSED,
  critic_result: CODE_FAILURE_VERDICT,
})

/**
 * Attempt 2 executing after that revision. The stored PASSED result and the review both
 * belong to attempt 1 and must never read as the current outcome.
 */
export const reExecutingAfterRevisionRun = run({
  ...revisingRun,
  stage: "executing",
  generated_code: { ...GENERATED_CODE, explanation: "Reverse by characters." },
  revision_count: 1,
})

export const retryingExecutionRun = run({
  ...executingRun,
  stage: "executing",
  execution_result: INFRASTRUCTURE_ERROR,
  critic_result: {
    verdict: "execution_failure",
    reason: "The sandbox could not run the code, so there is no test evidence.",
    code_issue: "",
    test_issue: "",
    recommended_action: "retry_execution",
  },
  execution_retry_count: 1,
})

export const waitingRun = run({
  ...executingRun,
  status: "waiting_for_approval",
  stage: "waiting_for_approval",
  execution_result: PASSED,
  critic_result: PASS_VERDICT,
  approval_status: "pending",
  approval_request: {
    run_id: RUN_ID,
    task: BASE.task,
    language: "python",
    problem_summary: REQUIREMENTS.problem_summary,
    execution_status: "passed",
    tests_passed: 2,
    tests_failed: 0,
    critic_reason: PASS_VERDICT.reason,
    revision_count: 0,
    execution_retry_count: 0,
    approval_means:
      "Approving accepts this verified solution as the run's result. Nothing else happens: no code is published, deployed or sent anywhere.",
  },
  approval_requested_at: "2026-09-16T11:27:00.000000Z",
  approval_expires_at: "2026-09-16T11:37:00.000000Z",
  approval_required: true,
})

export const resumingRun = run({
  ...waitingRun,
  status: "running",
  stage: "resuming",
  approval_status: "approved",
  approval_required: false,
})

export const completedRun = run({
  ...resumingRun,
  status: "completed",
  stage: "completed",
})

export const rejectedRun = run({
  ...waitingRun,
  status: "failed",
  stage: "failed",
  approval_status: "rejected",
  approval_required: false,
  error: {
    code: "approval_rejected",
    message: "A human rejected the verified solution.",
    stage: "waiting_for_approval",
  },
})

export const expiredRun = run({
  ...rejectedRun,
  approval_status: "expired",
  error: {
    code: "approval_expired",
    message: "Nobody approved or rejected the verified solution in time.",
    stage: "waiting_for_approval",
  },
})

export const llmFailedRun = run({
  status: "failed",
  stage: "failed",
  requirements: REQUIREMENTS,
  error: {
    code: "llm_failed",
    message: "The language model request failed or returned unusable output.",
    stage: "generating_tests",
  },
})

export const needsReviewRun = run({
  ...executingRun,
  status: "failed",
  stage: "failed",
  execution_result: FAILED,
  critic_result: {
    verdict: "ambiguous",
    reason: "The critic judged the work a pass, but the tests failed, so that verdict cannot be trusted.",
    code_issue: "",
    test_issue: "",
    recommended_action: "needs_human_review",
  },
  error: {
    code: "needs_human_review",
    message: "The agent could not confirm a correct solution, so the result needs human review.",
    stage: "reviewing",
  },
})

/** Timed out while attempt 2 was executing: the stored pass is attempt 1's. */
export const timedOutDuringReExecutionRun = run({
  ...reExecutingAfterRevisionRun,
  status: "failed",
  stage: "failed",
  error: {
    code: "run_timeout",
    message: "The run took longer than the allowed time and was stopped.",
    stage: "executing",
  },
})

export const sandboxUnavailableRun = run({
  ...retryingExecutionRun,
  status: "failed",
  stage: "failed",
  error: {
    code: "sandbox_unavailable",
    message: "The code could not be executed because the sandbox is unavailable.",
    stage: "executing",
  },
})

export const shutdownWhileQueuedRun = run({
  status: "failed",
  stage: "failed",
  error: {
    code: "shutdown",
    message: "The run was stopped because the service is shutting down.",
    stage: "queued",
  },
})

/** An approved run whose resume failed: failure must win over the approval status. */
export const approvedThenFailedRun = run({
  ...resumingRun,
  status: "failed",
  stage: "failed",
  error: {
    code: "internal_error",
    message: "The run failed because of an internal error.",
    stage: "resuming",
  },
})
