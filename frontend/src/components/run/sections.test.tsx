// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import type { Run } from "@/api/types"
import { RunLog } from "@/components/run/RunLog"
import { SolutionSection } from "@/components/run/SolutionSection"
import { TestsSection } from "@/components/run/TestsSection"
import {
  completedRun,
  executingRun,
  FAILED,
  generatingRun,
  needsReviewRun,
  outOfFixesRun,
  reExecutingAfterRevisionRun,
  reviewingRun,
  sandboxUnavailableRun,
  timedOutDuringReExecutionRun,
  waitingRun,
} from "@/test/fixtures"
import "@/test/render"

function withExplanation(explanation: string): Run {
  return { ...waitingRun, generated_code: { ...waitingRun.generated_code!, explanation } }
}

const codeCaption = () => screen.getByText("solution.py").parentElement!.textContent

describe("solution", () => {
  it("renders the code with its whitespace intact", () => {
    render(<SolutionSection run={waitingRun} />)

    const code = screen.getByRole("region", { name: "solution.py" })
    expect(within(code).getByText("return s[::-1]", { exact: false }).textContent).toBe("    return s[::-1]")
    expect(screen.getByRole("heading", { name: "Approach" })).toBeTruthy()
  })

  it("carries its own verification status", () => {
    const { unmount } = render(<SolutionSection run={waitingRun} />)
    expect(codeCaption()).toBe("solution.py·Python·Checks passed")
    unmount()

    render(<SolutionSection run={executingRun} />)
    expect(codeCaption()).toContain("Checking…")
  })

  it("never shows an earlier attempt's pass as the new code's status", () => {
    render(<SolutionSection run={reExecutingAfterRevisionRun} />)
    expect(codeCaption()).toContain("Checking…")
    expect(codeCaption()).not.toContain("Checks passed")
  })

  it("says plainly when the final code didn't pass its checks", () => {
    render(<SolutionSection run={outOfFixesRun} />)
    expect(codeCaption()).toContain("Checks not passed")
  })

  it("shows a quiet placeholder only while the solution is being written", () => {
    const { unmount } = render(<SolutionSection run={generatingRun} />)
    expect(screen.getByText("Writing…")).toBeTruthy()
    unmount()

    const { container } = render(<SolutionSection run={{ ...generatingRun, stage: "generating_tests" }} />)
    expect(container.textContent).toBe("")
  })
})

describe("approach note", () => {
  it("renders a markdown-style approach as bullets with inline code", () => {
    render(<SolutionSection run={withExplanation("Sort then sweep:\n- Sort by `start`.\n- Merge overlapping intervals.")} />)

    expect(screen.getByText("Sort then sweep:")).toBeTruthy()
    const items = screen.getAllByRole("listitem").map((item) => item.textContent)
    expect(items).toEqual(["Sort by start.", "Merge overlapping intervals."])
    expect(screen.getByText("start").tagName).toBe("CODE")
  })

  it("renders markdown emphasis instead of showing the asterisks", () => {
    render(
      <SolutionSection
        run={withExplanation("Standard merge:\n1. **Sort**: by `start`.\n2. *Sweep* once; cost is O(n * m).\nAccepts `**kwargs`.")}
      />,
    )

    const approach = screen.getByRole("heading", { name: "Approach" }).parentElement!
    expect(screen.getByText("Sort").tagName).toBe("STRONG")
    expect(screen.getByText("Sweep").tagName).toBe("EM")
    expect(approach.textContent).toContain("1. Sort: by start.")
    expect(approach.textContent).toContain("O(n * m)")
    expect(screen.getByText("**kwargs").tagName).toBe("CODE")
    expect(approach.textContent?.replace("O(n * m)", "").replace("**kwargs", "")).not.toContain("*")
  })

  it("clamps a long note at whole lines, never at a fixed height, until expanded", async () => {
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(200)
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(72)
    render(<SolutionSection run={withExplanation(`Intro paragraph.\n- ${"A long bullet. ".repeat(20)}\nLast line.`)} />)

    const body = screen.getByText("Intro paragraph.").parentElement!
    expect(body.className).toContain("line-clamp-3")
    expect(body.className).not.toMatch(/max-h-/)
    // Clamped visually only: the whole note stays in the document for assistive tech.
    expect(body.textContent).toContain("Last line.")

    await userEvent.click(screen.getByRole("button", { name: "Show more" }))
    expect(body.className).not.toContain("line-clamp")
    expect(screen.getByRole("button", { name: "Show less" }).getAttribute("aria-expanded")).toBe("true")
    vi.restoreAllMocks()
  })

  it("renders a short plain-text note unchanged, with no toggle", () => {
    render(<SolutionSection run={withExplanation("Reverse the string with slicing.")} />)

    const paragraph = screen.getByText("Reverse the string with slicing.")
    expect(paragraph.tagName).toBe("P")
    expect(paragraph.childElementCount).toBe(0)
    expect(screen.queryByRole("button", { name: /Show (more|less)/ })).toBeNull()
  })
})

describe("tests", () => {
  const rows = () => within(screen.getByRole("list", { name: /^Test cases/ })).getAllByRole("listitem")

  it("shows each case's evidence directly, without opening anything", () => {
    render(<TestsSection run={waitingRun} />)

    const [first] = rows()
    expect(first.closest("details")).toBeNull()
    expect(first.textContent).toContain("basic_word")
    expect(first.textContent).toContain("Reverses a typical word.")
    expect(first.textContent).toContain('s = "abc"')
    expect(first.textContent).toContain('"cba"')
    expect(screen.getByText("2 passed")).toBeTruthy()
    expect(rows().map((row) => row.textContent?.includes("passed"))).toEqual([true, true])
  })

  it("never hides a generated input, and keeps its full recipe inspectable", async () => {
    const recipe = "Build nums as [1] * 50000 + [2] * 25000 + [3] * 25000 (100,000 integers)."
    const both = { ...waitingRun.generated_tests!.cases[0], name: "large_k_one", input: "k = 1", input_generator: recipe }
    const onlyGenerated = { ...both, name: "large_only", input: "" }
    const run: Run = { ...waitingRun, generated_tests: { ...waitingRun.generated_tests!, cases: [both, onlyGenerated] } }
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(60)
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(20)
    render(<TestsSection run={run} />)

    const [withLiteral, generatedOnly] = rows()
    // The literal part alone must not read as the whole input.
    expect(withLiteral.textContent).toContain("k = 1")
    expect(withLiteral.textContent).toContain("+ generated input")
    expect(generatedOnly.textContent).toContain("generated input")
    expect(generatedOnly.textContent).not.toContain("(empty)")
    // The complete recipe is on the page, clamped to a line until asked for.
    const recipeLine = within(withLiteral).getByText(recipe).closest("button")!
    expect(recipeLine.getAttribute("aria-expanded")).toBe("false")
    await userEvent.click(recipeLine)
    expect(recipeLine.getAttribute("aria-expanded")).toBe("true")
    vi.restoreAllMocks()
  })

  it("puts the evidence before the description, which is secondary and compact", () => {
    render(<TestsSection run={waitingRun} />)
    const [first] = rows()
    const text = first.textContent ?? ""
    expect(text.indexOf('s = "abc"')).toBeLessThan(text.indexOf("Reverses a typical word."))
    expect(within(first).getByText("Reverses a typical word.").closest("[class*='line-clamp-1']")).not.toBeNull()
  })

  it("drops category badges that repeat what each case says", () => {
    render(<TestsSection run={waitingRun} />)
    expect(screen.queryByText("Empty or small")).toBeNull()
    expect(screen.queryByRole("list", { name: "Coverage by category" })).toBeNull()
  })

  it("shows what a failing case actually returned", () => {
    render(<TestsSection run={needsReviewRun} />)

    const [failing, other] = rows()
    expect(failing.textContent).toContain("failed")
    expect(within(failing).getByText("'abc'")).toBeTruthy()
    // Not reported, so not claimed either way.
    expect(other.textContent).not.toMatch(/passed|failed/)
    expect(screen.getByText("1 failed")).toBeTruthy()
  })

  it("claims nothing from a previous attempt while the tests run again", () => {
    render(<TestsSection run={reExecutingAfterRevisionRun} />)
    expect(screen.getByText("Running again…")).toBeTruthy()
    expect(rows().some((row) => /passed|failed/.test(row.textContent ?? ""))).toBe(false)
  })

  it("keeps the interpretation and the test program one step away", () => {
    render(<TestsSection run={waitingRun} />)

    const interpretation = screen.getByText("How AstraAi read the task").closest("details")!
    expect(interpretation.open).toBe(false)
    expect(within(interpretation).getByText("Return the characters of s in reverse order.")).toBeTruthy()
    const program = screen.getByText("Test program · test_solution.py").closest("details")!
    expect(program.open).toBe(false)
    expect(within(program).getByRole("region", { name: "test_solution.py" })).toBeTruthy()
  })

  it("renders the model's code spans as code, not raw backticks", () => {
    const run: Run = {
      ...waitingRun,
      requirements: { ...waitingRun.requirements!, functional_requirements: ["Return `s[::-1]` exactly."] },
      generated_tests: {
        ...waitingRun.generated_tests!,
        cases: [{ ...waitingRun.generated_tests!.cases[0], description: "Calls `reverse` once." }],
      },
    }
    render(<TestsSection run={run} />)

    expect(screen.getByText("s[::-1]").tagName).toBe("CODE")
    expect(screen.getByText("reverse").tagName).toBe("CODE")
    expect(document.body.textContent).not.toContain("`")
  })

  it("appears while the tests are being written, and not before", () => {
    const { unmount } = render(<TestsSection run={{ ...generatingRun, generated_tests: null, stage: "generating_tests" }} />)
    expect(screen.getByText("Writing…")).toBeTruthy()
    unmount()

    const { container } = render(<TestsSection run={{ ...generatingRun, generated_tests: null, stage: "analyzing" }} />)
    expect(container.textContent).toBe("")
  })
})

describe("run log", () => {
  const renderLog = (run: Run, open = true) => render(<RunLog run={run} open={open} onOpenChange={() => undefined} />)
  const log = () => screen.getByText("Run log").closest("details")!

  it("stays collapsed unless asked to open", () => {
    renderLog(completedRun, false)
    expect(log().open).toBe(false)
  })

  it("holds the test output and the AI review's reasoning", () => {
    renderLog(completedRun)
    expect(within(log()).getByText("Test run")).toBeTruthy()
    expect(within(log()).getByText("Every test passed and the implementation reverses the string as required.")).toBeTruthy()
    expect(within(log()).getByText("stdout")).toBeTruthy()
    expect(within(log()).getByText("Recommended:", { exact: false })).toBeTruthy()
  })

  it("labels an earlier attempt's results as history", () => {
    renderLog(reExecutingAfterRevisionRun)
    expect(within(log()).getByText(/^Attempt 2 is running. The results below are from the previous attempt./)).toBeTruthy()
    expect(within(log()).getAllByText(/previous attempt \(1\)/)).toHaveLength(2)
    expect(within(log()).getByText("Attempts").nextElementSibling?.textContent).toBe("2 (1 fix)")
  })

  it("marks the evidence of a run that stopped mid-attempt as previous", () => {
    renderLog(timedOutDuringReExecutionRun)
    expect(within(log()).getByText(/^Attempt 2 didn't finish./)).toBeTruthy()
  })

  it("keeps error codes and stages here, out of the status", () => {
    renderLog(outOfFixesRun)
    expect(within(log()).getByText("revision_budget_exhausted")).toBeTruthy()
    expect(within(log()).getByText("Stopped while")).toBeTruthy()
    expect(within(log()).getByText("Not carried out: no fixes were left.", { exact: false })).toBeTruthy()
  })

  it("preserves program output exactly", () => {
    const stdout = "FAIL basic_word: expected 'cba', got 'abc'\n    at line 3\n"
    const stderr = 'Traceback (most recent call last):\n  File "test_solution.py", line 9\n'
    renderLog({ ...needsReviewRun, execution_result: { ...FAILED, stdout, stderr, error_type: "runtime_error" } })

    const blocks = [...document.querySelectorAll("pre")].filter((block) => block.getAttribute("aria-label")?.startsWith("std"))
    expect(blocks.map((block) => block.textContent)).toEqual([stdout, stderr])
    expect(screen.getByRole("button", { name: "Copy stderr" })).toBeTruthy()
  })

  it("shows sandbox failures without any diagnostics", () => {
    renderLog(sandboxUnavailableRun)
    expect(screen.getByText(/says nothing about whether the solution is correct/)).toBeTruthy()
    expect(document.querySelectorAll('pre[aria-label^="std"]')).toHaveLength(0)
    expect(screen.queryByText("Exit code")).toBeNull()
  })

  it("names the current attempt", () => {
    renderLog(reviewingRun)
    expect(within(log()).getByText(/attempt 1/)).toBeTruthy()
  })
})
