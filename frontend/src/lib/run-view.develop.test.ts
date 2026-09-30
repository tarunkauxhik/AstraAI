import { describe, expect, it } from "vitest"

import type { Run } from "@/api/types"
import {
  announcement,
  describeEnding,
  existingTestsSummary,
  hasRunLog,
  runRequest,
  workSteps,
} from "@/lib/run-view"
import {
  completedRun,
  developCheckedRun,
  developEnvironmentRun,
  developFailingTestsRun,
  developFetchingRun,
  developNotPublicRun,
  developTestingRun,
  EXISTING_TESTS_PASSED,
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

  it("gets the repository, then runs its existing tests", () => {
    expect(steps(developFetchingRun)).toEqual([
      ["current", "Getting the repository…"],
      ["pending", "Run the existing tests"],
    ])
    expect(steps(developTestingRun)).toEqual([
      ["done", "Repository ready"],
      ["current", "Running the existing tests…"],
    ])
    expect(announcement(developTestingRun)).toBe("Running the existing tests")
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
