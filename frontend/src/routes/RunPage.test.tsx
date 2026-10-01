// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { createMemoryRouter, RouterProvider } from "react-router"
import { describe, expect, it, vi } from "vitest"

import type { Run } from "@/api/types"
import { RunPage } from "@/routes/RunPage"
import { completedRun, executingRun, expiredRun, outOfFixesRun, waitingRun } from "@/test/fixtures"
import { stubFetch, waitingFor } from "@/test/render"

async function renderRun(run: Run) {
  stubFetch(() => ({ status: 200, body: run }))
  const router = createMemoryRouter([{ path: "/runs/:runId", element: <RunPage /> }], {
    initialEntries: [`/runs/${run.run_id}`],
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  await screen.findByRole("heading", { level: 1 })
}

const review = waitingFor(waitingRun, { startedMsAgo: 60_000, expiresInMs: 9 * 60_000 })
const headings = () => screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent)

describe("run page", () => {
  it("is the task, one status, and the work: no pipeline, tabs or status pill", async () => {
    await renderRun(executingRun)

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(executingRun.task)
    expect(screen.queryByRole("tablist")).toBeNull()
    expect(document.body.textContent).not.toMatch(/Understand|Build|Verify|Approve|Stage|Revisions/)
    // The run's state is said once, in the status; the live region repeats it for screen readers.
    const visible = screen
      .getAllByText(/Running the tests/)
      .filter((node) => !node.classList.contains("sr-only"))
    expect(visible).toHaveLength(1)
  })

  it("puts the status before the work in reading order, and the work in a fixed order", async () => {
    await renderRun(completedRun)

    expect(headings()).toEqual(["Accepted", "Solution", "Tests", "Run log"])
    const status = screen.getByRole("region", { name: "Accepted" })
    const solution = screen.getByRole("region", { name: "solution.py" })
    expect(status.compareDocumentPosition(solution) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it("has one set of review actions and no countdown", async () => {
    await renderRun(review)

    expect(screen.queryByRole("timer")).toBeNull()
    expect(screen.getAllByRole("group", { name: "Review actions" })).toHaveLength(1)
    expect(screen.getAllByRole("button", { name: "Accept" })).toHaveLength(1)
  })

  it("takes the reviewer to the tests", async () => {
    Element.prototype.scrollIntoView = vi.fn()
    await renderRun(review)

    await userEvent.click(screen.getByRole("button", { name: "View tests" }))

    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Tests" }))
  })

  it("keeps a review that ran out of time readable: solution, tests and proof", async () => {
    await renderRun(expiredRun)

    expect(screen.getByRole("heading", { level: 2, name: "Not reviewed in time" })).toBeTruthy()
    expect(screen.getByRole("region", { name: "solution.py" })).toBeTruthy()
    expect(screen.getByRole("heading", { name: "Tests" }).parentElement!.textContent).toBe("Tests2 passed")
    expect(document.body.textContent).toContain("Checks passed")
  })

  it("opens the log by itself only when it explains the ending", async () => {
    await renderRun(outOfFixesRun)
    const log = () => screen.getByText("Run log", { selector: "h2" }).closest("details")!
    expect(log().open).toBe(true)
  })

  it("keeps the log closed after a clean run, and opens it on request", async () => {
    Element.prototype.scrollIntoView = vi.fn()
    await renderRun(completedRun)
    const log = () => screen.getByText("Run log", { selector: "h2" }).closest("details")!
    expect(log().open).toBe(false)

    await userEvent.click(log().querySelector("summary")!)
    await waitFor(() => expect(log().open).toBe(true))
  })

  it("offers the full task when the title is clamped", async () => {
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(120)
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(56)
    await renderRun(executingRun)

    await userEvent.click(screen.getByRole("button", { name: "Show full task" }))

    expect(document.getElementById("full-task")?.textContent).toBe(executingRun.task)
    vi.restoreAllMocks()
  })
})
