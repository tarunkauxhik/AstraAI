/**
 * Run snapshots for the important states, shaped exactly like GET /runs/{id} responses.
 * Values follow the backend's own test fixtures (backend/tests/fake_llm.py). The `Run`
 * type requires every key, so a field the server does not send cannot sneak in.
 */
import type {
  ChangeSet,
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
  mode: "solve",
  repository: null,
  repository_ref: null,
  existing_tests: null,
  changes: null,
  verification: null,
  first_attempt: null,
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

/** Nobody decided in time: not a failure, so no error, and every piece of evidence stays. */
export const expiredRun = run({
  ...waitingRun,
  status: "expired",
  stage: "expired",
  approval_status: "expired",
  approval_required: false,
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

/** Out of fixes with a failing test: the evidence is the latest attempt's. */
export const outOfFixesRun = run({
  ...executingRun,
  status: "failed",
  stage: "failed",
  generated_tests: GENERATED_TESTS,
  execution_result: FAILED,
  critic_result: CODE_FAILURE_VERDICT,
  revision_count: 2,
  error: {
    code: "revision_budget_exhausted",
    message: "The agent used all of its revision attempts without reaching a verified solution.",
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


// DEVELOP, first slice: the repository at its current commit, and its own tests.

const REPOSITORY_REF = {
  full_name: "octo/sample",
  default_branch: "main",
  commit_sha: "4e1f0c2d9b8a7f6e5d4c3b2a1f0e9d8c7b6a5f4e",
}

export const EXISTING_TESTS_PASSED: ExecutionResult = {
  status: "passed",
  exit_code: 0,
  stdout: "........\n128 passed in 3.10s\n",
  stderr: "",
  duration_ms: 3400,
  tests_passed: 128,
  tests_failed: 0,
  error_type: null,
  output_truncated: false,
}

export const EXISTING_TESTS_FAILING: ExecutionResult = {
  ...EXISTING_TESTS_PASSED,
  status: "failed",
  exit_code: 1,
  stdout:
    "FAILED tests/test_api.py::test_timeout - AssertionError\nFAILED tests/test_api.py::test_retry - AssertionError\n2 failed, 126 passed in 3.10s\n",
  tests_passed: 126,
  tests_failed: 2,
  error_type: "test_failure",
}

const DEVELOP = run({
  task: "Add a --json flag to the report command.",
  mode: "develop",
  repository: "octo/sample",
})

export const developFetchingRun = run({
  ...DEVELOP,
  status: "running",
  stage: "fetching_repository",
})

export const developTestingRun = run({
  ...DEVELOP,
  status: "running",
  stage: "running_existing_tests",
  repository_ref: REPOSITORY_REF,
})

export const developCheckedRun = run({
  ...developTestingRun,
  status: "completed",
  stage: "completed",
  existing_tests: EXISTING_TESTS_PASSED,
})

export const developFailingTestsRun = run({
  ...developCheckedRun,
  existing_tests: EXISTING_TESTS_FAILING,
})

export const developEnvironmentRun = run({
  ...developTestingRun,
  status: "failed",
  stage: "failed",
  existing_tests: {
    ...EXISTING_TESTS_PASSED,
    status: "failed",
    exit_code: 2,
    stdout: "E   ModuleNotFoundError: No module named 'requests'\n1 error in 0.10s\n",
    tests_passed: null,
    tests_failed: null,
    error_type: "environment_error",
  },
  error: {
    code: "environment_unsupported",
    message: "AstraAi couldn't run this repository in its current environment.",
    stage: "running_existing_tests",
  },
})

export const developNotPublicRun = run({
  ...DEVELOP,
  status: "failed",
  stage: "failed",
  error: {
    code: "repository_not_public",
    message:
      "AstraAi couldn't find a public repository at this address. If it's private, GitHub access isn't configured yet.",
    stage: "fetching_repository",
  },
})

// DEVELOP: a change to the repository, as a diff, and the tests run again on it.

export const CHANGES: ChangeSet = {
  files: [
    {
      path: "report/cli.py",
      status: "modified",
      additions: 3,
      deletions: 1,
      diff:
        "--- a/report/cli.py\n+++ b/report/cli.py\n@@ -10,7 +10,9 @@\n def main(argv):\n     parser = build_parser()\n-    args = parser.parse_args(argv)\n+    parser.add_argument(\"--json\", action=\"store_true\")\n+    args = parser.parse_args(argv)\n+    if args.json:\n+        return print_json(args)\n     return print_table(args)\n",
    },
    {
      path: "tests/test_cli.py",
      status: "added",
      additions: 4,
      deletions: 0,
      diff:
        "--- /dev/null\n+++ b/tests/test_cli.py\n@@ -0,0 +1,4 @@\n+from report.cli import main\n+\n+def test_json(capsys):\n+    main([\"--json\"])\n",
    },
  ],
  explanation: "Adds a --json flag that prints the report as JSON, with a test.",
}

export const TESTS_AFTER_PASSED: ExecutionResult = {
  ...EXISTING_TESTS_PASSED,
  stdout: "........\n129 passed in 3.30s\n",
  tests_passed: 129,
}

export const TESTS_AFTER_FAILED: ExecutionResult = {
  ...EXISTING_TESTS_PASSED,
  status: "failed",
  exit_code: 1,
  stdout: "FAILED tests/test_cli.py::test_json - AssertionError: expected JSON\n1 failed, 128 passed in 3.30s\n",
  tests_passed: 128,
  tests_failed: 1,
  error_type: "test_failure",
}

export const developMakingChangesRun = run({
  ...developTestingRun,
  stage: "making_changes",
  existing_tests: EXISTING_TESTS_PASSED,
})

export const developChangedRun = run({
  ...developMakingChangesRun,
  status: "completed",
  stage: "completed",
  changes: CHANGES,
  verification: TESTS_AFTER_PASSED,
  critic_result: PASS_VERDICT,
})

export const developChangedFailingRun = run({
  ...developChangedRun,
  verification: TESTS_AFTER_FAILED,
  critic_result: {
    verdict: "code_failure",
    reason: "The flag is parsed after the arguments are read.",
    code_issue: "--json is added after parse_args runs.",
    test_issue: "",
    recommended_action: "revise_code",
  },
})

export const developChangedNotRunRun = run({
  ...developChangedRun,
  verification: { ...INFRASTRUCTURE_ERROR },
  critic_result: null,
})

// The one repair: the first change's tests failed, AstraAi fixes it, then tests it again.
const FIRST_REVIEW = developChangedFailingRun.critic_result!

export const developFixingRun = run({
  ...developChangedFailingRun,
  status: "running",
  stage: "fixing_issue",
})

export const developRetestingRun = run({
  ...developFixingRun,
  stage: "running_tests",
  verification: null,
  critic_result: null,
  revision_count: 1,
  first_attempt: { verification: TESTS_AFTER_FAILED, review: FIRST_REVIEW },
})

export const developRepairedRun = run({
  ...developRetestingRun,
  status: "completed",
  stage: "completed",
  verification: TESTS_AFTER_PASSED,
  critic_result: PASS_VERDICT,
})

export const developRepairFailedRun = run({
  ...developRepairedRun,
  verification: TESTS_AFTER_FAILED,
  critic_result: FIRST_REVIEW,
})

export const developNoUsefulChangesRun = run({
  ...developMakingChangesRun,
  status: "failed",
  stage: "failed",
  error: {
    code: "no_changes",
    message: "AstraAi didn't find anything to change for this task.",
    stage: "making_changes",
  },
})

export const developNotAppliedRun = run({
  ...developMakingChangesRun,
  status: "failed",
  stage: "failed",
  error: {
    code: "changes_not_applied",
    message: "AstraAi's changes didn't match the repository exactly, so nothing was changed.",
    stage: "making_changes",
  },
})
