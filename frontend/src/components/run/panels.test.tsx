// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import type { Run } from "@/api/types"
import { ArtifactPanel } from "@/components/run/ArtifactPanel"
import { CriticPanel } from "@/components/run/CriticPanel"
import { ExecutionPanel } from "@/components/run/ExecutionPanel"
import { OutcomePanel } from "@/components/run/OutcomePanel"
import {
  approvedThenFailedRun,
  completedRun,
  expiredRun,
  FAILED,
  needsReviewRun,
  reExecutingAfterRevisionRun,
  rejectedRun,
  reviewingRun,
  sandboxUnavailableRun,
  timedOutDuringReExecutionRun,
  waitingRun,
} from "@/test/fixtures"
import "@/test/render"

describe("stale attempts", () => {
  it("labels the previous execution and keeps its Passed out of the current view", () => {
    render(<ExecutionPanel run={reExecutingAfterRevisionRun} />)

    expect(screen.getByText("Running attempt 2 in the sandbox…")).toBeTruthy()
    expect(screen.getByText("Attempt 2")).toBeTruthy()
    const history = screen.getByText(/Previous attempt \(1\) · not the current result/).closest("details")!
    expect(history.open).toBe(false)
    // The old pass exists only inside the collapsed history section.
    const passed = screen.getByText("Passed")
    expect(passed.closest("details")).toBe(history)
  })

  it("labels the previous review", () => {
    render(<CriticPanel run={reExecutingAfterRevisionRun} />)

    expect(screen.getByText("Attempt 2 hasn't been reviewed yet.")).toBeTruthy()
    const history = screen.getByText(/Previous attempt \(1\) · not the current verdict/).closest("details")!
    expect(screen.getByText("Code issue", { selector: "span, div" }).closest("details")).toBe(history)
    expect(screen.queryByText(/Recommended:/)).toBeNull()
  })

  it("marks the evidence of a run that stopped mid-attempt as previous", () => {
    render(<ExecutionPanel run={timedOutDuringReExecutionRun} />)

    expect(screen.getByText("Attempt 2 didn't finish before the run stopped.")).toBeTruthy()
    expect(screen.getByText("Passed").closest("details")).not.toBeNull()
  })

  it("shows the current result as current", () => {
    render(<ExecutionPanel run={reviewingRun} />)

    expect(screen.getByText("Attempt 1")).toBeTruthy()
    expect(screen.getByText("Passed").closest("details")).toBeNull()
    expect(screen.queryByText(/Previous attempt/)).toBeNull()
  })
})

describe("execution output", () => {
  it("preserves program output exactly and lets the user copy it", () => {
    const stdout = "FAIL basic_word: expected 'cba', got 'abc'\n    at line 3\n"
    const stderr = "Traceback (most recent call last):\n  File \"test_solution.py\", line 9\n"
    const run: Run = {
      ...needsReviewRun,
      execution_result: { ...FAILED, stdout, stderr, error_type: "runtime_error" },
    }
    render(<ExecutionPanel run={run} />)

    const blocks = document.querySelectorAll("pre")
    expect([...blocks].map((block) => block.textContent)).toEqual([stdout, stderr])
    expect(screen.getByText("Runtime error")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Copy stderr" })).toBeTruthy()
  })

  it("shows infrastructure failures without any diagnostics", () => {
    render(<ExecutionPanel run={sandboxUnavailableRun} />)

    expect(screen.getByText("Sandbox unavailable")).toBeTruthy()
    expect(screen.getByText(/says nothing about whether the code is correct/)).toBeTruthy()
    expect(document.querySelectorAll("pre")).toHaveLength(0)
    expect(screen.queryByText("Exit code")).toBeNull()
  })
})

describe("outcomes", () => {
  const revisionBudgetRun: Run = {
    ...needsReviewRun,
    revision_count: 2,
    error: { code: "revision_budget_exhausted", message: "The agent used all of its revision attempts without reaching a verified solution.", stage: "reviewing" },
  }
  const unknownRun: Run = {
    ...needsReviewRun,
    error: { code: "something_new", message: "A new kind of failure.", stage: "reviewing" },
  }

  it.each([
    ["completed", completedRun, "Completed"],
    ["approval rejected", rejectedRun, "Approval rejected"],
    ["approval expired", expiredRun, "Approval expired"],
    ["sandbox unavailable", sandboxUnavailableRun, "Sandbox unavailable"],
    ["run timeout", timedOutDuringReExecutionRun, "Run timed out"],
    ["revision budget exhausted", revisionBudgetRun, "Revision budget used"],
    ["needs human review", needsReviewRun, "Needs human review"],
    ["internal failure", approvedThenFailedRun, "Internal failure"],
    ["unknown code", unknownRun, "Run failed"],
  ] as const)("%s", (_, run, title) => {
    render(<OutcomePanel run={run} />)
    expect(screen.getByRole("heading", { name: title })).toBeTruthy()
  })

  it("never blames the code for an infrastructure failure", () => {
    render(<OutcomePanel run={sandboxUnavailableRun} />)
    expect(screen.getByText(/execution environment was unavailable/)).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/code is wrong|incorrect/i)
  })

  it("presents a rejection as the user's decision", () => {
    render(<OutcomePanel run={rejectedRun} />)
    expect(screen.getByText(/This was your decision, not a verification failure/)).toBeTruthy()
  })
})

describe("artifacts", () => {
  it("renders the solution with its whitespace intact", () => {
    render(<ArtifactPanel run={waitingRun} />)

    const code = screen.getByRole("region", { name: "solution.py" })
    expect(within(code).getByText("return s[::-1]", { exact: false }).textContent).toBe("    return s[::-1]")
    expect(screen.getByText("Approach")).toBeTruthy()
  })

  it("renders structured test cases, not raw JSON", async () => {
    render(<ArtifactPanel run={waitingRun} />)

    await userEvent.click(screen.getByRole("tab", { name: "Tests" }))

    expect(screen.getByText("Test cases (2)")).toBeTruthy()
    expect(screen.getByText("basic_word")).toBeTruthy()
    expect(screen.getByText("Empty or small")).toBeTruthy()
    expect(screen.getByText('s = "abc"')).toBeTruthy()
    expect(screen.getByText('"cba"')).toBeTruthy()
    expect(screen.getByRole("region", { name: "test_solution.py" })).toBeTruthy()
    expect(document.body.textContent).not.toContain('"expected_output"')
  })

  it("renders the requirements as sections", async () => {
    render(<ArtifactPanel run={waitingRun} />)

    await userEvent.click(screen.getByRole("tab", { name: "Requirements" }))

    expect(screen.getByText("Functional requirements")).toBeTruthy()
    expect(screen.getByText("Return the characters of s in reverse order.")).toBeTruthy()
    expect(screen.getByText("Empty string.")).toBeTruthy()
    expect(screen.getByText("Constraints")).toBeTruthy()
    expect(screen.getByText("None stated.")).toBeTruthy()
    expect(screen.getByText("Python requirements")).toBeTruthy()
  })
})
