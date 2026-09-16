// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { RunStatusPanel } from "@/components/run/RunStatusPanel"
import { runQueryKey } from "@/hooks/useRun"
import { expiredRun, waitingRun } from "@/test/fixtures"
import { renderWithClient, stubFetch, waitingFor } from "@/test/render"

const run = waitingFor(waitingRun, { startedMsAgo: 60_000, expiresInMs: 9 * 60_000 })
const approvalUrl = `/api/runs/${run.run_id}/approval`

/** The first (inline) instance; the sticky phone bar renders a second, hidden by CSS. */
function button(name: string) {
  return screen.getAllByRole("button", { name })[0]
}

describe("approval panel", () => {
  it("shows what the user is approving", () => {
    stubFetch(() => ({ status: 200, body: run }))
    renderWithClient(<RunStatusPanel run={run} />)

    expect(screen.getByText("Verified by AstraAi")).toBeTruthy()
    expect(screen.getByRole("heading", { name: "Waiting for your approval" })).toBeTruthy()
    expect(screen.getByText(run.approval_request!.problem_summary)).toBeTruthy()
    expect(screen.getByText(/2 passed · 0 failed/)).toBeTruthy()
    expect(screen.getByText(run.approval_request!.critic_reason)).toBeTruthy()
    expect(screen.getByText("0/2 revisions · 0/1 retries")).toBeTruthy()
    expect(screen.getAllByRole("timer", { name: "Time left to decide" })[0].textContent).toMatch(/^\d:\d\d$/)
    expect((button("Approve this solution") as HTMLButtonElement).disabled).toBe(false)
  })

  it("sends an approval without marking the run approved or complete", async () => {
    const calls = stubFetch((url) =>
      url === approvalUrl
        ? { status: 202, body: { run_id: run.run_id, status: "running" } }
        : { status: 200, body: run },
    )
    const { client } = renderWithClient(<RunStatusPanel run={run} />, { run })

    await userEvent.click(button("Approve this solution"))

    await waitFor(() => expect(calls.some((call) => call.url === approvalUrl)).toBe(true))
    expect(calls.find((call) => call.url === approvalUrl)).toMatchObject({
      method: "POST",
      body: { decision: "approve" },
    })
    // Only a server refetch may change the run; the panel stays as the server reported it.
    expect(await screen.findByText(/Decision sent/)).toBeTruthy()
    expect(screen.getByRole("heading", { name: "Waiting for your approval" })).toBeTruthy()
    expect(screen.queryByText("Completed")).toBeNull()
    expect((button("Approve this solution") as HTMLButtonElement).disabled).toBe(true)
    // The run is marked for an immediate refetch; the page's poller then shows the server state.
    await waitFor(() => expect(client.getQueryState(runQueryKey(run.run_id))?.isInvalidated).toBe(true))
    expect(client.getQueryData(runQueryKey(run.run_id))).toEqual(run)
  })

  it("requires confirmation before rejecting", async () => {
    const calls = stubFetch((url) =>
      url === approvalUrl
        ? { status: 202, body: { run_id: run.run_id, status: "failed" } }
        : { status: 200, body: run },
    )
    renderWithClient(<RunStatusPanel run={run} />)

    await userEvent.click(button("Reject this solution"))

    const dialog = await screen.findByRole("alertdialog", { name: "Reject this solution?" })
    expect(within(dialog).getByText(/Rejecting ends the run/)).toBeTruthy()
    expect(calls).toHaveLength(0)

    await userEvent.click(within(dialog).getByRole("button", { name: "Reject solution" }))

    await waitFor(() =>
      expect(calls.find((call) => call.url === approvalUrl)?.body).toEqual({ decision: "reject" }),
    )
  })

  it("can back out of rejecting without sending anything", async () => {
    const calls = stubFetch(() => ({ status: 200, body: run }))
    renderWithClient(<RunStatusPanel run={run} />)

    await userEvent.click(button("Reject this solution"))
    const dialog = await screen.findByRole("alertdialog")
    await userEvent.click(within(dialog).getByRole("button", { name: "Keep reviewing" }))

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull())
    expect(calls).toHaveLength(0)
  })

  it("shows a server conflict and never claims the decision succeeded", async () => {
    stubFetch((url) =>
      url === approvalUrl
        ? { status: 409, body: { detail: "The approval request has expired." } }
        : { status: 200, body: run },
    )
    renderWithClient(<RunStatusPanel run={run} />)

    await userEvent.click(button("Approve this solution"))

    const alert = await screen.findByRole("alert")
    expect(alert.textContent).toBe("The approval request has expired.")
    expect(screen.queryByText(/Decision sent/)).toBeNull()
  })

  it("at zero, disables the decision and asks the server instead of marking the run expired", async () => {
    const reached = waitingFor(waitingRun, { startedMsAgo: 11 * 60_000, expiresInMs: -1_000 })
    stubFetch(() => ({ status: 200, body: reached }))
    const { client } = renderWithClient(<RunStatusPanel run={reached} />, { run: reached })

    expect((await screen.findAllByText("Expiry being confirmed…")).length).toBeGreaterThan(0)
    expect((button("Approve this solution") as HTMLButtonElement).disabled).toBe(true)
    expect((button("Reject this solution") as HTMLButtonElement).disabled).toBe(true)
    // Still the server's waiting state: no local "expired" outcome.
    expect(screen.getByRole("heading", { name: "Waiting for your approval" })).toBeTruthy()
    expect(screen.queryByText("Approval expired")).toBeNull()
    await waitFor(() => expect(client.getQueryState(runQueryKey(reached.run_id))?.isInvalidated).toBe(true))
  })

  it("shows Approval expired only when the server reports it", () => {
    stubFetch(() => ({ status: 200, body: expiredRun }))
    renderWithClient(<RunStatusPanel run={expiredRun} />)

    expect(screen.getByRole("heading", { name: "Approval expired" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Approve this solution" })).toBeNull()
  })
})
