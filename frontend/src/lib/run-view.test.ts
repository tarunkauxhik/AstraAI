import { describe, expect, it } from "vitest"

import { ApiError } from "@/api/client"
import type { Run } from "@/api/types"
import { describeError } from "@/lib/labels"
import {
  criticFreshness,
  describeApprovalError,
  executionAttempt,
  executionFreshness,
  isVerified,
  pageState,
  pollInterval,
  POLL_MS,
  runPhase,
  showApprovalControls,
  timeline,
  verifyActivity,
} from "@/lib/run-view"
import {
  approvedThenFailedRun,
  completedRun,
  executingRun,
  expiredRun,
  generatingRun,
  llmFailedRun,
  needsReviewRun,
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

function states(run: Run) {
  return Object.fromEntries(timeline(run).map((step) => [step.id, step.state]))
}

describe("runPhase precedence", () => {
  it.each([
    ["queued", queuedRun, "queued"],
    ["generating", generatingRun, "working"],
    ["executing", executingRun, "working"],
    ["revising", revisingRun, "working"],
    ["waiting", waitingRun, "awaiting_approval"],
    ["resuming", resumingRun, "resuming"],
    ["completed", completedRun, "completed"],
    ["rejected", rejectedRun, "failed"],
  ] as const)("%s", (_, run, phase) => {
    expect(runPhase(run)).toBe(phase)
  })

  it("lets failed status win over stale approval and child data", () => {
    // Approval request, a passing result and "approved" are all still present.
    expect(runPhase(approvedThenFailedRun)).toBe("failed")
    expect(runPhase(expiredRun)).toBe("failed")
    expect(showApprovalControls(expiredRun)).toBe(false)
  })

  it("does not treat a leftover approval_request as pending", () => {
    expect(rejectedRun.approval_request).not.toBeNull()
    expect(showApprovalControls(rejectedRun)).toBe(false)
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

describe("approval visibility", () => {
  it("shows controls only while the server is waiting", () => {
    expect(showApprovalControls(waitingRun)).toBe(true)
    for (const run of [queuedRun, executingRun, resumingRun, completedRun, rejectedRun]) {
      expect(showApprovalControls(run)).toBe(false)
    }
  })
})

describe("verification", () => {
  it("is verified only once the server accepted the result", () => {
    expect(isVerified(reviewingRun)).toBe(false) // Tests passed, but not yet reviewed.
    expect(isVerified(revisingRun)).toBe(false)
    expect(isVerified(waitingRun)).toBe(true)
    expect(isVerified(completedRun)).toBe(true)
    expect(isVerified(needsReviewRun)).toBe(false)
  })
})

describe("execution attempts", () => {
  it("counts the first run, revisions and retries", () => {
    expect(executionAttempt(executingRun)).toBe(1)
    expect(executionAttempt(reExecutingAfterRevisionRun)).toBe(2)
    expect(executionAttempt(retryingExecutionRun)).toBe(2)
    expect(executionAttempt({ ...completedRun, revision_count: 2, execution_retry_count: 1 })).toBe(4)
  })

  it("describes the current verify activity", () => {
    expect(verifyActivity(executingRun)).toBe("Executing attempt 1")
    expect(verifyActivity(reviewingRun)).toBe("Reviewing attempt 1")
    expect(verifyActivity(revisingRun)).toBe("Revising code (revision 1 of 2)")
    expect(verifyActivity(reExecutingAfterRevisionRun)).toBe("Executing attempt 2")
    expect(verifyActivity(retryingExecutionRun)).toBe("Retrying execution (retry 1 of 1)")
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
    expect(criticFreshness({ ...reviewingRun, critic_result: revisingRun.critic_result })).toBe(
      "stale",
    )
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

  it("treats evidence at rest as current", () => {
    for (const run of [waitingRun, resumingRun, completedRun, rejectedRun]) {
      expect(executionFreshness(run)).toBe("current")
      expect(criticFreshness(run)).toBe("current")
    }
  })
})

describe("timeline", () => {
  it("has nothing active while queued", () => {
    expect(Object.values(states(queuedRun))).toEqual(Array(6).fill("pending"))
  })

  it("follows the current stage", () => {
    expect(states(generatingRun)).toEqual({
      analyze: "done",
      test_plan: "done",
      code: "active",
      verify: "pending",
      approval: "pending",
      result: "pending",
    })
    expect(states(revisingRun).verify).toBe("active")
    const verify = timeline(reExecutingAfterRevisionRun).find((step) => step.id === "verify")
    expect(verify?.detail).toBe("Executing attempt 2")
  })

  it("marks approval active while waiting and done once resuming", () => {
    expect(states(waitingRun).approval).toBe("active")
    expect(states(resumingRun)).toMatchObject({ approval: "done", result: "active" })
  })

  it("marks everything done when completed", () => {
    expect(Object.values(states(completedRun))).toEqual(Array(6).fill("done"))
  })

  it("marks where a failed run stopped, and the result", () => {
    expect(states(llmFailedRun)).toEqual({
      analyze: "done",
      test_plan: "failed",
      code: "pending",
      verify: "pending",
      approval: "pending",
      result: "failed",
    })
    expect(states(rejectedRun)).toMatchObject({ verify: "done", approval: "failed", result: "failed" })
    expect(states(needsReviewRun)).toMatchObject({ verify: "failed", approval: "pending" })
    const result = timeline(rejectedRun).find((step) => step.id === "result")
    expect(result?.detail).toBe("Rejected")
  })

  it("marks only the result when the run failed before starting", () => {
    const failedStates = states(shutdownWhileQueuedRun)
    expect(failedStates.analyze).toBe("pending")
    expect(failedStates.result).toBe("failed")
  })
})

describe("errors", () => {
  it("maps every known code and falls back safely", () => {
    expect(describeError(rejectedRun.error).title).toBe("Rejected")
    expect(describeError(expiredRun.error).title).toBe("Approval expired")
    expect(describeError(sandboxUnavailableRun.error).category).toBe("infrastructure")
    expect(describeError({ code: "brand_new_code", message: "?", stage: "executing" }).title).toBe(
      "Run failed",
    )
    expect(describeError(null).title).toBe("Run failed")
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

  it("stops at terminal states and on 404", () => {
    expect(pollInterval(completedRun, null, idle)).toBe(false)
    expect(pollInterval(rejectedRun, null, idle)).toBe(false)
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
