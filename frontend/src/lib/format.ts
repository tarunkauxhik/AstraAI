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

/**
 * The headline test result: "8 / 8 tests passed" when every reported case passed, otherwise
 * the counts as reported. Null when the sandbox reported no counts.
 */
export function formatTestResult(passed: number | null, failed: number | null): string | null {
  if (passed !== null && failed === 0) return `${passed} / ${passed} tests passed`
  return formatTestCounts(passed, failed)
}

/** "1 revision", "0 retries". Counts only: the frontend never claims a server-side limit. */
export function formatCount(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`
}

