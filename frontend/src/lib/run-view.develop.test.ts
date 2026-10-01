import { describe, expect, it } from "vitest"

import type { Run } from "@/api/types"
import {
  announcement,
  repairNote,
  describeEnding,
  existingTestsSummary,
  hasRunLog,
  runRequest,
  verificationOutcome,
  verificationSummary,
  workSteps,
} from "@/lib/run-view"
import {
  completedRun,
  developChangedFailingRun,
  developChangedNotRunRun,
  developChangedRun,
  developCheckedRun,
  developEnvironmentRun,
  developFailingTestsRun,
  developFetchingRun,
  developFixingRun,
  developMakingChangesRun,
  developRepairedRun,
  developRepairFailedRun,
  developRetestingRun,
  developNoChangesNeededRun,
  developAlreadyFailingRun,
  developBrokeExistingRun,
  developReviewFlaggedRun,
  developTimedOutRun,
  comparison,
  CHANGES,
  developNotAppliedRun,
  developNotPublicRun,
  developTestingRun,
  EXISTING_TESTS_PASSED,
  INFRASTRUCTURE_ERROR,
  TESTS_AFTER_FAILED,
  TESTS_AFTER_PASSED,
} from "@/test/fixtures"

describe("existing tests in one phrase", () => {
  it.each([
    [{ tests_passed: 128, tests_failed: 0 }, "128 passed"],
    [{ tests_passed: 126, tests_failed: 2 }, "126 passed · 2 failed"],
    [{ tests_passed: 0, tests_failed: 3 }, "0 passed · 3 failed"],
    [{ tests_passed: 0, tests_failed: 0 }, "none found"],
    [{ tests_passed: null, tests_failed: null }, "didn't finish"],
  ])("%j reads %s", (counts, phrase) => {
    expect(existingTestsSummary({ ...EXISTING_TESTS_PASSED, ...counts })).toBe(phrase)
  })
})

describe("develop work steps", () => {
  const steps = (run: Run) => workSteps(run).map((step) => [step.state, step.label])

  it("reads the repository, checks its tests, then understands, changes, tests and reviews", () => {
    expect(steps(developFetchingRun)).toEqual([
      ["current", "Checking the repository…"],
      ["pending", "Run the existing tests"],
      ["pending", "Understand the task"],
      ["pending", "Make the changes"],
      ["pending", "Run the tests"],
      ["pending", "Review the changes"],
    ])
    expect(steps(developMakingChangesRun)).toEqual([
      ["done", "Repository ready"],
      ["done", "Existing tests: 128 passed"],
      ["done", "Task understood"],
      ["current", "Making changes…"],
      ["pending", "Run the tests"],
      ["pending", "Review the changes"],
    ])
    expect(announcement(developTestingRun)).toBe("Running the existing tests")
    expect(announcement(developMakingChangesRun)).toBe("Making changes")
  })

  it("never names a step with internal vocabulary", () => {
    const labels = [developFetchingRun, developTestingRun, developMakingChangesRun]
      .flatMap((run) => workSteps(run).map((step) => step.label))
      .join(" ")

    expect(labels).not.toMatch(/baseline|sha|commit|workspace|context|graph|node|budget|plan/i)
  })
})

describe("verification after the change", () => {
  it.each([
    [TESTS_AFTER_PASSED, "passed", "129 passed"],
    [TESTS_AFTER_FAILED, "failed", "128 passed · 1 failed"],
    [
      { ...TESTS_AFTER_FAILED, exit_code: 2, error_type: "environment_error", tests_passed: null, tests_failed: null },
      "failed",
      "failed before any test ran",
    ],
    [{ ...INFRASTRUCTURE_ERROR }, "not_run", "couldn't run"],
    [{ ...TESTS_AFTER_PASSED, status: "timed_out" as const }, "not_run", "didn't finish in time"],
    [{ ...TESTS_AFTER_PASSED, status: "resource_exceeded" as const }, "not_run", "hit a resource limit"],
  ])("%#: reads as %s, %s", (result, outcome, phrase) => {
    expect(verificationOutcome(result)).toBe(outcome)
    expect(verificationSummary(result)).toBe(phrase)
  })
})

describe("outcomes", () => {
  it("ready: what AstraAi did, then the patch; no claim beyond the evidence", () => {
    const ending = describeEnding(developChangedRun)

    expect([ending.title, ending.tone, ending.detail]).toEqual(["Changes ready for review", "success", undefined])
    expect(ending.summary).toBe(CHANGES.explanation)
    expect(ending.actions).toEqual(["patch"])
    expect(JSON.stringify(ending)).not.toMatch(/verified|confiden|score/i)
  })

  it("tests that already failed before the change don't stop it being ready", () => {
    expect(describeEnding(developAlreadyFailingRun).title).toBe("Changes ready for review")
  })

  it.each([
    [developChangedFailingRun, /^Its new test fails: test_json\.$/],
    [developBrokeExistingRun, /^1 test that passed before fails now: test_columns\.$/],
    [developReviewFlaggedRun, /^AI review flagged something to check: --json is added after parse_args runs\.$/],
  ])("needs your review, saying why: %#", (run, reason) => {
    const ending = describeEnding(run)

    expect([ending.title, ending.tone]).toEqual(["Changes need your review", "attention"])
    expect(ending.detail).toMatch(reason)
    expect(ending.actions).toEqual(["patch", "run_again"])
    expect(announcement(run)).toBe("Changes need your review")
  })

  it.each([
    [developChangedNotRunRun, "AstraAi couldn't start the tests"],
    [developTimedOutRun, "The tests didn't finish within the time limit"],
  ])("couldn't verify is never a test failure: %#", (run, reason) => {
    const ending = describeEnding(run)

    expect(ending.title).toBe("AstraAi couldn't verify the changes")
    expect(ending.detail).toContain(reason)
    expect(ending.detail).not.toMatch(/fail/)
  })

  it("no changes needed, with AstraAi's reason", () => {
    const ending = describeEnding(developNoChangesNeededRun)

    expect([ending.title, ending.summary]).toEqual([
      "No changes needed",
      "The report command already has a --json flag, with tests, so nothing needs to change.",
    ])
    expect(ending.actions).toEqual(["edit"])
  })

  it("changes that couldn't be made are not called unnecessary", () => {
    const ending = describeEnding(developNotAppliedRun)

    expect([ending.title, ending.actions]).toEqual(["No changes made", ["edit", "run_again"]])
  })

  it("a run from before the server decided outcomes falls back to its final tests", () => {
    const legacy = { ...developChangedFailingRun, outcome: null, checks: null }

    expect(describeEnding(legacy).title).toBe("Changes need your review")
    expect(describeEnding({ ...developChangedRun, outcome: null, checks: null }).title).toBe(
      "Changes ready for review",
    )
  })
})

describe("the repair, after the fact", () => {
  it("is one line about what caught the first change, never an attempt number", () => {
    expect(repairNote(developRepairedRun)).toBe(
      "AstraAi found a failing test after its first change and corrected it before the final test run.",
    )
    expect(repairNote(developChangedRun)).toBeNull()
    const caughtByReview = {
      ...developRepairedRun,
      first_attempt: { ...developRepairedRun.first_attempt!, checks: comparison() },
    }
    expect(repairNote(caughtByReview)).toMatch(/^The AI review flagged a problem/)
  })

  it("keeps the summary of the final change, not the repair's story", () => {
    expect(describeEnding(developRepairedRun).summary).toBe(developRepairedRun.changes!.explanation)
  })
})

describe("the one repair", () => {
  it("sends the change step back with what is being fixed", () => {
    const steps = workSteps(developFixingRun)
    const change = steps.find((step) => step.id === "change")!

    expect([change.state, change.label, change.detail]).toEqual([
      "current",
      "Fixing an issue…",
      "--json is added after parse_args runs.",
    ])
    expect(announcement(developFixingRun)).toBe("Fixing an issue")
  })

  it("then runs the tests again", () => {
    const verify = workSteps(developRetestingRun).find((step) => step.id === "verify")!

    expect([verify.state, verify.label]).toEqual(["current", "Running tests again…"])
    expect(announcement(developRetestingRun)).toBe("Running tests again")
  })

  it("never shows a counter, a budget or an attempt number", () => {
    const text = JSON.stringify([
      workSteps(developFixingRun),
      workSteps(developRetestingRun),
      describeEnding(developRepairedRun),
      describeEnding(developRepairFailedRun),
    ])

    expect(text).not.toMatch(/attempt|revision|budget|\b[12]\/[12]\b/i)
  })
})

describe("develop endings", () => {
  it("a clean check is a success with the count", () => {
    const ending = describeEnding(developCheckedRun)

    expect([ending.title, ending.description, ending.tone]).toEqual([
      "Repository checked",
      "Existing tests: 128 passed",
      "success",
    ])
    expect(ending.actions).toEqual(["new_run"])
  })

  it("failing existing tests are reported, not judged", () => {
    const ending = describeEnding(developFailingTestsRun)

    expect([ending.title, ending.description, ending.tone]).toEqual([
      "Repository checked",
      "Existing tests: 126 passed · 2 failed",
      "neutral",
    ])
  })

  it("tests that couldn't run open the run log", () => {
    const ending = describeEnding(developEnvironmentRun)

    expect(ending.title).toBe("Couldn't run the tests")
    expect(ending.openLog).toBe(true)
    expect(ending.actions).toEqual(["log", "new_run"])
  })

  it("an unreachable repository offers to fix the address", () => {
    expect(describeEnding(developNotPublicRun).actions).toEqual(["edit", "new_run"])
  })

  it("the log has something to show once the tests ran", () => {
    expect(hasRunLog(developFetchingRun)).toBe(false)
    expect(hasRunLog(developCheckedRun)).toBe(true)
  })
})

describe("run again", () => {
  it("repeats a develop run with its repository, and a solve run as before", () => {
    expect(runRequest(developCheckedRun)).toEqual({
      task: developCheckedRun.task,
      language: "python",
      mode: "develop",
      repository: "octo/sample",
    })
    expect(runRequest(completedRun)).toEqual({ task: completedRun.task, language: "python" })
  })
})
