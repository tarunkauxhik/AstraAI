import { useEffect } from "react"
import { useQuery } from "@tanstack/react-query"

import { api, type ApiError } from "@/api/client"
import type { Run } from "@/api/types"
import { pollInterval } from "@/lib/run-view"

export const runQueryKey = (runId: string) => ["run", runId] as const

// Per-run polling hints. Module state is enough: one browser tab, a handful of runs.
const consecutiveFailures = new Map<string, number>()
const boostedUntil = new Map<string, number>()

/** Poll quickly for a while, e.g. right after an approval decision. */
export function boostRunPolling(runId: string, durationMs = 10_000): void {
  boostedUntil.set(runId, Date.now() + durationMs)
}

/** Poll one run with a phase-aware interval (see pollInterval). */
export function useRun(runId: string) {
  useEffect(
    () => () => {
      consecutiveFailures.delete(runId)
      boostedUntil.delete(runId)
    },
    [runId],
  )

  return useQuery<Run, ApiError>({
    queryKey: runQueryKey(runId),
    queryFn: async ({ signal }) => {
      try {
        const run = await api.getRun(runId, signal)
        consecutiveFailures.set(runId, 0)
        return run
      } catch (error) {
        consecutiveFailures.set(runId, (consecutiveFailures.get(runId) ?? 0) + 1)
        throw error
      }
    },
    // Each poll is a single request; backoff between polls comes from pollInterval.
    retry: false,
    refetchOnWindowFocus: true,
    // Keep polling (slowly) in a hidden tab so a waiting approval isn't missed on return.
    refetchIntervalInBackground: true,
    refetchInterval: (query) =>
      pollInterval(query.state.data, query.state.error, {
        hidden: typeof document !== "undefined" && document.hidden,
        boosted: (boostedUntil.get(runId) ?? 0) > Date.now(),
        failures: consecutiveFailures.get(runId) ?? 0,
      }),
  })
}
