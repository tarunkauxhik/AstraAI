/**
 * Pure presentation logic derived from one server Run. The backend is authoritative for
 * every business fact; nothing here decides pass/fail, approval or expiry.
 */
import type { ApiError } from "@/api/client"
import { NETWORK_ERROR_DETAIL } from "@/api/client"
import type { ErrorCode, ExecutionResult, Run, RunRequest, RunStage } from "@/api/types"
import { formatCount } from "@/lib/format"
import { describeFailure, STAGE_ACTIVITY, type FailureKind } from "@/lib/labels"

// ---------------------------------------------------------------------------------------
// Semantic state

export type RunPhase =
  | "queued"
  | "working"
  | "resuming"
  | "awaiting_approval"
  | "completed"
  | "expired"
  | "failed"

/** Top-level status always wins; stage only refines a running run. */
export function runPhase(run: Run): RunPhase {
  switch (run.status) {
    case "failed":
      return "failed"
    case "completed":
      return "completed"
    case "expired":
      return "expired"
    case "waiting_for_approval":
      return "awaiting_approval"
    case "running":
      return run.stage === "resuming" ? "resuming" : "working"
    case "queued":
      return "queued"
  }
}

export function isTerminal(run: Run): boolean {
  return run.status === "completed" || run.status === "failed" || run.status === "expired"
}

/** Still in AstraAi's hands: nothing to decide yet. */
export function isWorking(run: Run): boolean {
  return run.status === "queued" || run.status === "running"
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

/** The execution result only if it describes the code and tests shown now. */
function currentExecution(run: Run): ExecutionResult | null {
  return executionFreshness(run) === "current" ? run.execution_result : null
}

function currentReview(run: Run) {
  return criticFreshness(run) === "current" ? run.critic_result : null
}

// ---------------------------------------------------------------------------------------
// Test evidence

export interface FailedCase {
  /** Case name as the test program printed it. */
  name: string
  /** The whole FAIL line, exactly as printed. */
  line: string
  expected: string | null
  actual: string | null
}

/**
 * The test program must print `FAIL <case>: expected <x>, got <y>` per failure; the backend
 * counts failures from the same lines, so these match its `tests_failed`.
 */
export function failedCases(result: ExecutionResult): FailedCase[] {
  const cases: FailedCase[] = []
  for (const raw of result.stdout.split("\n")) {
    const line = raw.trimEnd()
    const match = /^FAIL (\S+?):?(?: (.*))?$/.exec(line)
    if (!match) continue
    const values = /^expected (.*), got (.*)$/.exec(match[2] ?? "")
    cases.push({ name: match[1], line, expected: values?.[1] ?? null, actual: values?.[2] ?? null })
  }
  return cases
}

function tests(count: number): string {
  return count === 1 ? "test" : "tests"
}

/** One line for a finished test run, e.g. "8 of 8 tests passed". Counts as reported. */
export function testRunSummary(result: ExecutionResult, planned: number | null): string {
  switch (result.status) {
    case "passed":
      return result.tests_passed !== null
        ? `${result.tests_passed} of ${result.tests_passed} ${tests(result.tests_passed)} passed`
        : "The tests passed"
    case "failed": {
      if (result.error_type === "compile_error") return "The tests didn't compile"
      const failed = result.tests_failed ?? 0
      if (failed === 0) return "The tests stopped with an error"
      return planned !== null && planned >= failed
        ? `${failed} of ${planned} ${tests(planned)} failed`
        : `${formatCount(failed, "test")} failed`
    }
    case "timed_out":
      return "The tests hit the time limit"
    case "resource_exceeded":
      return "The tests hit the memory limit"
    case "infrastructure_error":
      return "The tests couldn't run"
  }
}

export type CaseStatus = "passed" | "failed" | null

export interface CaseEvidence {
  status: CaseStatus
  /** What the code returned, when the test program reported it. */
  actual: string | null
}

export interface TestReport {
  /** Short header, e.g. "8 passed", "1 failed", "Running…". */
  summary: string
  /** Evidence per planned case name; missing names have no known status. */
  cases: Map<string, CaseEvidence>
  /** Reported failures whose names match no planned case. */
  unmatched: FailedCase[]
}

/**
 * Per-case evidence from the current execution only. A case is marked passed only when the
 * program reported every planned case passing; a stale result marks nothing.
 */
export function testReport(run: Run): TestReport {
  const planned = run.generated_tests?.cases ?? []
  const cases = new Map<string, CaseEvidence>()
  const result = run.execution_result
  const working = isWorking(run)

  if (result === null) {
    const summary = !working ? "Not run" : run.stage === "executing" ? "Running…" : "Not run yet"
    return { summary, cases, unmatched: [] }
  }
  if (executionFreshness(run) === "stale") {
    return { summary: working ? "Running again…" : "Not finished", cases, unmatched: [] }
  }

  const failures = failedCases(result)
  const names = new Set(planned.map((testCase) => testCase.name))
  let summary: string
  switch (result.status) {
    case "passed":
      summary = result.tests_passed !== null ? `${result.tests_passed} passed` : "Passed"
      if (result.tests_passed === planned.length && result.tests_failed === 0) {
        for (const testCase of planned) cases.set(testCase.name, { status: "passed", actual: null })
      }
      break
    case "failed":
      summary =
        result.error_type === "compile_error"
          ? "Didn't compile"
          : failures.length > 0
            ? `${result.tests_failed ?? failures.length} failed`
            : "Stopped with an error"
      break
    case "timed_out":
      summary = "Time limit reached"
      break
    case "resource_exceeded":
      summary = "Memory limit reached"
      break
    case "infrastructure_error":
      summary = "Couldn't run"
      break
  }
  for (const failure of failures) {
    if (names.has(failure.name)) cases.set(failure.name, { status: "failed", actual: failure.actual })
  }
  return { summary, cases, unmatched: failures.filter((failure) => !names.has(failure.name)) }
}

// ---------------------------------------------------------------------------------------
// The displayed code's verification

export type CodeStatus = "checking" | "verified" | "not_verified"

/**
 * Whether the code on screen passed its checks: the tests passed and the AI review agreed,
 * both on this exact version. Anything stale or still running is "checking".
 */
export function codeStatus(run: Run): CodeStatus {
  const result = currentExecution(run)
  const review = currentReview(run)
  if (result?.status === "passed" && review?.verdict === "pass") return "verified"
  if (isWorking(run) && (result === null || (result.status === "passed" && review === null))) {
    return "checking"
  }
  return "not_verified"
}

export interface Evidence {
  text: string
  /** Raw program output, or the AI review's finding. */
  source: "output" | "review"
}

/** The first thing that shows why verification failed: a failing test, an error, or the review. */
export function failingEvidence(run: Run): Evidence | null {
  const result = currentExecution(run)
  if (result && result.status !== "passed" && result.status !== "infrastructure_error") {
    const failure = failedCases(result)[0]
    if (failure) return { text: clip(failure.line), source: "output" }
    const errors = result.stderr.split("\n").map((line) => line.trim()).filter(Boolean)
    const line =
      errors.find((error) => /error/i.test(error)) ??
      errors.at(-1) ??
      result.stdout.split("\n").map((output) => output.trim()).find(Boolean)
    if (line) return { text: clip(line), source: "output" }
  }
  const review = currentReview(run)
  // "No usable test result" is about the sandbox, not the code, so it isn't evidence.
  if (review && review.verdict !== "pass" && review.verdict !== "execution_failure") {
    const issue = review.code_issue || review.test_issue || review.reason
    if (issue) return { text: clip(issue), source: "review" }
  }
  return null
}

function clip(text: string, max = 240): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text
}

// ---------------------------------------------------------------------------------------
// Work in progress (derived from the current state only; there is no event history)

export type StepId =
  | "analyze"
  | "tests"
  | "solution"
  | "run"
  | "review"
  | "repository"
  | "existing_tests"
  | "understand"
  | "change"
  | "verify"
  | "review_changes"
export type StepState = "done" | "current" | "pending"

export interface WorkStep {
  id: StepId
  state: StepState
  label: string
  /** A second line, e.g. what is being fixed. */
  detail?: string
  /** A finished step that found a problem, e.g. failing tests. */
  problem?: boolean
}

/** The first sentence of a review note: enough to say what is being fixed. */
function firstSentence(text: string): string {
  const sentence = /^.*?[.!?](?=\s|$)/.exec(text.trim())?.[0] ?? text.trim()
  return clip(sentence, 160)
}

/**
 * What AstraAi has done and is doing, in facts that exist on the run. A repair sends its
 * step back to "current" with what is being fixed; attempt numbers stay in the run log.
 */
export function workSteps(run: Run): WorkStep[] {
  if (run.mode === "develop") return developSteps(run)
  const stage = run.stage
  const planned = run.generated_tests?.cases.length ?? null
  const review = run.critic_result
  const result = currentExecution(run)

  const analyze: WorkStep =
    stage === "analyzing"
      ? { id: "analyze", state: "current", label: "Analyzing the task…" }
      : run.requirements
        ? { id: "analyze", state: "done", label: "Task analyzed" }
        : { id: "analyze", state: "pending", label: "Analyze the task" }

  const tests: WorkStep =
    stage === "revising_tests"
      ? {
          id: "tests",
          state: "current",
          label: "Fixing the tests…",
          detail: review ? firstSentence(review.test_issue || review.reason) : undefined,
        }
      : stage === "generating_tests"
        ? { id: "tests", state: "current", label: "Writing tests…" }
        : planned !== null
          ? { id: "tests", state: "done", label: `${formatCount(planned, "test")} written` }
          : { id: "tests", state: "pending", label: "Write tests" }

  const solution: WorkStep =
    stage === "revising_code"
      ? {
          id: "solution",
          state: "current",
          label: "Fixing the solution…",
          detail: review ? firstSentence(review.code_issue || review.reason) : undefined,
        }
      : stage === "generating_code"
        ? { id: "solution", state: "current", label: "Writing the solution…" }
        : run.generated_code
          ? { id: "solution", state: "done", label: "Solution written" }
          : { id: "solution", state: "pending", label: "Write the solution" }

  const runStep: WorkStep =
    stage === "executing"
      ? {
          id: "run",
          state: "current",
          label: executionAttempt(run) > 1 ? "Running the tests again…" : "Running the tests…",
        }
      : stage === "reviewing" && result
        ? {
            id: "run",
            state: "done",
            label: testRunSummary(result, planned),
            problem: result.status !== "passed",
          }
        : { id: "run", state: "pending", label: "Run the tests" }

  const reviewStep: WorkStep =
    stage === "reviewing"
      ? { id: "review", state: "current", label: "Reviewing the solution…" }
      : { id: "review", state: "pending", label: "AI review" }

  return [analyze, tests, solution, runStep, reviewStep]
}

/**
 * A repository's own test suite in one phrase: "128 passed", "126 passed · 2 failed", or
 * that it has none. Nothing here judges whether failing tests are acceptable.
 */
export function existingTestsSummary(result: ExecutionResult): string {
  const passed = result.tests_passed ?? 0
  const failed = result.tests_failed ?? 0
  if (result.tests_passed === null && result.tests_failed === null) return "didn't finish"
  if (passed + failed === 0) return "none found"
  return failed > 0 ? `${passed} passed · ${failed} failed` : `${passed} passed`
}

/** Tests run on a changed repository: they passed, they failed, or they couldn't run. */
export type VerificationOutcome = "passed" | "failed" | "not_run"

/**
 * A sandbox or limit problem is never a test failure. Anything pytest itself reports after
 * the change (a failing test, or code that no longer imports) is: the tests ran before it.
 */
export function verificationOutcome(result: ExecutionResult): VerificationOutcome {
  if (result.status === "passed") return "passed"
  if (result.status === "failed") return "failed"
  return "not_run"
}

/** The tests on the changed repository in one phrase. */
export function verificationSummary(result: ExecutionResult): string {
  switch (verificationOutcome(result)) {
    case "passed":
      return existingTestsSummary(result)
    case "failed":
      return result.tests_passed === null ? "failed before any test ran" : existingTestsSummary(result)
    case "not_run":
      if (result.status === "timed_out") return "didn't finish in time"
      if (result.status === "resource_exceeded") return "hit a resource limit"
      return "couldn't run"
  }
}

function step(id: StepId, current: boolean, done: boolean, labels: [string, string, string]): WorkStep {
  const [doing, finished, todo] = labels
  if (current) return { id, state: "current", label: doing }
  return done ? { id, state: "done", label: finished } : { id, state: "pending", label: todo }
}

/** What a DEVELOP repair is fixing, from the evidence that asked for it. */
function repairDetail(run: Run): string | undefined {
  const review = run.critic_result
  const issue = review?.code_issue || review?.test_issue
  if (issue) return firstSentence(issue)
  const after = run.verification
  return after && verificationOutcome(after) === "failed" ? `Tests: ${verificationSummary(after)}` : undefined
}

/**
 * DEVELOP: read the repository, check its tests, then understand, change, test, review. The
 * one repair sends the change step back to "current"; its tests then run again.
 */
function developSteps(run: Run): WorkStep[] {
  const stage = run.stage
  const existing = run.existing_tests
  const changes = run.changes
  const after = run.verification
  const again = run.first_attempt !== null
  return [
    step("repository", stage === "fetching_repository", run.repository_ref !== null, [
      "Reading the repository…",
      "Repository read",
      "Read the repository",
    ]),
    {
      ...step("existing_tests", stage === "running_existing_tests", existing !== null, [
        "Running the existing tests…",
        existing ? `Existing tests: ${existingTestsSummary(existing)}` : "",
        "Run the existing tests",
      ]),
      problem: existing !== null && existing.status !== "passed",
    },
    step("understand", stage === "understanding_task", changes !== null || stage === "making_changes", [
      "Understanding the task…",
      "Task understood",
      "Understand the task",
    ]),
    stage === "fixing_issue"
      ? { id: "change", state: "current", label: "Fixing an issue…", detail: repairDetail(run) }
      : step("change", stage === "making_changes", changes !== null, [
          "Making changes…",
          changes ? `${formatCount(changes.files.length, "file")} changed` : "",
          "Make the changes",
        ]),
    {
      ...step("verify", stage === "running_tests", after !== null, [
        again ? "Running tests again…" : "Running tests…",
        after ? `Tests: ${verificationSummary(after)}` : "",
        "Run the tests",
      ]),
      problem: after !== null && verificationOutcome(after) !== "passed",
    },
    step("review_changes", stage === "reviewing_changes", false, [
      "Reviewing the changes…",
      "",
      "Review the changes",
    ]),
  ]
}

/** The request that starts this run again, as it was asked for. */
export function runRequest(run: Run): RunRequest {
  return run.mode === "develop" && run.repository !== null
    ? { task: run.task, language: run.language, mode: "develop", repository: run.repository }
    : { task: run.task, language: run.language }
}

// ---------------------------------------------------------------------------------------
// Endings

export type EndingTone = "success" | "attention" | "neutral"
export type EndingAction = "copy" | "new_run" | "run_again" | "edit" | "log"

export interface Ending {
  kind: FailureKind | "accepted" | "expired" | "checked" | "changed" | "needs_review"
  title: string
  description: string
  tone: EndingTone
  actions: EndingAction[]
  /** The run log explains this ending, so it opens by itself. */
  openLog: boolean
}

/**
 * How long AstraAi worked: until it asked for a review, or until the run ended. Null while
 * it is still working (the live clock covers that).
 */
export function workDurationMs(run: Run): number | null {
  const end = run.approval_requested_at ?? (isTerminal(run) ? run.updated_at : null)
  if (end === null) return null
  const span = Date.parse(end) - Date.parse(run.created_at)
  return Number.isNaN(span) ? null : Math.max(0, span)
}

/** Whether the run log has anything to show yet. */
export function hasRunLog(run: Run): boolean {
  return (
    run.execution_result !== null ||
    run.critic_result !== null ||
    run.existing_tests !== null ||
    run.changes !== null ||
    run.error !== null
  )
}

/** Why a run couldn't be verified, from the evidence that stopped it. */
function unverifiedDescription(run: Run): string {
  const result = currentExecution(run)
  const planned = run.generated_tests?.cases.length ?? null
  const fixes = run.revision_count > 0 ? " after the available fixes" : ""
  if (result && result.status !== "passed" && result.status !== "infrastructure_error") {
    return `${testRunSummary(result, planned)}${fixes}.`
  }
  const review = currentReview(run)
  if (result?.status === "passed" && review && review.verdict !== "pass") {
    return run.revision_count > 0
      ? "The tests passed, but the AI review found a problem the fixes didn't resolve."
      : "The tests passed, but the AI review found a problem."
  }
  return "AstraAi couldn't confirm that the solution is correct."
}

/**
 * DEVELOP: changes are ready for review only when the tests passed on them. Tests that still
 * fail, or couldn't run, leave changes that need the person's review. Either way the diff is
 * there to read: passing tests are evidence, not proof, and no review is a guarantee.
 */
function describeDevelopEnding(run: Run): Ending {
  if (run.status === "completed" && run.changes !== null) {
    const after = run.verification
    const files = `${formatCount(run.changes.files.length, "file")} changed`
    const tests = after ? ` · Tests: ${verificationSummary(after)}` : ""
    if (after !== null && verificationOutcome(after) === "passed") {
      return {
        kind: "changed",
        title: "Changes ready for review",
        description: `${files}${tests}`,
        tone: "success",
        actions: ["new_run"],
        openLog: false,
      }
    }
    return {
      kind: "needs_review",
      title: "Changes need your review",
      description: `${files}${tests}`,
      tone: "attention",
      actions: ["run_again", "new_run"],
      openLog: false,
    }
  }
  if (run.status === "completed") {
    // A run from before changes were made: it only checked the repository.
    const result = run.existing_tests
    const clean = result !== null && result.status === "passed" && (result.tests_passed ?? 0) > 0
    return {
      kind: "checked",
      title: "Repository checked",
      description: result ? `Existing tests: ${existingTestsSummary(result)}` : "",
      tone: clean ? "success" : "neutral",
      actions: ["new_run"],
      openLog: false,
    }
  }
  const failure = describeFailure(run.error)
  switch (failure.kind) {
    case "repository":
      return { ...failure, tone: "neutral", actions: ["edit", "new_run"], openLog: false }
    case "environment":
      // The run log says what stopped the tests, so it opens by itself.
      return { ...failure, tone: "attention", actions: ["log", "new_run"], openLog: true }
    case "unchanged":
      // Rewording the task is the most likely way forward.
      return { ...failure, tone: "neutral", actions: ["edit", "run_again"], openLog: false }
    case "sandbox":
      return {
        ...failure,
        description: "AstraAi couldn't start the test sandbox, so the tests haven't run.",
        tone: "neutral",
        actions: ["run_again"],
        openLog: false,
      }
    default:
      return { ...failure, tone: "neutral", actions: ["run_again"], openLog: false }
  }
}

/** How a finished run is presented: one title, one sentence, and the ways forward. */
export function describeEnding(run: Run): Ending {
  if (run.mode === "develop") return describeDevelopEnding(run)
  if (run.status === "completed") {
    return {
      kind: "accepted",
      title: "Accepted",
      description: "All checks passed",
      tone: "success",
      actions: ["copy", "new_run"],
      openLog: false,
    }
  }
  if (run.status === "expired") {
    return {
      kind: "expired",
      title: "Not reviewed in time",
      description:
        "All checks passed, but the review window closed. The solution and its tests are still here.",
      tone: "neutral",
      actions: ["copy", "run_again"],
      openLog: false,
    }
  }
  const failure = describeFailure(run.error)
  switch (failure.kind) {
    case "rejected":
      return { ...failure, tone: "neutral", actions: ["edit", "run_again"], openLog: false }
    case "unverified":
      return {
        ...failure,
        description: unverifiedDescription(run),
        tone: "attention",
        actions: ["run_again", "edit", "log"],
        openLog: true,
      }
    case "timeout":
      return { ...failure, tone: "neutral", actions: ["run_again", "edit"], openLog: false }
    default:
      return { ...failure, tone: "neutral", actions: ["run_again"], openLog: false }
  }
}

/** One short phrase for the page title and the polite live region. */
export function announcement(run: Run): string {
  switch (runPhase(run)) {
    case "queued":
      return "Waiting to start"
    case "working":
      return run.stage === "running_tests" && run.first_attempt !== null
        ? "Running tests again"
        : STAGE_ACTIVITY[run.stage]
    case "resuming":
      return "Accepting"
    case "awaiting_approval":
      return "Ready for review"
    default:
      return describeEnding(run).title
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
}

export function approvalCountdown(expiresAt: string, nowMs: number): Countdown {
  const end = Date.parse(expiresAt)
  const remainingMs = Number.isNaN(end) ? 0 : Math.max(0, end - nowMs)
  const totalSeconds = Math.ceil(remainingMs / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = String(totalSeconds % 60).padStart(2, "0")
  const label =
    hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${seconds}` : `${minutes}:${seconds}`
  return { remainingMs, reached: remainingMs === 0, label }
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
