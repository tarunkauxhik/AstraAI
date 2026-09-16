import { afterEach, describe, expect, it, vi } from "vitest"

import { api, ApiError, NETWORK_ERROR_DETAIL, toApiError } from "@/api/client"

function jsonResponse(status: number, body: unknown, headers?: Record<string, string>) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  })
}

describe("toApiError", () => {
  it("keeps the server's string detail", async () => {
    const error = await toApiError(jsonResponse(409, { detail: "The approval request has expired." }))
    expect(error).toMatchObject({ kind: "http", status: 409, detail: "The approval request has expired." })
  })

  it("turns FastAPI validation errors into field errors without echoing input", async () => {
    const error = await toApiError(
      jsonResponse(422, {
        detail: [
          {
            type: "string_too_short",
            loc: ["body", "task"],
            msg: "String should have at least 1 character",
            input: "SECRET TASK TEXT",
          },
        ],
      }),
    )
    expect(error.fieldErrors).toEqual([
      { field: "task", message: "String should have at least 1 character" },
    ])
    expect(JSON.stringify(error)).not.toContain("SECRET TASK TEXT")
    expect(error.detail).not.toContain("SECRET")
  })

  it("reads Retry-After on 429", async () => {
    const error = await toApiError(
      jsonResponse(429, { detail: "Too many runs are waiting. Try again shortly." }, { "Retry-After": "30" }),
    )
    expect(error.retryAfterSeconds).toBe(30)
  })

  it("does not surface non-JSON bodies such as proxy error pages", async () => {
    const error = await toApiError(new Response("<html>Bad gateway: docker internals</html>", { status: 502 }))
    expect(error.detail).toBe("The AstraAi service is unavailable right now.")
  })

  it("flags 404", async () => {
    const error = await toApiError(jsonResponse(404, { detail: "Run not found." }))
    expect(error.isNotFound).toBe(true)
  })
})

describe("api", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("calls same-origin /api paths", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(202, { run_id: "r1", status: "queued" }))
    vi.stubGlobal("fetch", fetchMock)

    await expect(api.createRun({ task: "Reverse", language: "python" })).resolves.toEqual({
      run_id: "r1",
      status: "queued",
    })
    await api.decideApproval("a/b", "approve").catch(() => undefined)

    expect(fetchMock.mock.calls[0][0]).toBe("/api/runs")
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ task: "Reverse", language: "python" })
    expect(fetchMock.mock.calls[1][0]).toBe("/api/runs/a%2Fb/approval")
  })

  it("normalizes network failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")))

    const error = await api.getRun("r1").catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ kind: "network", status: 0, detail: NETWORK_ERROR_DETAIL })
  })
})
