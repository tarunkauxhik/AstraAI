// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { createMemoryRouter, RouterProvider, useLocation, useParams } from "react-router"
import { describe, expect, it, vi } from "vitest"

import type { Run } from "@/api/types"
import { RunStatus } from "@/components/run/RunStatus"
import { useRun } from "@/hooks/useRun"
import {
  approvedThenFailedRun,
  completedRun,
  executingRun,
  expiredRun,
  llmFailedRun,
  outOfFixesRun,
  reExecutingAfterRevisionRun,
  rejectedRun,
  resumingRun,
  revisingRun,
  sandboxUnavailableRun,
  waitingRun,
} from "@/test/fixtures"
import { stubFetch, waitingFor } from "@/test/render"

type Reply = { status: number; body: unknown }

/**
 * RunStatus inside the real polling hook, against a stubbed server: `server.run` is what
 * GET returns, so a test moves the server on by changing it, exactly as the app would see.
 */
function renderStatus(run: Run, replies: { approval?: Reply; create?: Reply } = {}) {
  const server = { run }
  const calls = stubFetch((url, init) => {
    const method = init?.method ?? "GET"
    if (method === "POST" && url.endsWith("/approval")) {
      return replies.approval ?? { status: 202, body: { run_id: run.run_id, status: "running" } }
    }
    if (method === "POST" && url === "/api/runs") {
      return replies.create ?? { status: 202, body: { run_id: "next-run", status: "queued" } }
    }
    return { status: 200, body: server.run }
  })
  const onViewTests = vi.fn()
  const onOpenLog = vi.fn()

  function Harness() {
    const { runId = "" } = useParams()
    const { data } = useRun(runId)
    return data ? <RunStatus run={data} onViewTests={onViewTests} onOpenLog={onOpenLog} /> : null
  }
  function NewRun() {
    return <p>New run page: {JSON.stringify(useLocation().state)}</p>
  }

  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  client.setQueryData(["run", run.run_id], run)
  const router = createMemoryRouter(
    [
      { path: "/", element: <NewRun /> },
      { path: "/runs/:runId", element: <Harness /> },
    ],
    { initialEntries: [`/runs/${run.run_id}`] },
  )
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  const posts = () => calls.filter((call) => call.method === "POST")
  const gets = () => calls.filter((call) => call.method === "GET")
  return { server, posts, gets, onViewTests, onOpenLog, router }
}

const heading = () => screen.getByRole("heading", { level: 2 })
const review = waitingFor(waitingRun, { startedMsAgo: 60_000, expiresInMs: 9 * 60_000 })

describe("working", () => {
  it("shows facts as they happen, with one step in progress and a clock", () => {
    renderStatus(executingRun)

    expect(heading().textContent).toMatch(/^Working · \d+:\d{2}/)
    const steps = within(screen.getByRole("list", { name: "Progress" })).getAllByRole("listitem")
    expect(steps.map((step) => step.textContent?.split(":")[0])).toEqual([
      "Task analyzed",
      "2 tests written",
      "Solution written",
      "Running the tests…",
      "AI review",
    ])
    expect(steps.filter((step) => step.getAttribute("aria-current") === "step")).toHaveLength(1)
  })

  it("says what a repair is fixing, not which attempt it is", () => {
    renderStatus(revisingRun)
    expect(screen.getByText("Fixing the solution…")).toBeTruthy()
    expect(screen.getByText("Reversal must operate on characters, not bytes.")).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/attempt|revision|Previous/i)
  })

  it("repeats the test run without showing the previous result as current", () => {
    renderStatus(reExecutingAfterRevisionRun)
    expect(screen.getByText("Running the tests again…")).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/passed/)
  })
})

describe("review", () => {
  it("leads with the verdict, what to check, and what accepting means", async () => {
    const { onViewTests } = renderStatus(review)

    expect(heading().textContent).toBe("Ready for review")
    // Execution evidence is the headline; the model's own assessment sits under it, smaller.
    const tests = screen.getByText("2 of 2 tests passed")
    const aiReview = screen.getByText("AI review found no issues")
    expect(tests.className).toContain("text-success")
    expect(aiReview.className).toContain("text-xs")
    expect(tests.compareDocumentPosition(aiReview) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByText(/AstraAi wrote these tests — check that they match what you meant/)).toBeTruthy()
    expect(screen.getByText("Accepting marks this run complete. Nothing is published or deployed.")).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/Verified by AstraAi|Why this was accepted|Approve/)

    await userEvent.click(screen.getByRole("button", { name: "View tests" }))
    expect(onViewTests).toHaveBeenCalledOnce()
  })

  it("mentions fixes that were needed to get there", () => {
    renderStatus({ ...review, revision_count: 1 })
    expect(screen.getByText("2 of 2 tests passed after 1 fix")).toBeTruthy()
  })

  it("sends Accept without marking anything locally", async () => {
    const { posts } = renderStatus(review)

    await userEvent.click(screen.getByRole("button", { name: "Accept" }))

    expect(posts()).toEqual([{ url: `/api/runs/${review.run_id}/approval`, method: "POST", body: { decision: "approve" } }])
    expect(await screen.findByText("Decision sent. Updating…")).toBeTruthy()
    expect(heading().textContent).toBe("Ready for review")
  })

  it("rejects at once: nothing is lost, so there's no confirmation dialog", async () => {
    const { posts } = renderStatus(review)

    await userEvent.click(screen.getByRole("button", { name: "Reject" }))

    expect(screen.queryByRole("alertdialog")).toBeNull()
    expect(posts()[0].body).toEqual({ decision: "reject" })
  })

  it("has no keyboard shortcut for Accept", () => {
    renderStatus(review)
    expect(screen.getByRole("button", { name: "Accept" }).getAttribute("aria-keyshortcuts")).toBeNull()
  })

  it("moves focus to the outcome once the server has moved on", async () => {
    const { server } = renderStatus(review)
    server.run = resumingRun

    await userEvent.click(screen.getByRole("button", { name: "Accept" }))

    await waitFor(() => expect(heading().textContent).toBe("Accepting…"))
    expect(document.activeElement).toBe(heading())
  })

  it("shows a server conflict and never claims the decision succeeded", async () => {
    renderStatus(review, { approval: { status: 409, body: { detail: "The approval request has expired." } } })

    await userEvent.click(screen.getByRole("button", { name: "Accept" }))

    expect((await screen.findByRole("alert")).textContent).toBe("The approval request has expired.")
    expect(screen.queryByText("Decision sent. Updating…")).toBeNull()
  })
})

describe("time to review", () => {
  it("never hurries a decision that publishes nothing: no countdown, no more-time button", () => {
    const soon = waitingFor(waitingRun, { startedMsAgo: 500_000, expiresInMs: 90_000 })
    renderStatus(soon)

    expect(screen.queryByRole("timer")).toBeNull()
    expect(screen.queryByRole("button", { name: "More time" })).toBeNull()
    expect(document.body.textContent).not.toMatch(/closes|minutes? left/i)
    expect((screen.getByRole("button", { name: "Accept" }) as HTMLButtonElement).disabled).toBe(false)
  })
})

describe("endings", () => {
  it("accepted: the solution to copy, how long it took, and a new run", () => {
    renderStatus(completedRun)
    expect(heading().textContent).toBe("Accepted")
    expect(screen.getByText("All checks passed · 2m 00s")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Copy solution.py" }).textContent).toBe("Copy solution")
    expect(screen.getByRole("link", { name: "New task" })).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/You approved/)
  })

  it("a review window that closed is neutral and keeps the result", () => {
    renderStatus(expiredRun)
    expect(heading().textContent).toBe("Not reviewed in time")
    expect(screen.getByText(/All checks passed, but the review window closed/)).toBeTruthy()
    expect(screen.getByRole("button", { name: "Copy solution.py" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/expired|failed/i)
  })

  it("rejected: neutral, with a way to try again differently", async () => {
    const { router } = renderStatus(rejectedRun)
    expect(heading().textContent).toBe("Rejected")
    expect(screen.getByText("The solution wasn't accepted.")).toBeTruthy()

    await userEvent.click(screen.getByRole("button", { name: "Edit task" }))

    expect(router.state.location.pathname).toBe("/")
    expect(router.state.location.state).toEqual({ task: rejectedRun.task, language: "python" })
  })

  it("couldn't verify: the first failing evidence and the ways forward", async () => {
    const { onOpenLog } = renderStatus(outOfFixesRun)

    expect(heading().textContent).toBe("Couldn't verify")
    expect(screen.getByText("1 of 2 tests failed after the available fixes.")).toBeTruthy()
    expect(screen.getByText("FAIL basic_word: expected 'cba', got 'abc'")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "Edit task" })).toBeTruthy()

    await userEvent.click(screen.getByRole("button", { name: "Run log" }))
    expect(onOpenLog).toHaveBeenCalledOnce()
  })

  it("runs the same task again in one click", async () => {
    const { posts, router } = renderStatus(sandboxUnavailableRun)

    await userEvent.click(screen.getByRole("button", { name: "Try again" }))

    expect(posts()[0]).toEqual({
      url: "/api/runs",
      method: "POST",
      body: { task: sandboxUnavailableRun.task, language: "python" },
    })
    await waitFor(() => expect(router.state.location.pathname).toBe("/runs/next-run"))
  })

  it("explains a busy service instead of failing silently", async () => {
    renderStatus(llmFailedRun, { create: { status: 429, body: { detail: "Too many runs are waiting. Try again shortly." } } })

    await userEvent.click(screen.getByRole("button", { name: "Try again" }))

    expect((await screen.findByRole("alert")).textContent).toBe(
      "Couldn't start a new task. Too many runs are waiting. Try again shortly.",
    )
  })

  it("keeps codes, stages and budgets out of the status", () => {
    for (const run of [sandboxUnavailableRun, llmFailedRun, outOfFixesRun, approvedThenFailedRun]) {
      renderStatus(run)
      expect(document.body.textContent).not.toMatch(
        new RegExp(`${run.error!.code}|Stopped while|Error code|budget|recommended|attempt`, "i"),
      )
      cleanup()
    }
  })

  it("notes an acceptance that couldn't be finished", () => {
    renderStatus(approvedThenFailedRun)
    expect(heading().textContent).toBe("Something went wrong")
    expect(screen.getByText("You accepted the solution, but the run couldn't finish.")).toBeTruthy()
  })
})
