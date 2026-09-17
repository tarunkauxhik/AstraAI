// @vitest-environment jsdom
import { useState } from "react"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import type { Run } from "@/api/types"
import { ArtifactPanel, type ArtifactTab } from "@/components/run/ArtifactPanel"
import {
  FAILED,
  generatingRun,
  needsReviewRun,
  reExecutingAfterRevisionRun,
  reviewingRun,
  sandboxUnavailableRun,
  timedOutDuringReExecutionRun,
  waitingRun,
} from "@/test/fixtures"
import "@/test/render"

function Harness({ run, initialTab = "solution" }: { run: Run; initialTab?: ArtifactTab }) {
  const [tab, setTab] = useState<ArtifactTab>(initialTab)
  const [open, setOpen] = useState(initialTab === "details")
  return (
    <ArtifactPanel run={run} tab={tab} onTabChange={setTab} verificationOpen={open} onVerificationOpenChange={setOpen} />
  )
}

describe("tabs", () => {
  it("has three destinations with the solution first", () => {
    render(<Harness run={waitingRun} />)
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Solution", "Tests", "Details"])
    expect(screen.getByRole("tab", { name: "Solution" }).getAttribute("aria-selected")).toBe("true")
  })
})

describe("solution", () => {
  it("renders the code with its whitespace intact and the approach", () => {
    render(<Harness run={waitingRun} />)

    const code = screen.getByRole("region", { name: "solution.py" })
    expect(within(code).getByText("return s[::-1]", { exact: false }).textContent).toBe("    return s[::-1]")
    expect(screen.getByRole("heading", { name: "Approach" })).toBeTruthy()
  })

  it("renders a markdown-style approach as bullets with inline code", () => {
    const run: Run = {
      ...waitingRun,
      generated_code: {
        ...waitingRun.generated_code!,
        explanation: "Sort then sweep:\n- Sort by `start`.\n- Merge overlapping intervals.",
      },
    }
    render(<Harness run={run} />)

    expect(screen.getByText("Sort then sweep:")).toBeTruthy()
    const items = screen.getAllByRole("listitem").map((item) => item.textContent)
    expect(items).toEqual(["Sort by start.", "Merge overlapping intervals."])
    expect(screen.getByText("start").tagName).toBe("CODE")
  })

  it("shows a quiet placeholder while the solution is being produced", () => {
    render(<Harness run={generatingRun} />)
    expect(screen.getByText("AstraAi is working on the solution.")).toBeTruthy()
  })
})

describe("tests", () => {
  it("merges the test plan and test program into one structured view", async () => {
    render(<Harness run={waitingRun} />)

    await userEvent.click(screen.getByRole("tab", { name: "Tests" }))

    expect(screen.getByRole("heading", { name: "Test cases (2)" })).toBeTruthy()
    expect(screen.getByText("How results are compared")).toBeTruthy()
    expect(screen.getByRole("list", { name: "Coverage by category" }).textContent).toContain("Empty or small")
    expect(screen.getByText("basic_word")).toBeTruthy()
    expect(screen.getByText('s = "abc"')).toBeTruthy()
    expect(screen.getByText('"cba"')).toBeTruthy()
    const program = screen.getByText("Test program (test_solution.py)").closest("details")!
    expect(program.open).toBe(false)
    expect(within(program).getByRole("region", { name: "test_solution.py" })).toBeTruthy()
    expect(document.body.textContent).not.toContain('"expected_output"')
  })
})

describe("details", () => {
  it("keeps requirements and verification behind collapsed sections", async () => {
    render(<Harness run={waitingRun} />)

    await userEvent.click(screen.getByRole("tab", { name: "Details" }))

    const requirements = screen.getByText("Requirements").closest("details")!
    expect(requirements.open).toBe(false)
    expect(within(requirements).getByText("Return the characters of s in reverse order.")).toBeTruthy()
    expect(within(requirements).getByText("None stated.")).toBeTruthy()
    expect(screen.getByText("Verification details").closest("details")!.open).toBe(false)
  })

  it("shows current verification evidence as current", () => {
    render(<Harness run={reviewingRun} initialTab="details" />)

    const verification = screen.getByText("Verification details").closest("details")!
    expect(verification.open).toBe(true)
    expect(within(verification).getByText("Passed").closest("details")).toBe(verification)
    expect(within(verification).queryByText(/Previous attempt/)).toBeNull()
  })

  it("puts an earlier attempt's pass behind its own collapsed disclosure", () => {
    render(<Harness run={reExecutingAfterRevisionRun} initialTab="details" />)

    const verification = screen.getByText("Verification details").closest("details")!
    expect(within(verification).getByText(/^Attempt 2 is in progress./)).toBeTruthy()
    const previous = within(verification).getAllByText("Previous attempt (attempt 1)")
    expect(previous.length).toBeGreaterThan(0)
    const passed = within(verification).getByText("Passed")
    expect(passed.closest("details")).toBe(previous[0].closest("details"))
    expect(passed.closest("details")!.open).toBe(false)
    // The previous review's issue is labelled as history too.
    expect(within(verification).getByText("Code issue").closest("details")).not.toBe(verification)
  })

  it("marks the evidence of a run that stopped mid-attempt as previous", () => {
    render(<Harness run={timedOutDuringReExecutionRun} initialTab="details" />)
    expect(screen.getByText(/^Attempt 2 didn't finish before the run stopped./)).toBeTruthy()
  })

  it("preserves program output exactly and lets the user copy it", () => {
    const stdout = "FAIL basic_word: expected 'cba', got 'abc'\n    at line 3\n"
    const stderr = 'Traceback (most recent call last):\n  File "test_solution.py", line 9\n'
    const run: Run = { ...needsReviewRun, execution_result: { ...FAILED, stdout, stderr, error_type: "runtime_error" } }
    render(<Harness run={run} initialTab="details" />)

    const blocks = [...document.querySelectorAll("pre")].filter((block) => block.getAttribute("aria-label")?.startsWith("std"))
    expect(blocks.map((block) => block.textContent)).toEqual([stdout, stderr])
    expect(screen.getByText("Runtime error")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Copy stderr" })).toBeTruthy()
  })

  it("shows infrastructure failures without any diagnostics", () => {
    render(<Harness run={sandboxUnavailableRun} initialTab="details" />)

    expect(screen.getByText(/says nothing about whether the code is correct/)).toBeTruthy()
    expect(document.querySelectorAll('pre[aria-label^="std"]')).toHaveLength(0)
    expect(screen.queryByText("Exit code")).toBeNull()
  })
})
