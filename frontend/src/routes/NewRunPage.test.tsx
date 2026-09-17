// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { createMemoryRouter, RouterProvider } from "react-router"
import { describe, expect, it } from "vitest"

import { NewRunPage } from "@/routes/NewRunPage"
import { stubFetch } from "@/test/render"

// U+1F600 is one code point (what the backend's Python len() counts) but two UTF-16 units.
const EMOJI = "\u{1F600}"
const QUESTION = "What do you want AstraAi to solve?"

function renderPage({ healthy = true }: { healthy?: boolean } = {}) {
  const calls = stubFetch((url) =>
    url === "/api/runs"
      ? { status: 202, body: { run_id: "new-run", status: "queued" } }
      : healthy
        ? { status: 200, body: { status: "ok", service: "astraai" } }
        : { status: 503, body: { detail: "down" } },
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
  const task = screen.getByRole("textbox", { name: QUESTION })
  const submit = () => fireEvent.click(screen.getByRole("button", { name: "Run with AstraAi" }))
  const posts = () => calls.filter((call) => call.method === "POST")
  return { task, submit, posts }
}

describe("new run", () => {
  it("is one question, a task box, a language choice and one action", () => {
    renderPage()

    expect(screen.getByRole("heading", { level: 1, name: QUESTION })).toBeTruthy()
    expect(screen.getByText("AstraAi writes tests and code, checks the result, and asks before accepting it.")).toBeTruthy()
    expect(screen.getByRole("radiogroup", { name: "Language" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "Run with AstraAi" })).toBeTruthy()
    // No flow chips, counter or service chatter while everything is fine.
    expect(document.body.textContent).not.toMatch(/sandbox|20,000|Service online|Sandbox run/i)
  })

  it("mentions the service only when it can't be reached", async () => {
    renderPage({ healthy: false })
    expect(await screen.findByText("Can't reach AstraAi")).toBeTruthy()
  })

  it("asks for a task only after an attempt to run an empty one", () => {
    const { submit, posts } = renderPage()

    expect(screen.queryByText("Describe what you want AstraAi to solve.")).toBeNull()
    submit()

    expect(screen.getByText("Describe what you want AstraAi to solve.")).toBeTruthy()
    expect(posts()).toHaveLength(0)
  })
})

describe("task length", () => {
  it("hides the counter for ordinary tasks", () => {
    const { task } = renderPage()

    fireEvent.change(task, { target: { value: "Reverse a string." } })

    expect(screen.queryByText(/\/ 20,000/)).toBeNull()
  })

  it("shows the counter near the limit, counting code points after trimming like the backend", () => {
    const { task } = renderPage()

    fireEvent.change(task, { target: { value: `  ${EMOJI.repeat(18_000)} \n` } })

    expect(screen.getByText("18,000 / 20,000")).toBeTruthy()
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
    expect(screen.getByText("20,001 / 20,000")).toBeTruthy()
    expect(posts()).toHaveLength(0)
  })
})
