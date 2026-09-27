import { describe, expect, it } from "vitest"

import { ApiError } from "@/api/client"
import type { ExecutionResult, Run } from "@/api/types"
import { formatClock, formatSpan } from "@/lib/format"
import { describeFailure } from "@/lib/labels"
import {
  announcement,
  approvalCountdown,
  codeStatus,
  criticFreshness,
  describeApprovalError,
  describeEnding,
  evidenceAttempt,
  executionAttempt,
  executionFreshness,
  failedCases,
  failingEvidence,
  pageState,
  pollInterval,
  POLL_MS,
  runPhase,
  testReport,
  workDurationMs,
  workSteps,
} from "@/lib/run-view"
import {
  approvedThenFailedRun,
  completedRun,
  executingRun,
  expiredRun,
  FAILED,
  generatingRun,
  llmFailedRun,
  needsReviewRun,
  outOfFixesRun,
  PASSED,
  queuedRun,
  reExecutingAfterRevisionRun,
  rejectedRun,
  resumingRun,
  retryingExecutionRun,
  reviewingRun,
  revisingRun,
  sandboxUnavailableRun,
  shutdownWhileQueuedRun,
  timedOutDuringReExecutionRun,
  waitingRun,
} from "@/test/fixtures"

const httpError = (status: number, detail = "x") =>
  new ApiError({ kind: "http", status, detail })
const networkError = () => new ApiError({ kind: "network", status: 0, detail: "offline" })

describe("runPhase precedence", () => {
  it.each([
    ["queued", queuedRun, "queued"],
    ["generating", generatingRun, "working"],
    ["executing", executingRun, "working"],
    ["revising", revisingRun, "working"],
    ["waiting", waitingRun, "awaiting_approval"],
    ["resuming", resumingRun, "resuming"],
    ["completed", completedRun, "completed"],
    ["expired", expiredRun, "expired"],
    ["rejected", rejectedRun, "failed"],
  ] as const)("%s", (_, run, phase) => {
    expect(runPhase(run)).toBe(phase)
  })

  it("lets failed status win over stale approval and child data", () => {
    // Approval request, a passing result and "approved" are all still present.
    expect(runPhase(approvedThenFailedRun)).toBe("failed")
  })
})

describe("pageState", () => {
  it("puts HTTP problems first", () => {
    expect(pageState(waitingRun, httpError(404))).toEqual({ kind: "not_found" })
    expect(pageState(undefined, networkError()).kind).toBe("unreachable")
    expect(pageState(undefined, null)).toEqual({ kind: "loading" })
  })

  it("keeps a loaded run visible during a transient failure", () => {
    const error = networkError()
    expect(pageState(executingRun, error)).toEqual({
      kind: "run",
      run: executingRun,
      phase: "working",
      connectionError: error,
    })
  })
})

describe("execution attempts", () => {
  it("counts the first run, revisions and retries", () => {
    expect(executionAttempt(executingRun)).toBe(1)
    expect(executionAttempt(reExecutingAfterRevisionRun)).toBe(2)
    expect(executionAttempt(retryingExecutionRun)).toBe(2)
    expect(executionAttempt({ ...completedRun, revision_count: 2, execution_retry_count: 1 })).toBe(4)
  })

  it("attributes stale evidence to the previous attempt", () => {
    expect(evidenceAttempt(reExecutingAfterRevisionRun, "stale")).toBe(1)
    expect(evidenceAttempt(reExecutingAfterRevisionRun, "current")).toBe(2)
    expect(evidenceAttempt(revisingRun, "current")).toBe(1)
    expect(evidenceAttempt(retryingExecutionRun, "stale")).toBe(1)
  })
})

describe("stale evidence", () => {
  it("never presents a previous attempt's pass as current", () => {
    expect(reExecutingAfterRevisionRun.execution_result?.status).toBe("passed")
    expect(executionFreshness(reExecutingAfterRevisionRun)).toBe("stale")
    expect(criticFreshness(reExecutingAfterRevisionRun)).toBe("stale")
  })

  it("marks the old review stale while the new execution is reviewed", () => {
    expect(executionFreshness(reviewingRun)).toBe("current")
    expect(criticFreshness({ ...reviewingRun, critic_result: revisingRun.critic_result })).toBe("stale")
  })

  it("treats the diagnosis behind a revision as current", () => {
    expect(executionFreshness(revisingRun)).toBe("current")
    expect(criticFreshness(revisingRun)).toBe("current")
  })

  it("uses where a failed run stopped", () => {
    expect(executionFreshness(timedOutDuringReExecutionRun)).toBe("stale")
    // Decided after review: the stored evidence is what the decision was based on.
    expect(executionFreshness(needsReviewRun)).toBe("current")
    expect(criticFreshness(needsReviewRun)).toBe("current")
    expect(executionFreshness(sandboxUnavailableRun)).toBe("current")
  })

  it("has no freshness without evidence", () => {
    expect(executionFreshness(generatingRun)).toBeNull()
    expect(criticFreshness(executingRun)).toBeNull()
  })

  it("treats evidence at rest as current, including a review that ran out of time", () => {
    for (const run of [waitingRun, resumingRun, completedRun, rejectedRun, expiredRun]) {
      expect(executionFreshness(run)).toBe("current")
      expect(criticFreshness(run)).toBe("current")
    }
  })
})

describe("work steps", () => {
  const states = (run: Run) => workSteps(run).map((step) => step.state)
  const labels = (run: Run) => workSteps(run).map((step) => step.label)

  it("starts with the whole plan still to do", () => {
    expect(states(queuedRun)).toEqual(["pending", "pending", "pending", "pending", "pending"])
    expect(labels(queuedRun)).toEqual([
      "Analyze the task",
      "Write tests",
      "Write the solution",
      "Run the tests",
      "AI review",
    ])
  })

  it("states facts that exist on the run as each step finishes", () => {
    expect(labels(generatingRun).slice(0, 3)).toEqual([
      "Task analyzed",
      "2 tests written",
      "Writing the solution…",
    ])
    expect(states(generatingRun)).toEqual(["done", "done", "current", "pending", "pending"])
    expect(labels(executingRun)[3]).toBe("Running the tests…")
    expect(labels(reviewingRun).slice(3)).toEqual(["2 of 2 tests passed", "Reviewing the solution…"])
  })

  it("says what a repair is fixing instead of numbering attempts", () => {
    const [, , solution, run, review] = workSteps(revisingRun)
    expect(solution).toMatchObject({
      state: "current",
      label: "Fixing the solution…",
      detail: "Reversal must operate on characters, not bytes.",
    })
    // The later steps will be redone, so they're to do again, not done.
    expect([run.state, review.state]).toEqual(["pending", "pending"])

    const tests = workSteps({ ...revisingRun, stage: "revising_tests" })
    expect(tests[1]).toMatchObject({ state: "current", label: "Fixing the tests…" })
    // A test fix leaves the solution as it was.
    expect(tests[2].state).toBe("done")
  })

  it("marks a repeated test run without showing the stale result", () => {
    expect(labels(reExecutingAfterRevisionRun)[3]).toBe("Running the tests again…")
    expect(labels(retryingExecutionRun)[3]).toBe("Running the tests again…")
    expect(labels(reExecutingAfterRevisionRun).join(" ")).not.toMatch(/passed/)
  })

  it("flags a finished test run that failed", () => {
    const run = { ...reviewingRun, execution_result: FAILED }
    expect(workSteps(run)[3]).toMatchObject({ state: "done", label: "1 of 2 tests failed", problem: true })
  })

  it("never exposes internal attempts, budgets or stage names", () => {
    const runs = [queuedRun, generatingRun, executingRun, reviewingRun, revisingRun, reExecutingAfterRevisionRun, retryingExecutionRun]
    for (const run of runs) {
      const text = workSteps(run)
        .map((step) => `${step.label} ${step.detail ?? ""}`)
        .join(" ")
      expect(text).not.toMatch(/attempt|revision|retry|budget|generating|executing|Understand|Verify/i)
    }
  })
})

describe("test evidence", () => {
  const failing = (stdout: string, extra: Partial<ExecutionResult> = {}): Run => ({
    ...needsReviewRun,
    execution_result: { ...FAILED, stdout, ...extra },
  })

  it("parses FAIL lines the way the backend counts them", () => {
    const cases = failedCases({
      ...FAILED,
      stdout: "FAIL basic_word: expected 'cba', got 'abc'\r\nnoise\nFAIL empty_string\n",
    })
    expect(cases).toEqual([
      { name: "basic_word", line: "FAIL basic_word: expected 'cba', got 'abc'", expected: "'cba'", actual: "'abc'" },
      { name: "empty_string", line: "FAIL empty_string", expected: null, actual: null },
    ])
  })

  it("marks every case passed only when the program reported them all", () => {
    const report = testReport(waitingRun)
    expect(report.summary).toBe("2 passed")
    expect([...report.cases.values()].map((evidence) => evidence.status)).toEqual(["passed", "passed"])

    // One planned case never reported: no per-case claims at all.
    const partial = testReport({ ...waitingRun, execution_result: { ...PASSED, tests_passed: 1 } })
    expect(partial.summary).toBe("1 passed")
    expect(partial.cases.size).toBe(0)
  })

  it("shows the failing case with what the code actually returned", () => {
    const report = testReport(needsReviewRun)
    expect(report.summary).toBe("1 failed")
    expect(report.cases.get("basic_word")).toEqual({ status: "failed", actual: "'abc'" })
    // Unreported cases are unknown, not assumed to pass.
    expect(report.cases.get("empty_string")).toBeUndefined()
  })

  it("keeps failures for unknown case names instead of dropping them", () => {
    const report = testReport(failing("FAIL mystery_case: expected 1, got 2\n"))
    expect(report.unmatched.map((failure) => failure.name)).toEqual(["mystery_case"])
  })

  it("claims nothing from a stale or missing result", () => {
    expect(testReport(reExecutingAfterRevisionRun)).toMatchObject({ summary: "Running again…" })
    expect(testReport(reExecutingAfterRevisionRun).cases.size).toBe(0)
    expect(testReport(generatingRun).summary).toBe("Not run yet")
    expect(testReport({ ...executingRun, execution_result: null }).summary).toBe("Running…")
    expect(testReport(timedOutDuringReExecutionRun).summary).toBe("Not finished")
  })

  it("names results that aren't pass or fail", () => {
    expect(testReport(failing("", { error_type: "compile_error", tests_failed: null })).summary).toBe("Didn't compile")
    expect(testReport(failing("", { error_type: "runtime_error", tests_failed: null })).summary).toBe(
      "Stopped with an error",
    )
    expect(testReport(sandboxUnavailableRun).summary).toBe("Couldn't run")
  })
})

describe("code status", () => {
  it("is verified only when this exact code passed its tests and the review", () => {
    for (const run of [waitingRun, resumingRun, completedRun, rejectedRun, expiredRun, approvedThenFailedRun]) {
      expect(codeStatus(run)).toBe("verified")
    }
  })

  it("is checking while the current code has no verdict yet", () => {
    expect(codeStatus(executingRun)).toBe("checking")
    expect(codeStatus(reviewingRun)).toBe("checking")
    // A previous attempt's pass says nothing about the new code.
    expect(codeStatus(reExecutingAfterRevisionRun)).toBe("checking")
  })

  it("is not verified when the checks failed or never ran", () => {
    for (const run of [revisingRun, needsReviewRun, outOfFixesRun, sandboxUnavailableRun, timedOutDuringReExecutionRun]) {
      expect(codeStatus(run)).toBe("not_verified")
    }
  })
})

describe("failing evidence", () => {
  it("leads with the first failing test line", () => {
    expect(failingEvidence(needsReviewRun)).toEqual({
      text: "FAIL basic_word: expected 'cba', got 'abc'",
      source: "output",
    })
  })

  it("falls back to the error line, then to the AI review", () => {
    const crashed: Run = {
      ...needsReviewRun,
      execution_result: {
        ...FAILED,
        stdout: "",
        tests_failed: null,
        error_type: "runtime_error",
        stderr: 'Traceback (most recent call last):\n  File "test_solution.py", line 9\nZeroDivisionError: division by zero\n',
      },
    }
    expect(failingEvidence(crashed)?.text).toBe("ZeroDivisionError: division by zero")

    const reviewOnly: Run = { ...outOfFixesRun, execution_result: PASSED }
    expect(failingEvidence(reviewOnly)).toEqual({
      text: "Reversal must operate on characters, not bytes.",
      source: "review",
    })
  })

  it("has nothing to say about passing or sandbox-less runs", () => {
    expect(failingEvidence(waitingRun)).toBeNull()
    expect(failingEvidence(sandboxUnavailableRun)).toBeNull()
  })
})

describe("endings", () => {
  it("accepted: copy the solution or start again", () => {
    expect(describeEnding(completedRun)).toMatchObject({
      title: "Accepted",
      description: "All checks passed",
      tone: "success",
      actions: ["copy", "new_run"],
    })
  })

  it("a review that ran out of time is neutral and keeps its proof", () => {
    const ending = describeEnding(expiredRun)
    expect(ending).toMatchObject({ title: "Not reviewed in time", tone: "neutral", actions: ["copy", "run_again"] })
    expect(ending.description).toContain("All checks passed")
  })

  it("rejected: neutral, and easy to try again differently", () => {
    expect(describeEnding(rejectedRun)).toMatchObject({
      title: "Rejected",
      description: "The solution wasn't accepted.",
      tone: "neutral",
      actions: ["edit", "run_again"],
    })
  })

  it("couldn't verify: says what failed and opens the log", () => {
    expect(describeEnding(outOfFixesRun)).toMatchObject({
      title: "Couldn't verify",
      description: "1 of 2 tests failed after the available fixes.",
      tone: "attention",
      actions: ["run_again", "edit", "log"],
      openLog: true,
    })
    expect(describeEnding(needsReviewRun).description).toBe("1 of 2 tests failed.")
    expect(describeEnding({ ...outOfFixesRun, execution_result: PASSED }).description).toBe(
      "The tests passed, but the AI review found a problem the fixes didn't resolve.",
    )
  })

  it("infrastructure and service failures are neutral and offer another run", () => {
    expect(describeEnding(sandboxUnavailableRun)).toMatchObject({
      title: "Couldn't run the tests",
      tone: "neutral",
      actions: ["run_again"],
    })
    expect(describeEnding(llmFailedRun)).toMatchObject({ title: "AI service unavailable", tone: "neutral" })
    expect(describeEnding(timedOutDuringReExecutionRun)).toMatchObject({
      title: "Took too long",
      actions: ["run_again", "edit"],
    })
    expect(describeEnding(shutdownWhileQueuedRun).title).toBe("Interrupted")
  })

  it("never shows error codes or internal wording, and falls back safely", () => {
    const failed = [rejectedRun, needsReviewRun, outOfFixesRun, sandboxUnavailableRun, llmFailedRun, timedOutDuringReExecutionRun, shutdownWhileQueuedRun, approvedThenFailedRun]
    for (const run of failed) {
      const { title, description } = describeEnding(run)
      expect(`${title} ${description}`).not.toMatch(/_|budget|revision|retry|Stopped while|attempt/i)
    }
    const unknown = { ...llmFailedRun, error: { code: "brand_new_code", message: "?", stage: "executing" as const } }
    expect(describeEnding(unknown).title).toBe("Something went wrong")
    expect(describeFailure(null).title).toBe("Something went wrong")
  })

  it("titles the page by what's happening now", () => {
    expect(announcement(queuedRun)).toBe("Waiting to start")
    expect(announcement(revisingRun)).toBe("Fixing the solution")
    expect(announcement(waitingRun)).toBe("Ready for review")
    expect(announcement(expiredRun)).toBe("Not reviewed in time")
    expect(announcement(outOfFixesRun)).toBe("Couldn't verify")
  })
})

describe("durations", () => {
  it("counts AstraAi's work until it asked for a review, or until the run ended", () => {
    // Created 11:25, review requested 11:27: waiting for a human never counts.
    expect(workDurationMs(completedRun)).toBe(120_000)
    expect(workDurationMs(llmFailedRun)).toBe(60_000)
    expect(workDurationMs(executingRun)).toBeNull()
  })

  it("formats a live clock and a finished span", () => {
    expect([formatClock(7_000), formatClock(72_000), formatClock(3_723_000)]).toEqual(["0:07", "1:12", "1:02:03"])
    expect([formatSpan(42_000), formatSpan(102_000), formatSpan(3_780_000)]).toEqual(["42s", "1m 42s", "1h 03m"])
  })
})

describe("pollInterval", () => {
  const idle = { hidden: false, boosted: false, failures: 0 }

  it("polls by phase", () => {
    expect(pollInterval(queuedRun, null, idle)).toBe(POLL_MS.queued)
    expect(pollInterval(executingRun, null, idle)).toBe(POLL_MS.working)
    expect(pollInterval(waitingRun, null, idle)).toBe(POLL_MS.awaitingApproval)
    expect(pollInterval(resumingRun, null, idle)).toBe(POLL_MS.fast)
  })

  it("stops at every ending and on 404", () => {
    for (const run of [completedRun, rejectedRun, expiredRun]) expect(pollInterval(run, null, idle)).toBe(false)
    expect(pollInterval(waitingRun, httpError(404), idle)).toBe(false)
  })

  it("speeds up after a decision and slows down when hidden", () => {
    expect(pollInterval(waitingRun, null, { ...idle, boosted: true })).toBe(POLL_MS.fast)
    expect(pollInterval(executingRun, null, { ...idle, hidden: true })).toBe(POLL_MS.hidden)
  })

  it("backs off on consecutive failures, bounded", () => {
    const at = (failures: number) => pollInterval(executingRun, networkError(), { ...idle, failures })
    expect([at(1), at(2), at(3), at(4), at(5), at(9)]).toEqual([2000, 4000, 8000, 16000, 30000, 30000])
  })
})

describe("describeApprovalError", () => {
  it("never implies the decision succeeded", () => {
    expect(describeApprovalError(httpError(409, "The approval request has expired."))).toBe(
      "The approval request has expired.",
    )
    expect(
      describeApprovalError(new ApiError({ kind: "http", status: 429, detail: "", retryAfterSeconds: 30 })),
    ).toContain("still waiting; try again in 30 seconds")
    expect(describeApprovalError(networkError())).toContain("whether your decision was recorded")
    expect(describeApprovalError(httpError(503))).toContain("couldn't be recorded")
  })
})

describe("approvalCountdown", () => {
  const expires = "2026-09-16T11:37:00.000Z"
  const at = (iso: string) => approvalCountdown(expires, Date.parse(iso))

  it("counts down against the given clock", () => {
    expect(at("2026-09-16T11:27:00.000Z")).toMatchObject({ label: "10:00", reached: false })
    expect(at("2026-09-16T11:36:30.400Z")).toMatchObject({ label: "0:30", reached: false })
  })

  it("reaches zero without going negative", () => {
    expect(at("2026-09-16T11:37:00.000Z")).toMatchObject({ remainingMs: 0, reached: true, label: "0:00" })
    expect(at("2026-09-16T12:00:00.000Z")).toMatchObject({ remainingMs: 0, reached: true })
  })

  it("formats long windows with hours", () => {
    expect(at("2026-09-16T09:36:59.000Z").label).toBe("2:00:01")
  })
})
