// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { createMemoryRouter, RouterProvider } from "react-router"
import { describe, expect, it, vi } from "vitest"

import type { Run } from "@/api/types"
import { RunPage } from "@/routes/RunPage"
import { executingRun, waitingRun } from "@/test/fixtures"
import { setViewport, stubFetch, waitingFor } from "@/test/render"

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
  await screen.findByRole("tablist", { name: "Run results" })
}

const waiting = waitingFor(waitingRun, { startedMsAgo: 60_000, expiresInMs: 9 * 60_000 })

describe("run page", () => {
  it("shows the four-step progress with the current step", async () => {
    setViewport("desktop")
    await renderRun(executingRun)

    const progress = screen.getByRole("navigation", { name: "Progress" })
    const steps = within(progress).getAllByRole("listitem")
    expect(steps.map((step) => step.textContent?.split(":")[0])).toEqual(["Understand", "Build", "Verify", "Approve"])
    expect(steps[2].getAttribute("aria-current")).toBe("step")
  })

  it("states the task once and has no separate status card or counters", async () => {
    setViewport("desktop")
    await renderRun(executingRun)

    expect(screen.getAllByText(executingRun.task)).toHaveLength(1)
    expect(document.body.textContent).not.toMatch(/Execution retries|Revisions|Stage/)
    expect(document.body.textContent).not.toMatch(/\d\/\d/)
    // The status pill is coarse; the specific activity is said once, in the decision panel.
    // (The polite live region repeats it for screen readers only.)
    const visible = screen.getAllByText(/Verifying the solution/).filter((node) => !node.classList.contains("sr-only"))
    expect(visible).toHaveLength(1)
  })

  it("expands the full task from the header", async () => {
    setViewport("desktop")
    await renderRun(executingRun)

    await userEvent.click(screen.getByRole("button", { name: /Show the full task/ }))
    expect(document.getElementById("full-task")?.textContent).toContain(executingRun.task)
  })

  it("puts the solution before the decision, so phones show the work first", async () => {
    setViewport("mobile")
    await renderRun(waiting)

    const solution = screen.getByRole("region", { name: "solution.py" })
    const decision = screen.getByRole("complementary", { name: "Run status" })
    expect(solution.compareDocumentPosition(decision) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it("shows a single countdown and a single set of approval actions on a phone", async () => {
    setViewport("mobile")
    await renderRun(waiting)

    expect(screen.getAllByRole("timer")).toHaveLength(1)
    expect(screen.getAllByRole("button", { name: "Approve this solution" })).toHaveLength(1)
    expect(within(screen.getByRole("region", { name: "Approval actions" })).getByRole("timer")).toBeTruthy()
  })

  it("reserves the phone approval bar's measured height, and releases it when the bar goes", async () => {
    setViewport("mobile")
    vi.stubGlobal(
      "ResizeObserver",
      class {
        callback: () => void
        constructor(callback: () => void) {
          this.callback = callback
        }
        observe() {
          this.callback()
        }
        disconnect() {}
      },
    )
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(89)
    await renderRun(waiting)

    const root = document.documentElement
    expect(root.style.getPropertyValue("--approval-bar-height")).toBe("89px")
    cleanup()
    expect(root.style.getPropertyValue("--approval-bar-height")).toBe("")
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it("keeps the approval decision in the panel on desktop", async () => {
    setViewport("desktop")
    await renderRun(waiting)

    const decision = screen.getByRole("complementary", { name: "Run status" })
    expect(within(decision).getByRole("button", { name: "Approve this solution" })).toBeTruthy()
    expect(screen.getAllByRole("timer")).toHaveLength(1)
    expect(screen.queryByRole("region", { name: "Approval actions" })).toBeNull()
  })

  it("opens verification details from the decision panel", async () => {
    setViewport("desktop")
    Element.prototype.scrollIntoView = () => undefined
    await renderRun(waiting)

    await userEvent.click(screen.getByRole("button", { name: "Verification details" }))

    expect(screen.getByRole("tab", { name: "Details" }).getAttribute("aria-selected")).toBe("true")
    expect((document.getElementById("verification-details") as HTMLDetailsElement).open).toBe(true)
  })
})
