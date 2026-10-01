// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { createMemoryRouter, RouterProvider } from "react-router"
import { afterEach, describe, expect, it } from "vitest"

import type { Run } from "@/api/types"
import { NewRunPage } from "@/routes/NewRunPage"
import { RunPage } from "@/routes/RunPage"
import {
  CHANGES,
  developAlreadyFailingRun,
  developBrokeExistingRun,
  developChangedFailingRun,
  developChangedNotRunRun,
  developChangedRun,
  developCheckedRun,
  developEnvironmentRun,
  developFailingTestsRun,
  developFixingRun,
  developNoChangesNeededRun,
  developNotAppliedRun,
  developNotPublicRun,
  developRepairedRun,
  developRepairFailedRun,
  developRetestingRun,
  developReviewFlaggedRun,
  developTestingRun,
  developUnsupportedRun,
} from "@/test/fixtures"
import { stubFetch } from "@/test/render"

/** Words that belong to the implementation, never to the page. */
const INTERNALS = /baseline|sha|commit|workspace|snapshot|sandbox|graph|checkpoint|permission|token|MCP/i

function renderNewRun(state?: unknown) {
  const calls = stubFetch((url) =>
    url === "/api/runs"
      ? { status: 202, body: { run_id: "new-run", status: "queued" } }
      : { status: 200, body: { status: "ok", service: "astraai" } },
  )
  const router = createMemoryRouter(
    [
      { path: "/", element: <NewRunPage /> },
      { path: "/runs/:runId", element: <p>Run page</p> },
    ],
    { initialEntries: [{ pathname: "/", state }] },
  )
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { posts: () => calls.filter((call) => call.method === "POST") }
}

afterEach(() => window.localStorage.clear())

const PROMISE = "Describe a small change. Get a tested patch."
const TASK = "What should change?"

function chooseDevelop() {
  fireEvent.click(screen.getByRole("radio", { name: "Change a repository" }))
}

describe("starting a task on a repository", () => {
  it("says what AstraAi does, then asks for the repository and the change", () => {
    renderNewRun()

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(PROMISE)
    // Changing a repository is where a new device starts.
    expect(screen.getByRole("radio", { name: "Change a repository" }).getAttribute("aria-checked")).toBe("true")
    expect(screen.getByText(/It makes the change, runs the tests, reviews it and gives you the patch/)).toBeTruthy()
    const repository = screen.getByRole("textbox", { name: "Repository" })
    const task = screen.getByRole("textbox", { name: TASK })
    expect(repository.compareDocumentPosition(task) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // What will work, before starting.
    expect(
      screen.getByText(
        /Public Python repositories whose tests run with pytest without additional dependencies\. Works on a copy\. AstraAi never writes to GitHub\./,
      ),
    ).toBeTruthy()
    expect(screen.getByRole("button", { name: "Start" })).toBeTruthy()
    // No language choice, settings, branch or technical detail.
    expect(screen.queryByRole("radiogroup", { name: "Language" })).toBeNull()
    expect(document.body.textContent).not.toMatch(/Develop a repository|model|branch|setting/i)
    expect(document.body.textContent?.replace("never writes to GitHub", "")).not.toMatch(INTERNALS)
  })

  it("sends the change, the repository and nothing more", async () => {
    const { posts } = renderNewRun()
    chooseDevelop()
    fireEvent.change(screen.getByRole("textbox", { name: TASK }), {
      target: { value: "Add a --json flag to the report command." },
    })
    fireEvent.change(screen.getByRole("textbox", { name: "Repository" }), {
      target: { value: "https://github.com/octo/sample" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Start" }))

    await waitFor(() => expect(posts()).toHaveLength(1))
    expect(posts()[0].body).toEqual({
      task: "Add a --json flag to the report command.",
      language: "python",
      mode: "develop",
      repository: "https://github.com/octo/sample",
    })
  })

  it.each([
    ["", "Enter a GitHub repository."],
    ["https://gitlab.com/octo/sample", "Enter a GitHub repository, like https://github.com/owner/name."],
    ["https://github.com/octo/sample/tree/main", "Enter a GitHub repository, like https://github.com/owner/name."],
  ])("refuses %j without sending anything", (value, message) => {
    const { posts } = renderNewRun()
    fireEvent.change(screen.getByRole("textbox", { name: TASK }), { target: { value: "Add a flag." } })
    fireEvent.change(screen.getByRole("textbox", { name: "Repository" }), { target: { value } })
    fireEvent.click(screen.getByRole("button", { name: "Start" }))

    expect(screen.getByText(message)).toBeTruthy()
    expect(screen.getByRole("textbox", { name: "Repository" }).getAttribute("aria-invalid")).toBe("true")
    expect(posts()).toHaveLength(0)
  })

  it("opens with the request of a task being edited", () => {
    renderNewRun({ task: "Add a flag.", language: "python", mode: "develop", repository: "octo/sample" })

    expect((screen.getByRole("textbox", { name: TASK }) as HTMLTextAreaElement).value).toBe("Add a flag.")
    expect((screen.getByRole("textbox", { name: "Repository" }) as HTMLInputElement).value).toBe("octo/sample")
  })

  it("keeps solving a coding problem as it was", () => {
    renderNewRun()
    fireEvent.click(screen.getByRole("radio", { name: "Solve a coding problem" }))

    expect(screen.getByRole("textbox", { name: "What should AstraAi solve?" })).toBeTruthy()
    expect(screen.getByText(/It generates, tests and reviews a solution/)).toBeTruthy()
    expect(screen.getByRole("radiogroup", { name: "Language" })).toBeTruthy()
    expect(screen.queryByRole("textbox", { name: "Repository" })).toBeNull()
    expect(screen.getByRole("button", { name: "Solve" })).toBeTruthy()
  })
})

async function renderRun(run: Run) {
  stubFetch(() => ({ status: 200, body: run }))
  const router = createMemoryRouter([{ path: "/runs/:runId", element: <RunPage /> }], {
    initialEntries: [`/runs/${run.run_id}`],
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  await screen.findByRole("heading", { level: 1 })
}

/** What a person reads: visible text, without the collapsed run log's contents. */
function visibleText(): string {
  const main = document.querySelector("main")!
  const log = main.querySelector("#run-log")?.textContent ?? ""
  return (main.textContent ?? "").replace(log, "")
}

const checkRow = (label: string) =>
  within(screen.getByRole("region", { name: "Checks" }))
    .getAllByRole("listitem")
    .find((item) => item.textContent?.startsWith(label))

describe("a task on a repository, while it works", () => {
  it("shows the task, the repository and what AstraAi is doing", async () => {
    await renderRun(developTestingRun)

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(developTestingRun.task)
    expect(screen.getByText("octo/sample")).toBeTruthy()
    expect(screen.getByText("Repository ready")).toBeTruthy()
    expect(screen.getByText("Public GitHub repository · Python project · pytest tests found")).toBeTruthy()
    expect(screen.getByRole("heading", { level: 2, name: /Working on your repository/ })).toBeTruthy()
    expect(screen.getAllByText(/Running the existing tests/).length).toBeGreaterThan(0)
    expect(visibleText()).not.toMatch(INTERNALS)
    expect(visibleText()).not.toContain(developTestingRun.repository_ref!.commit_sha.slice(0, 7))
  })

  it("reports the existing tests of a run that only checked the repository", async () => {
    await renderRun(developCheckedRun)

    const status = screen.getByRole("region", { name: "Repository checked" })
    expect(within(status).getByText("Existing tests: 128 passed")).toBeTruthy()
    expect(within(status).getByRole("link", { name: "New task" })).toBeTruthy()
    expect(screen.queryByRole("heading", { name: "Solution" })).toBeNull()
    expect(document.body.textContent).not.toContain(developCheckedRun.repository_ref!.commit_sha)
  })

  it("reports failing existing tests as they are, without calling the run a failure", async () => {
    await renderRun(developFailingTestsRun)

    expect(screen.getByRole("heading", { level: 2, name: "Repository checked" })).toBeTruthy()
    expect(screen.getByText("Existing tests: 126 passed · 2 failed")).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/Stopped|Couldn't verify/)
  })

  it("explains tests that couldn't run, with the details in the open run log", async () => {
    await renderRun(developEnvironmentRun)

    const status = screen.getByRole("region", { name: "Couldn't run the tests" })
    expect(within(status).getByText("AstraAi couldn't run this repository in its current environment.")).toBeTruthy()
    const log = screen.getByRole("region", { name: "Run log" })
    expect(log.textContent).toContain("Existing tests")
    expect(log.textContent).toContain("No module named 'requests'")
  })

  it("stops early on a repository V1 doesn't support, and says what is supported", async () => {
    await renderRun(developUnsupportedRun)

    const status = screen.getByRole("region", { name: "Repository not supported" })
    expect(within(status).getByText(/couldn't find tests in this repository that pytest would run/)).toBeTruthy()
    expect(
      within(status).getByText(
        /AstraAi V1 supports public Python repositories whose tests run with pytest without additional dependencies\./,
      ),
    ).toBeTruthy()
    expect(within(status).getByRole("button", { name: "Edit task" })).toBeTruthy()
    // Not a test failure, and nothing claimed about changes or checks.
    expect(document.body.textContent).not.toMatch(/failed|Couldn't verify|Changes need/)
    expect(screen.queryByRole("region", { name: "Checks" })).toBeNull()
    expect(visibleText()).not.toMatch(INTERNALS)
  })

  it("says plainly when a repository can't be reached, and offers to edit it", async () => {
    await renderRun(developNotPublicRun)

    const status = screen.getByRole("region", { name: "Repository not found" })
    expect(within(status).getByText(/If it's private, GitHub access isn't configured yet/)).toBeTruthy()
    expect(within(status).getByRole("button", { name: "Edit task" })).toBeTruthy()
  })
})

describe("changes ready for review", () => {
  it("says what happened, then the checks, then the changes, then hands over the patch", async () => {
    await renderRun(developChangedRun)

    expect(screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent)).toEqual([
      "Changes ready for review",
      "Checks",
      "Changes",
      "Run log",
    ])
    const status = screen.getByRole("region", { name: "Changes ready for review" })
    expect(within(status).getByText(CHANGES.explanation)).toBeTruthy()
    const patch = within(status).getByRole("link", { name: "Download patch" })
    expect(patch.getAttribute("href")).toBe(`/api/runs/${developChangedRun.run_id}/patch`)
    expect(patch.hasAttribute("download")).toBe(true)
    expect(status.textContent).toMatch(/Made against main as of .*Apply it in your copy of the repository with git apply\./)
    // One way to a new task, in the header; the outcome isn't a second one.
    expect(screen.getAllByRole("link", { name: "New task" })).toHaveLength(1)
    // No approval gate: nothing is published, so there is nothing to approve.
    expect(screen.queryByRole("button", { name: /Accept|Approve|Reject/ })).toBeNull()
    expect(visibleText()).not.toMatch(INTERNALS)
    expect(visibleText()).not.toMatch(/verified|confidence|score/i)
  })

  it("shows the evidence as a developer would check it, and nothing a review didn't find", async () => {
    await renderRun(developChangedRun)

    expect(checkRow("Existing tests")?.textContent).toBe("Existing tests — 128 passed · none broken")
    expect(checkRow("New tests")?.textContent).toBe("New tests — 1 passed")
    expect(checkRow("Final test run")?.textContent).toBe("Final test run — 129 passed")
    expect(checkRow("AI review")).toBeUndefined()
  })

  it("says how much changed once", async () => {
    await renderRun(developChangedRun)

    expect(visibleText().match(/files? changed/g)).toHaveLength(1)
  })

  it("renders each file's diff: removed and added lines, hunks, and no file headers", async () => {
    await renderRun(developChangedRun)

    const diff = screen.getByLabelText("Changes to report/cli.py")
    const lines = [...diff.children].map((line) => [line.textContent, line.className])
    expect(lines[0][0]).toBe("@@ -10,7 +10,9 @@")
    const removed = lines.find(([text]) => text === "-    args = parser.parse_args(argv)")!
    const added = lines.find(([text]) => text === '+    parser.add_argument("--json", action="store_true")')!
    expect(removed[1]).toContain("text-destructive")
    expect(added[1]).toContain("text-success")
    expect(diff.textContent).not.toContain("+++ b/report/cli.py")
  })

  it("opens diffs only within a size budget", async () => {
    const big = { ...CHANGES.files[0], path: "report/big.py", additions: 400 }
    await renderRun({ ...developChangedRun, changes: { ...CHANGES, files: [CHANGES.files[0], big] } })

    const files = within(screen.getByRole("region", { name: "Changes" })).getAllByRole("group")
    expect(files.map((file) => (file as HTMLDetailsElement).open)).toEqual([true, false])
  })

  it("isn't held back by tests that already failed before the change", async () => {
    await renderRun(developAlreadyFailingRun)

    expect(screen.getByRole("heading", { level: 2, name: "Changes ready for review" })).toBeTruthy()
    expect(checkRow("Existing tests")?.textContent).toBe("Existing tests — 126 passed · 2 already failing · none broken")
    expect(checkRow("Final test run")?.querySelector(".text-destructive")).toBeNull()
  })
})

describe("changes that need review", () => {
  it("names the failing tests and why, with the output and the patch", async () => {
    await renderRun(developChangedFailingRun)

    const status = screen.getByRole("region", { name: "Changes need your review" })
    expect(
      within(status).getByText("Its new test fails: test_json."),
    ).toBeTruthy()
    expect(within(status).getByRole("link", { name: "Download patch" })).toBeTruthy()
    expect(within(status).getByRole("button", { name: "Try again" })).toBeTruthy()
    expect(checkRow("New tests")?.textContent).toBe("New tests — problem: 1 added · test_json fails")
    expect(checkRow("Existing tests")?.textContent).toBe("Existing tests — 128 passed · none broken")
    // The review's finding is a check, not repeated as the reason.
    expect(checkRow("AI review")?.textContent).toMatch(/flagged something to check: --json is added/)
    expect(within(status).queryByText(/AI review/)).toBeNull()
    expect(checkRow("Final test run")?.textContent).toBe("Final test run — problem: 128 passed · 1 failed")
    const checks = screen.getByRole("region", { name: "Checks" })
    expect(within(checks).getByText(/FAILED tests\/test_cli.py::test_json/)).toBeTruthy()
  })

  it("says when a test that passed before now fails, even if the review approved", async () => {
    await renderRun(developBrokeExistingRun)

    const status = screen.getByRole("region", { name: "Changes need your review" })
    expect(within(status).getByText("1 test that passed before fails now: test_columns.")).toBeTruthy()
    expect(checkRow("Existing tests")?.textContent).toBe(
      "Existing tests — problem: 1 test that passed before fails now: test_columns",
    )
    // The tests are the reason; the review's approval isn't repeated as one.
    expect(within(status).queryByText(/AI review/)).toBeNull()
  })

  it("holds back passing tests when the AI review flagged something to check", async () => {
    await renderRun(developReviewFlaggedRun)

    expect(screen.getByRole("heading", { level: 2, name: "Changes need your review" })).toBeTruthy()
    expect(checkRow("Final test run")?.textContent).toBe("Final test run — 129 passed")
    expect(checkRow("AI review")?.textContent).toBe(
      "AI review — to check: flagged something to check: --json is added after parse_args runs.",
    )
    expect(visibleText()).not.toMatch(/failed/i)
  })
})

describe("changes AstraAi couldn't verify", () => {
  it("never calls tests that couldn't run a failure", async () => {
    await renderRun(developChangedNotRunRun)

    const status = screen.getByRole("region", { name: "AstraAi couldn't verify the changes" })
    expect(within(status).getByText(/couldn't start the tests/)).toBeTruthy()
    expect(checkRow("Final test run")?.textContent).toBe("Final test run — to check: couldn't run")
    const checks = screen.getByRole("region", { name: "Checks" })
    expect(within(checks).getByText(/couldn't run the tests on the changed repository/)).toBeTruthy()
    expect(within(checks).queryByText(/failed/)).toBeNull()
    expect(visibleText()).not.toMatch(INTERNALS)
  })
})

describe("no changes", () => {
  it("says nothing needed to change, and why, without a patch", async () => {
    await renderRun(developNoChangesNeededRun)

    const status = screen.getByRole("region", { name: "No changes needed" })
    expect(within(status).getByText(/already has a --json flag/)).toBeTruthy()
    expect(within(status).getByRole("button", { name: "Edit task" })).toBeTruthy()
    expect(screen.queryByRole("link", { name: "Download patch" })).toBeNull()
    expect(screen.queryByRole("region", { name: "Changes" })).toBeNull()
    expect(screen.queryByRole("region", { name: "Checks" })).toBeNull()
  })

  it("says plainly when changes couldn't be made, without calling them unnecessary", async () => {
    await renderRun(developNotAppliedRun)

    const status = screen.getByRole("region", { name: "No changes made" })
    expect(within(status).getByText(/didn't match the repository exactly/)).toBeTruthy()
    expect(within(status).getByRole("button", { name: "Edit task" })).toBeTruthy()
    expect(screen.queryByRole("region", { name: "Changes" })).toBeNull()
  })
})

describe("the one repair", () => {
  it("shows the fix without a stale diff, a counter or a budget", async () => {
    await renderRun(developFixingRun)

    expect(screen.getAllByText("Fixing an issue…").length).toBeGreaterThan(0)
    const steps = screen.getByRole("region", { name: /Working on your repository/ })
    expect(within(steps).getByText("--json is added after parse_args runs.")).toBeTruthy()
    // The first change's diff and results are no longer the answer.
    expect(screen.queryByLabelText("Changes to report/cli.py")).toBeNull()
    expect(checkRow("Final test run")?.textContent).toBe("Final test run — Waiting for the fix…")
    expect(within(screen.getByRole("region", { name: "Checks" })).queryByText(/FAILED/)).toBeNull()
    expect(visibleText()).not.toMatch(INTERNALS)
    expect(visibleText()).not.toMatch(/attempt|revision|budget/i)
  })

  it("then runs the tests again on the final diff", async () => {
    await renderRun(developRetestingRun)

    expect(screen.getAllByText("Running tests again…").length).toBeGreaterThan(0)
    expect(screen.getByLabelText("Changes to report/cli.py")).toBeTruthy()
    expect(visibleText()).not.toMatch(/attempt|revision|budget/i)
  })

  it("ends ready for review with one line about the fix; the first try stays in the run log", async () => {
    await renderRun(developRepairedRun)

    const status = screen.getByRole("region", { name: "Changes ready for review" })
    expect(
      within(status).getByText(
        "AstraAi found a failing test after its first change and corrected it before the final test run.",
      ),
    ).toBeTruthy()
    // The summary describes the final change, never the repair's own story.
    expect(within(status).getByText(developRepairedRun.changes!.explanation)).toBeTruthy()
    expect(within(screen.getByRole("region", { name: "Checks" })).queryByText(/FAILED/)).toBeNull()
    const log = screen.getByRole("region", { name: "Run log" })
    expect(log.querySelector("details")?.open).toBe(false)
    expect(visibleText()).not.toContain("Before the fix")
    expect(log.textContent).toContain("Before the fix")
    expect(log.textContent).toContain("Corrected: The flag is now added before the arguments are parsed.")
  })

  it("ends needing review, with what failed, when the fix still fails", async () => {
    await renderRun(developRepairFailedRun)

    const status = screen.getByRole("region", { name: "Changes need your review" })
    expect(within(status).getByText(/Its new test fails: test_json/)).toBeTruthy()
    expect(within(screen.getByRole("region", { name: "Checks" })).getByText(/FAILED tests\/test_cli.py::test_json/)).toBeTruthy()
    expect(screen.queryByText("Changes ready for review")).toBeNull()
  })
})
