// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { createMemoryRouter, RouterProvider } from "react-router"
import { describe, expect, it } from "vitest"

import { NewRunPage } from "@/routes/NewRunPage"
import { stubFetch } from "@/test/render"

// U+1F600 is one code point (what the backend's Python len() counts) but two UTF-16 units.
const EMOJI = "\u{1F600}"

function renderPage() {
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
    { initialEntries: ["/"] },
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  const task = screen.getByRole("textbox", { name: "Task" })
  const submit = () => fireEvent.click(screen.getByRole("button", { name: "Start run" }))
  const posts = () => calls.filter((call) => call.method === "POST")
  return { task, submit, posts }
}

describe("task length", () => {
  it("counts code points after trimming, like the backend", () => {
    const { task } = renderPage()

    fireEvent.change(task, { target: { value: `  ${EMOJI.repeat(3)}abc \n` } })

    expect(screen.getByText("6 / 20,000")).toBeTruthy()
  })

  it("accepts 20,000 code points even when they are 40,000 UTF-16 units", async () => {
    const { task, submit, posts } = renderPage()
    const value = EMOJI.repeat(20_000)
    expect(value.length).toBe(40_000)

    fireEvent.change(task, { target: { value } })
    submit()

    expect(screen.getByText("20,000 / 20,000")).toBeTruthy()
    expect(screen.queryByText(/too long/)).toBeNull()
    await waitFor(() => expect(posts()).toHaveLength(1))
    expect(posts()[0].body).toEqual({ task: value, language: "python" })
    expect(await screen.findByText("Run page")).toBeTruthy()
  })

  it("rejects a task over the limit without sending it", () => {
    const { task, submit, posts } = renderPage()

    fireEvent.change(task, { target: { value: `${EMOJI.repeat(20_000)}a` } })
    submit()

    expect(screen.getByText("The task is too long: 20,001 of 20,000 characters.")).toBeTruthy()
    expect(posts()).toHaveLength(0)
  })
})
