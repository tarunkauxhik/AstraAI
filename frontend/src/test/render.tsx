import type { ReactElement } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render } from "@testing-library/react"
import { afterEach, vi } from "vitest"

import type { Run } from "@/api/types"

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

/** Render inside a fresh QueryClient; `run` seeds that run's query before the first render. */
export function renderWithClient(ui: ReactElement, { run }: { run?: Run } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  if (run) client.setQueryData(["run", run.run_id], run)
  return { client, ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>) }
}

type Responder = (url: string, init?: RequestInit) => { status: number; body: unknown }

/** A fetch stub that records calls and answers each with the responder's JSON. */
export function stubFetch(responder: Responder) {
  const calls: { url: string; method: string; body: unknown }[] = []
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({
      url,
      method: init?.method ?? "GET",
      body: typeof init?.body === "string" ? JSON.parse(init.body) : null,
    })
    const { status, body } = responder(url, init)
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })
  })
  vi.stubGlobal("fetch", fetchMock)
  return calls
}

/** A waiting run whose approval window is relative to now, so countdowns are realistic. */
export function waitingFor(run: Run, { startedMsAgo, expiresInMs }: { startedMsAgo: number; expiresInMs: number }): Run {
  const now = Date.now()
  return {
    ...run,
    approval_requested_at: new Date(now - startedMsAgo).toISOString(),
    approval_expires_at: new Date(now + expiresInMs).toISOString(),
  }
}
