import type {
  ApprovalDecision,
  HealthResponse,
  Run,
  RunAccepted,
  RunRequest,
} from "@/api/types"
import { recordServerDate } from "@/lib/server-clock"

/** Same-origin prefix. In development Vite proxies it to FastAPI (vite.config.ts). */
const API_BASE = "/api"

export interface FieldError {
  /** Dotted body path, e.g. "task" or "decision". */
  field: string
  message: string
}

export type ApiErrorKind = "network" | "http"

/** Every failed request becomes one of these; raw server bodies are never shown as-is. */
export class ApiError extends Error {
  readonly kind: ApiErrorKind
  /** HTTP status, or 0 when the request never got a response. */
  readonly status: number
  readonly detail: string
  readonly fieldErrors: FieldError[]
  readonly retryAfterSeconds: number | null

  constructor(options: {
    kind: ApiErrorKind
    status: number
    detail: string
    fieldErrors?: FieldError[]
    retryAfterSeconds?: number | null
  }) {
    super(options.detail)
    this.name = "ApiError"
    this.kind = options.kind
    this.status = options.status
    this.detail = options.detail
    this.fieldErrors = options.fieldErrors ?? []
    this.retryAfterSeconds = options.retryAfterSeconds ?? null
  }

  get isNotFound(): boolean {
    return this.status === 404
  }
}

export const NETWORK_ERROR_DETAIL =
  "Can't reach the AstraAi service. Check that the backend is running."
const UNAVAILABLE_DETAIL = "The AstraAi service is unavailable right now."
const INVALID_REQUEST_DETAIL = "The request was not valid."

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

/** FastAPI 422 items look like {loc: ["body", "task"], msg, ...}; `input` is ignored. */
function toFieldErrors(detail: unknown[]): FieldError[] {
  return detail.filter(isRecord).map((item) => {
    const loc = Array.isArray(item.loc) ? item.loc : []
    const path = loc[0] === "body" ? loc.slice(1) : loc
    return {
      field: path.map(String).join(".") || "request",
      message: typeof item.msg === "string" ? item.msg : "Invalid value.",
    }
  })
}

function retryAfter(response: Response): number | null {
  const header = response.headers.get("retry-after")
  if (header === null) return null
  const seconds = Number(header)
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null
}

/** Normalize a non-2xx response into an ApiError. */
export async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // Not JSON: for example a proxy error page while the backend is down.
  }
  const detail = isRecord(body) ? body.detail : undefined

  if (Array.isArray(detail)) {
    return new ApiError({
      kind: "http",
      status: response.status,
      detail: INVALID_REQUEST_DETAIL,
      fieldErrors: toFieldErrors(detail),
    })
  }
  const fallback =
    response.status >= 500 ? UNAVAILABLE_DETAIL : `Request failed (${response.status}).`
  return new ApiError({
    kind: "http",
    status: response.status,
    detail: typeof detail === "string" && detail.trim() ? detail : fallback,
    retryAfterSeconds: retryAfter(response),
  })
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...init?.headers },
    })
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause
    throw new ApiError({ kind: "network", status: 0, detail: NETWORK_ERROR_DETAIL })
  }
  recordServerDate(response.headers.get("date"))
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as T
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

export const api = {
  health: (signal?: AbortSignal) => request<HealthResponse>("/health", { signal }),

  createRun: (body: RunRequest) => postJson<RunAccepted>("/runs", body),

  getRun: (runId: string, signal?: AbortSignal) =>
    request<Run>(`/runs/${encodeURIComponent(runId)}`, { signal }),

  decideApproval: (runId: string, decision: ApprovalDecision) =>
    postJson<RunAccepted>(`/runs/${encodeURIComponent(runId)}/approval`, { decision }),
}
