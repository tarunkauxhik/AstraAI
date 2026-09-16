import { useMutation, useQueryClient } from "@tanstack/react-query"

import { api, type ApiError } from "@/api/client"
import type { ApprovalDecision, RunAccepted } from "@/api/types"
import { boostRunPolling, runQueryKey } from "@/hooks/useRun"

/**
 * Send an approval decision. Nothing is changed locally: whatever the outcome (202, 409,
 * 429, network error), the run is refetched and the server's state is what the UI shows.
 */
export function useApproval(runId: string) {
  const queryClient = useQueryClient()
  return useMutation<RunAccepted, ApiError, ApprovalDecision>({
    mutationFn: (decision) => api.decideApproval(runId, decision),
    onSettled: () => {
      boostRunPolling(runId)
      return queryClient.invalidateQueries({ queryKey: runQueryKey(runId) })
    },
  })
}
