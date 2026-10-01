// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { createMemoryRouter, RouterProvider } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"

import { NewRunPage } from "@/routes/NewRunPage"
import { stubFetch } from "@/test/render"

// U+1F600 is one code point (what the backend's Python len() counts) but two UTF-16 units.
const EMOJI = "\u{1F600}"
const QUESTION = "What should AstraAi solve?"
const PROMISE = "Describe a small change. Get a tested patch."

afterEach(() => window.localStorage.clear())

/** The start page, on a device whose last task was solving a problem unless told otherwise. */
function renderPage({
  healthy = true,
  state,
  mode = "solve",
}: { healthy?: boolean; state?: unknown; mode?: "solve" | "develop" | null } = {}) {
  if (mode) window.localStorage.setItem("astraai:mode", mode)
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
    { initialEntries: [{ pathname: "/", state }] },
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  const task = screen.queryByRole("textbox", { name: QUESTION })!
  const submit = () => fireEvent.click(screen.getByRole("button", { name: "Solve" }))
  const posts = () => calls.filter((call) => call.method === "POST")
  return { task, submit, posts }
}

describe("new run", () => {
  it("is one question, a task box, a language choice and one action", () => {
    renderPage()

    expect(screen.getByRole("heading", { level: 1, name: PROMISE })).toBeTruthy()
    expect(screen.getByRole("textbox", { name: QUESTION })).toBeTruthy()
    expect(screen.getByText(/It generates, tests and reviews a solution/)).toBeTruthy()
    expect(screen.getByText(/Describe one self-contained function/)).toBeTruthy()
    expect(screen.getByRole("radiogroup", { name: "Language" })).toBeTruthy()
    const solve = screen.getByRole("button", { name: "Solve" })
    // The shortcut is shown next to the action and announced as a key shortcut.
    expect(solve.getAttribute("aria-keyshortcuts")).toBe("Control+Enter Meta+Enter")
    expect(solve.querySelector("kbd")?.textContent).toMatch(/↵/)
    // No flow chips, counter or service chatter while everything is fine.
    expect(document.body.textContent).not.toMatch(/sandbox|20,000|Service online|Sandbox run/i)
  })

  it("says what AstraAi does first, and starts with changing a repository", () => {
    renderPage({ mode: null })

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(PROMISE)
    const kinds = screen.getAllByRole("radio").slice(0, 2)
    expect(kinds.map((kind) => kind.textContent)).toEqual(["Change a repository", "Solve a coding problem"])
    expect(kinds[0].getAttribute("aria-checked")).toBe("true")
    expect(document.body.textContent).not.toMatch(/Develop a repository/)
  })

  it("remembers the kind of task last started on this device", () => {
    renderPage({ mode: null })
    fireEvent.click(screen.getByRole("radio", { name: "Solve a coding problem" }))
    expect(window.localStorage.getItem("astraai:mode")).toBe("solve")

    cleanup()
    window.localStorage.removeItem("astraai:language")
    renderPage({ mode: null })
    expect(screen.getByRole("radio", { name: "Solve a coding problem" }).getAttribute("aria-checked")).toBe("true")
  })

  it("submits with Ctrl+Enter from the task box", async () => {
    const { task, posts } = renderPage()

    fireEvent.change(task, { target: { value: "Reverse a string." } })
    fireEvent.keyDown(task, { key: "Enter", ctrlKey: true })

    await waitFor(() => expect(posts()).toHaveLength(1))
  })

  it("opens with the task and language of a run being edited", () => {
    // Editing a solved problem stays a problem, whatever this device did last.
    const { task } = renderPage({
      mode: "develop",
      state: { task: "Reverse a string, keeping emoji intact.", language: "cpp" },
    })

    expect((task as HTMLTextAreaElement).value).toBe("Reverse a string, keeping emoji intact.")
    expect(screen.getByRole("radio", { name: "C++" }).getAttribute("aria-checked")).toBe("true")
  })

  it("remembers the last language chosen on this device", () => {
    renderPage()
    fireEvent.click(screen.getByRole("radio", { name: "C++" }))
    expect(window.localStorage.getItem("astraai:language")).toBe("cpp")

    cleanup()
    renderPage()
    expect(screen.getByRole("radio", { name: "C++" }).getAttribute("aria-checked")).toBe("true")
  })

  it("is ready to type with a mouse, but doesn't pop up a phone keyboard", () => {
    const pointer = (fine: boolean) =>
      vi.stubGlobal("matchMedia", (query: string) => ({ matches: fine && query === "(pointer: fine)" }))

    pointer(true)
    const { task } = renderPage()
    expect(document.activeElement).toBe(task)

    cleanup()
    pointer(false)
    const touch = renderPage()
    expect(document.activeElement).not.toBe(touch.task)
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
