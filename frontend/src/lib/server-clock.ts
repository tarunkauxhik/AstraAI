/**
 * The server's clock, estimated from HTTP Date headers, so countdowns to server timestamps
 * don't depend on a wrong browser clock. Display only: expiry is always decided server-side.
 */

// Date headers have one-second resolution, so small offsets are noise, not skew.
const IGNORED_SKEW_MS = 2_000

let offsetMs = 0

export function recordServerDate(dateHeader: string | null, receivedAt: number = Date.now()): void {
  if (!dateHeader) return
  const serverMs = Date.parse(dateHeader)
  if (Number.isNaN(serverMs)) return
  // The header is truncated to the second; its midpoint is the best single estimate.
  const offset = serverMs + 500 - receivedAt
  offsetMs = Math.abs(offset) < IGNORED_SKEW_MS ? 0 : offset
}

/** Current time on the server's clock, in epoch milliseconds. */
export function serverNow(localNow: number = Date.now()): number {
  return localNow + offsetMs
}

export function resetServerClock(): void {
  offsetMs = 0
}
