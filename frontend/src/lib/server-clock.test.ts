import { afterEach, describe, expect, it } from "vitest"

import { recordServerDate, resetServerClock, serverNow } from "@/lib/server-clock"

describe("server clock", () => {
  afterEach(() => resetServerClock())

  const local = Date.parse("2026-09-16T12:00:00.000Z")

  it("corrects for real skew reported by the Date header", () => {
    // The server is five minutes ahead of this browser.
    recordServerDate("Wed, 16 Sep 2026 12:05:00 GMT", local)
    expect(serverNow(local)).toBe(local + 5 * 60_000 + 500)
  })

  it("ignores sub-second header noise", () => {
    recordServerDate("Wed, 16 Sep 2026 12:00:01 GMT", local)
    expect(serverNow(local)).toBe(local)
  })

  it("ignores missing or unparseable headers", () => {
    recordServerDate(null, local)
    recordServerDate("not a date", local)
    expect(serverNow(local)).toBe(local)
  })
})
