const dateTime = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "medium",
})

export function formatDateTime(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : dateTime.format(date)
}

/** "342 ms", "4.2 s", "3m 07s". */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(1)} s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${String(Math.floor(seconds % 60)).padStart(2, "0")}s`
}

/** "in 9 min", "2 min ago". Coarse on purpose: informational, never a deadline check. */
export function formatRelative(iso: string, now: number = Date.now()): string {
  const diff = new Date(iso).getTime() - now
  if (Number.isNaN(diff)) return ""
  const minutes = Math.round(Math.abs(diff) / 60_000)
  const amount = minutes < 1 ? "less than a minute" : `${minutes} min`
  return diff >= 0 ? `in ${amount}` : `${amount} ago`
}

/**
 * Test counts exactly as reported. The sandbox only prints a total when every case
 * passes, so a total is never invented from partial numbers.
 */
export function formatTestCounts(
  passed: number | null,
  failed: number | null,
): string | null {
  if (passed !== null && failed !== null) return `${passed} passed · ${failed} failed`
  if (passed !== null) return `${passed} passed`
  if (failed !== null) return `${failed} failing`
  return null
}

export function shortId(runId: string): string {
  return runId.slice(0, 8)
}
