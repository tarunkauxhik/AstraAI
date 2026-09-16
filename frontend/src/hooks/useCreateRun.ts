import { useMutation } from "@tanstack/react-query"

import { api, type ApiError } from "@/api/client"
import type { RunAccepted, RunRequest } from "@/api/types"

export function useCreateRun() {
  return useMutation<RunAccepted, ApiError, RunRequest>({
    mutationFn: (request) => api.createRun(request),
  })
}
