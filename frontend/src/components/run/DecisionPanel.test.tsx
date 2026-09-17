// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import type { Run } from "@/api/types"
import { DecisionPanel } from "@/components/run/DecisionPanel"
import { runQueryKey } from "@/hooks/useRun"
import {
  approvedThenFailedRun,
  completedRun,
  executingRun,
  expiredRun,
  generatingRun,
  needsReviewRun,
  queuedRun,
  reExecutingAfterRevisionRun,
  rejectedRun,
  revisingRun,
  sandboxUnavailableRun,
  timedOutDuringReExecutionRun,
  waitingRun,
} from "@/test/fixtures"
import { renderWithClient, setViewport, stubFetch, waitingFor } from "@/test/render"

const run = waitingFor(waitingRun, { startedMsAgo: 60_000, expiresInMs: 9 * 60_000 })
const approvalUrl = `/api/runs/${run.run_id}/approval`

function renderPanel(target: Run, options: { seed?: boolean } = {}) {
  const onShowDetails = vi.fn()
  const utils = renderWithClient(<DecisionPanel run={target} onShowDetails={onShowDetails} />, {
    run: options.seed ? target : undefined,
  })
  return { ...utils, onShowDetails }
}

describe("working", () => {
  it("says what AstraAi is doing, in plain words", () => {
    renderPanel(generatingRun)

    expect(screen.getByRole("heading", { name: "AstraAi is working" })).toBeTruthy()
    expect(screen.getByText("Building the solution…")).toBeTruthy()
    // No internal stage names, zero counters or attempt numbers on a first attempt.
    expect(document.body.textContent).not.toMatch(/generat(e|ing)_|revision|retr(y|ies)|attempt/i)
  })

  it("explains a repair once, and points to the previous attempt", async () => {
    const { onShowDetails } = renderPanel(reExecutingAfterRevisionRun)

    expect(screen.getByText("Verifying the solution…")).toBeTruthy()
    expect(screen.getByText("Checking the repaired version (attempt 2).")).toBeTruthy()
    expect(document.body.textContent?.match(/attempt 2/gi)).toHaveLength(1)
    // An earlier attempt's pass is never shown as a current result here.
    expect(screen.queryByText(/passed/i)).toBeNull()

    await userEvent.click(screen.getByRole("button", { name: "Previous attempt" }))
    expect(onShowDetails).toHaveBeenCalledOnce()
  })

  it("names the repair being made", () => {
    renderPanel(revisingRun)
    expect(screen.getByText("Making a repair…")).toBeTruthy()
    expect(screen.getByText("Found an issue — repairing the solution (attempt 2).")).toBeTruthy()
  })

  it("shows a queued run as waiting, without claiming how workers are scheduled", () => {
    renderPanel(queuedRun)
    expect(screen.getByRole("heading", { name: "Waiting to start" })).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/one at a time/i)
  })

  it("does not show zero counters", () => {
    renderPanel(executingRun)
    expect(document.body.textContent).not.toMatch(/0 (revisions|retries)/)
  })
})

describe("approval", () => {
  function button(name: string) {
    return screen.getByRole("button", { name })
  }

  it("leads with verification, the result and the decision", () => {
    setViewport("desktop")
    stubFetch(() => ({ status: 200, body: run }))
    renderPanel(run)

    expect(screen.getByText("Verified by AstraAi")).toBeTruthy()
    expect(screen.getByRole("heading", { name: "Ready for your approval" })).toBeTruthy()
    expect(screen.getByText("2 / 2 tests passed")).toBeTruthy()
    expect(screen.getByText("Review passed")).toBeTruthy()
    expect((button("Approve this solution") as HTMLButtonElement).disabled).toBe(false)
    expect(button("Reject this solution")).toBeTruthy()
    // No restated problem, and the reviewer's reason sits behind a disclosure.
    expect(screen.queryByText(run.approval_request!.problem_summary)).toBeNull()
    const reason = screen.getByText(run.approval_request!.critic_reason)
    expect(reason.closest("details")?.open).toBe(false)
  })

  it("shows exactly one countdown, in the panel on desktop", () => {
    setViewport("desktop")
    stubFetch(() => ({ status: 200, body: run }))
    renderPanel(run)

    expect(screen.getAllByRole("timer")).toHaveLength(1)
    expect(screen.getAllByRole("timer")[0].textContent).toMatch(/^\d:\d\d$/)
    expect(screen.queryByRole("region", { name: "Approval actions" })).toBeNull()
  })

  it("moves the actions and the only countdown into the sticky bar on smaller screens", () => {
    setViewport("mobile")
    stubFetch(() => ({ status: 200, body: run }))
    renderPanel(run)

    const bar = screen.getByRole("region", { name: "Approval actions" })
    expect(screen.getAllByRole("timer")).toHaveLength(1)
    expect(within(bar).getByRole("timer")).toBeTruthy()
    expect(within(bar).getByRole("button", { name: "Approve this solution" })).toBeTruthy()
    expect(screen.getAllByRole("button", { name: "Approve this solution" })).toHaveLength(1)
  })

  it("sends an approval without marking the run approved or complete", async () => {
    setViewport("desktop")
    const calls = stubFetch((url) =>
      url === approvalUrl
        ? { status: 202, body: { run_id: run.run_id, status: "running" } }
        : { status: 200, body: run },
    )
    const { client } = renderPanel(run, { seed: true })

    await userEvent.click(button("Approve this solution"))

    await waitFor(() => expect(calls.some((call) => call.url === approvalUrl)).toBe(true))
    expect(calls.find((call) => call.url === approvalUrl)).toMatchObject({ method: "POST", body: { decision: "approve" } })
    expect(await screen.findByText(/Decision sent/)).toBeTruthy()
    expect(screen.getByRole("heading", { name: "Ready for your approval" })).toBeTruthy()
    expect(screen.queryByText("Completed")).toBeNull()
    expect((button("Approve this solution") as HTMLButtonElement).disabled).toBe(true)
    await waitFor(() => expect(client.getQueryState(runQueryKey(run.run_id))?.isInvalidated).toBe(true))
    expect(client.getQueryData(runQueryKey(run.run_id))).toEqual(run)
  })

  it("requires confirmation before rejecting", async () => {
    setViewport("desktop")
    const calls = stubFetch((url) =>
      url === approvalUrl ? { status: 202, body: { run_id: run.run_id, status: "failed" } } : { status: 200, body: run },
    )
    renderPanel(run)

    await userEvent.click(button("Reject this solution"))

    const dialog = await screen.findByRole("alertdialog", { name: "Reject this solution?" })
    expect(within(dialog).getByText("This will end the run and cannot be undone.")).toBeTruthy()
    expect(calls).toHaveLength(0)

    await userEvent.click(within(dialog).getByRole("button", { name: "Reject" }))

    await waitFor(() => expect(calls.find((call) => call.url === approvalUrl)?.body).toEqual({ decision: "reject" }))
  })

  it("can cancel a rejection without sending anything", async () => {
    setViewport("desktop")
    const calls = stubFetch(() => ({ status: 200, body: run }))
    renderPanel(run)

    await userEvent.click(button("Reject this solution"))
    const dialog = await screen.findByRole("alertdialog")
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull())
    expect(calls).toHaveLength(0)
  })

  it("shows a server conflict and never claims the decision succeeded", async () => {
    setViewport("desktop")
    stubFetch((url) =>
      url === approvalUrl ? { status: 409, body: { detail: "The approval request has expired." } } : { status: 200, body: run },
    )
    renderPanel(run)

    await userEvent.click(button("Approve this solution"))

    const alert = await screen.findByRole("alert")
    expect(alert.textContent).toBe("The approval request has expired.")
    expect(screen.queryByText(/Decision sent/)).toBeNull()
  })

  it("at zero, disables the decision and asks the server instead of marking the run expired", async () => {
    setViewport("desktop")
    const reached = waitingFor(waitingRun, { startedMsAgo: 11 * 60_000, expiresInMs: -1_000 })
    stubFetch(() => ({ status: 200, body: reached }))
    const { client } = renderPanel(reached, { seed: true })

    expect(await screen.findByText("Expiry being confirmed…")).toBeTruthy()
    expect((button("Approve this solution") as HTMLButtonElement).disabled).toBe(true)
    expect((button("Reject this solution") as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByRole("heading", { name: "Ready for your approval" })).toBeTruthy()
    expect(screen.queryByText("Approval expired")).toBeNull()
    await waitFor(() => expect(client.getQueryState(runQueryKey(reached.run_id))?.isInvalidated).toBe(true))
  })

  it("opens verification details on request", async () => {
    setViewport("desktop")
    stubFetch(() => ({ status: 200, body: run }))
    const { onShowDetails } = renderPanel(run)

    await userEvent.click(button("Verification details"))
    expect(onShowDetails).toHaveBeenCalledOnce()
  })
})

describe("outcomes", () => {
  const revisionBudgetRun: Run = {
    ...needsReviewRun,
    revision_count: 2,
    error: { code: "revision_budget_exhausted", message: "", stage: "reviewing" },
  }
  const unknownRun: Run = {
    ...needsReviewRun,
    error: { code: "something_new", message: "A new kind of failure.", stage: "reviewing" },
  }

  it.each([
    ["completed", completedRun, "Completed", "You approved this solution."],
    ["approval rejected", rejectedRun, "Approval rejected", "You chose not to accept this solution."],
    ["approval expired", expiredRun, "Approval expired", "The approval window ended before a decision was made."],
    ["sandbox unavailable", sandboxUnavailableRun, "Sandbox unavailable", "This does not indicate a problem with your code."],
    ["run timeout", timedOutDuringReExecutionRun, "Run timed out", "took longer than allowed"],
    ["revision budget exhausted", revisionBudgetRun, "Couldn't complete the repair", "couldn't get it verified"],
    ["needs human review", needsReviewRun, "Needs human review", "couldn't confirm"],
    ["internal failure", approvedThenFailedRun, "Internal failure", "internal problem"],
    ["unknown code", unknownRun, "Run failed", "ended without a result"],
  ] as const)("%s", (_, target, title, sentence) => {
    renderPanel(target)
    expect(screen.getByRole("heading", { name: title })).toBeTruthy()
    expect(screen.getByText(new RegExp(sentence.replace(/[.?]/g, "\\$&")))).toBeTruthy()
  })

  it("keeps technical information behind a disclosure, and never for a decision", () => {
    renderPanel(sandboxUnavailableRun)
    const code = screen.getByText("sandbox_unavailable")
    expect(code.closest("details")?.open).toBe(false)
    expect(document.body.textContent).not.toMatch(/docker|container|daemon/i)

    renderPanel(rejectedRun)
    expect(screen.queryAllByText("Technical details")).toHaveLength(1)
  })

  it("does not describe a rejection as a failure of the code", () => {
    renderPanel(rejectedRun)
    expect(document.body.textContent).not.toMatch(/fail|error|incorrect/i)
  })

  it("shows the test result and only non-zero repairs when completed", () => {
    renderPanel({ ...completedRun, revision_count: 1 })
    expect(screen.getByText(/2 \/ 2 tests passed/)).toBeTruthy()
    expect(screen.getByText(/verified on attempt 2/)).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/\d\/\d(?! tests)|0 retries/)
  })
})
