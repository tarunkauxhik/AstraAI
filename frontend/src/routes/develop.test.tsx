// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { createMemoryRouter, RouterProvider } from "react-router"
import { describe, expect, it } from "vitest"

import type { Run } from "@/api/types"
import { NewRunPage } from "@/routes/NewRunPage"
import { RunPage } from "@/routes/RunPage"
import {
  developChangedFailingRun,
  developChangedNotRunRun,
  developChangedRun,
  developCheckedRun,
  developEnvironmentRun,
  developFailingTestsRun,
  developFixingRun,
  developNoUsefulChangesRun,
  developNotAppliedRun,
  developRepairedRun,
  developRepairFailedRun,
  developRetestingRun,
  developNotPublicRun,
  developTestingRun,
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

function chooseDevelop() {
  fireEvent.click(screen.getByRole("radio", { name: "Develop a repository" }))
}

describe("starting a develop run", () => {
  it("asks only for the change and the repository", () => {
    renderNewRun()
    chooseDevelop()

    expect(screen.getByRole("heading", { level: 1, name: "What do you want changed?" })).toBeTruthy()
    expect(screen.getByRole("textbox", { name: "What do you want changed?" })).toBeTruthy()
    expect(screen.getByRole("textbox", { name: "Repository" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "Start" })).toBeTruthy()
    // No language choice, settings, branch or technical detail.
    expect(screen.queryByRole("radiogroup", { name: "Language" })).toBeNull()
    expect(screen.queryByText(/self-contained function/)).toBeNull()
    expect(document.body.textContent).not.toMatch(INTERNALS)
    expect(document.body.textContent).not.toMatch(/branch/i)
  })

  it("sends the change, the repository and nothing more", async () => {
    const { posts } = renderNewRun()
    chooseDevelop()
    fireEvent.change(screen.getByRole("textbox", { name: "What do you want changed?" }), {
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
    chooseDevelop()
    fireEvent.change(screen.getByRole("textbox", { name: "What do you want changed?" }), {
      target: { value: "Add a flag." },
    })
    fireEvent.change(screen.getByRole("textbox", { name: "Repository" }), { target: { value } })
    fireEvent.click(screen.getByRole("button", { name: "Start" }))

    expect(screen.getByText(message)).toBeTruthy()
    expect(screen.getByRole("textbox", { name: "Repository" }).getAttribute("aria-invalid")).toBe("true")
    expect(posts()).toHaveLength(0)
  })

  it("opens with the request of a develop run being edited", () => {
    renderNewRun({ task: "Add a flag.", language: "python", mode: "develop", repository: "octo/sample" })

    expect((screen.getByRole("textbox", { name: "What do you want changed?" }) as HTMLTextAreaElement).value).toBe(
      "Add a flag.",
    )
    expect((screen.getByRole("textbox", { name: "Repository" }) as HTMLInputElement).value).toBe("octo/sample")
  })

  it("leaves Solve exactly as it was", () => {
    renderNewRun()

    expect(screen.getByRole("heading", { level: 1, name: "What do you want AstraAi to solve?" })).toBeTruthy()
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
  return document.querySelector("main")!.textContent ?? ""
}

describe("a develop run", () => {
  it("shows the task, the repository and what AstraAi is doing", async () => {
    await renderRun(developTestingRun)

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(developTestingRun.task)
    expect(screen.getByText("octo/sample")).toBeTruthy()
    expect(screen.getByText("Repository read")).toBeTruthy()
    expect(screen.getByRole("heading", { level: 2, name: /Working on your repository/ })).toBeTruthy()
    expect(screen.getAllByText(/Running the existing tests/).length).toBeGreaterThan(0)
    expect(visibleText()).not.toMatch(INTERNALS)
    expect(visibleText()).not.toContain(developTestingRun.repository_ref!.commit_sha.slice(0, 7))
  })

  it("reports the existing tests when the check is done", async () => {
    await renderRun(developCheckedRun)

    const status = screen.getByRole("region", { name: "Repository checked" })
    expect(within(status).getByText("Existing tests: 128 passed")).toBeTruthy()
    expect(within(status).getByRole("link", { name: "New run" })).toBeTruthy()
    // No solution or tests sections: there is nothing written yet.
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
    expect(
      within(status).getByText("AstraAi couldn't run this repository in its current environment."),
    ).toBeTruthy()
    const log = screen.getByRole("region", { name: "Run log" })
    expect(log.textContent).toContain("Existing tests")
    expect(log.textContent).toContain("No module named 'requests'")
  })

  it("says plainly when a repository can't be reached, and offers to edit it", async () => {
    await renderRun(developNotPublicRun)

    const status = screen.getByRole("region", { name: "Repository not found" })
    expect(within(status).getByText(/If it's private, GitHub access isn't configured yet/)).toBeTruthy()
    expect(within(status).getByRole("button", { name: "Edit task" })).toBeTruthy()
  })
})

describe("changes ready for review", () => {
  it("leads with the diff, then the tests before and after", async () => {
    await renderRun(developChangedRun)

    const status = screen.getByRole("region", { name: "Changes ready for review" })
    expect(within(status).getByText("2 files changed · Tests: 129 passed")).toBeTruthy()
    expect(screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent)).toEqual([
      "Changes ready for review",
      "Changes",
      "Verification",
      "Run log",
    ])
    const changes = screen.getByRole("region", { name: "Changes" })
    expect(within(changes).getByText("2 files changed ·", { exact: false })).toBeTruthy()
    expect(within(changes).getByText("report/cli.py")).toBeTruthy()
    expect(within(changes).getByText("tests/test_cli.py")).toBeTruthy()
    expect(within(changes).getByText("new")).toBeTruthy()
    const verification = screen.getByRole("region", { name: "Verification" })
    expect(within(verification).getByText("128 passed")).toBeTruthy()
    expect(within(verification).getByText("129 passed")).toBeTruthy()
    expect(within(verification).getByText("AI review found no issues")).toBeTruthy()
    expect(visibleText()).not.toMatch(INTERNALS)
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

  it("keeps the explanation secondary and collapsed", async () => {
    await renderRun(developChangedRun)

    const explanation = screen.getByText("Adds a --json flag that prints the report as JSON, with a test.")
    expect(explanation.closest("details")?.open).toBe(false)
  })

  it("shows failing tests after the change, with their output", async () => {
    await renderRun(developChangedFailingRun)

    const verification = screen.getByRole("region", { name: "Verification" })
    expect(within(verification).getByText("128 passed · 1 failed").className).toContain("text-destructive")
    expect(within(verification).getByText(/FAILED tests\/test_cli.py::test_json/)).toBeTruthy()
    expect(within(verification).getByText(/AI review:/)).toBeTruthy()
  })

  it("never calls a sandbox problem a test failure", async () => {
    await renderRun(developChangedNotRunRun)

    const verification = screen.getByRole("region", { name: "Verification" })
    expect(within(verification).getByText("couldn't run").className).not.toContain("text-destructive")
    expect(within(verification).getByText(/couldn't run the tests on the changed repository/)).toBeTruthy()
    expect(within(verification).queryByText(/failed/)).toBeNull()
  })

  it("says plainly when no changes could be made", async () => {
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
    const verification = screen.getByRole("region", { name: "Verification" })
    expect(within(verification).getByText("Waiting for the fix…")).toBeTruthy()
    expect(within(verification).queryByText(/FAILED/)).toBeNull()
    expect(visibleText()).not.toMatch(INTERNALS)
    expect(visibleText()).not.toMatch(/attempt|revision|budget/i)
  })

  it("then runs the tests again on the final diff", async () => {
    await renderRun(developRetestingRun)

    expect(screen.getAllByText("Running tests again…").length).toBeGreaterThan(0)
    expect(screen.getByLabelText("Changes to report/cli.py")).toBeTruthy()
    expect(visibleText()).not.toMatch(/attempt|revision|budget/i)
  })

  it("ends ready for review when the fix passes, with the first try only in the run log", async () => {
    await renderRun(developRepairedRun)

    const status = screen.getByRole("region", { name: "Changes ready for review" })
    expect(within(status).getByText("2 files changed · Tests: 129 passed")).toBeTruthy()
    const verification = screen.getByRole("region", { name: "Verification" })
    expect(within(verification).getByText("129 passed")).toBeTruthy()
    expect(within(verification).queryByText(/FAILED/)).toBeNull()
    // The first try is history: only in the collapsed run log.
    const log = screen.getByRole("region", { name: "Run log" })
    expect(log.querySelector("details")?.open).toBe(false)
    expect(visibleText().replace(log.textContent ?? "", "")).not.toContain("Before the fix")
    expect(log.textContent).toContain("Before the fix")
    expect(log.textContent).toContain("--json is added after parse_args runs.")
  })

  it("ends needing review, with what failed, when the fix still fails", async () => {
    await renderRun(developRepairFailedRun)

    const status = screen.getByRole("region", { name: "Changes need your review" })
    expect(within(status).getByText("2 files changed · Tests: 128 passed · 1 failed")).toBeTruthy()
    const verification = screen.getByRole("region", { name: "Verification" })
    expect(within(verification).getByText(/FAILED tests\/test_cli.py::test_json/)).toBeTruthy()
    expect(screen.queryByText("Changes ready for review")).toBeNull()
  })

  it("says no useful changes only when nothing needed to change", async () => {
    await renderRun(developNoUsefulChangesRun)

    const status = screen.getByRole("region", { name: "No useful changes" })
    expect(within(status).getByText(/didn't find anything to change/)).toBeTruthy()
  })
})
