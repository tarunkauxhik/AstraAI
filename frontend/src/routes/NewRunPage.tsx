import { useId, useState, type FormEvent } from "react"
import { useQuery } from "@tanstack/react-query"
import { Loader2, WifiOff } from "lucide-react"
import { useNavigate } from "react-router"

import { api } from "@/api/client"
import { TASK_MAX_LENGTH, type Language } from "@/api/types"
import { Brand } from "@/components/Brand"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useCreateRun } from "@/hooks/useCreateRun"
import { cn } from "@/lib/utils"

/** The counter only appears once the task is long enough for the limit to matter. */
const COUNTER_THRESHOLD = Math.floor(TASK_MAX_LENGTH * 0.9)

/** Says nothing while the service is reachable; only an outage is worth the space. */
function ServiceWarning() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => api.health(signal),
    retry: false,
    refetchInterval: 30_000,
  })
  if (!health.isError) return null
  return (
    <Alert className="mb-6">
      <WifiOff aria-hidden="true" />
      <AlertTitle>Can't reach AstraAi</AlertTitle>
      <AlertDescription>The service isn't responding right now. Your task will be kept here.</AlertDescription>
    </Alert>
  )
}

export function NewRunPage() {
  const navigate = useNavigate()
  const createRun = useCreateRun()
  const [task, setTask] = useState("")
  const [language, setLanguage] = useState<Language>("python")
  const [attempted, setAttempted] = useState(false)
  const taskId = useId()
  const hintId = useId()
  const counterId = useId()
  const errorId = useId()

  // Mirrors the backend: strip, then count code points (Python len()), not UTF-16 units.
  // The server rechecks.
  const length = [...task.trim()].length
  const localError =
    length === 0
      ? "Describe what you want AstraAi to solve."
      : length > TASK_MAX_LENGTH
        ? `The task is too long: ${length.toLocaleString()} of ${TASK_MAX_LENGTH.toLocaleString()} characters.`
        : null
  const serverFieldError = createRun.error?.fieldErrors.find((item) => item.field === "task")?.message
  // An empty box isn't an error until the user tries to run it; an over-long one is at once.
  const taskError =
    (localError && (attempted || length > TASK_MAX_LENGTH) ? localError : null) ?? serverFieldError ?? null
  const generalError = createRun.error && !serverFieldError ? createRun.error : null
  const showCounter = length >= COUNTER_THRESHOLD

  function submit(event?: FormEvent) {
    event?.preventDefault()
    setAttempted(true)
    if (localError || createRun.isPending) return
    createRun.mutate({ task, language }, { onSuccess: (accepted) => navigate(`/runs/${accepted.run_id}`) })
  }

  const describedBy = [hintId, showCounter && counterId, taskError && errorId].filter(Boolean).join(" ")

  return (
    <div className="mx-auto flex min-h-dvh max-w-2xl flex-col px-4 pb-10 sm:px-6">
      <header className="flex h-14 items-center">
        <Brand />
      </header>

      <main className="flex-1 pt-10 sm:pt-20">
        <ServiceWarning />
        <form onSubmit={submit} noValidate className="space-y-5">
          <div className="space-y-2">
            <h1>
              <label htmlFor={taskId} className="text-2xl font-semibold tracking-tight">
                What do you want AstraAi to solve?
              </label>
            </h1>
            <p id={hintId} className="text-muted-foreground">
              AstraAi writes tests and code, checks the result, and asks before accepting it.
            </p>
          </div>

          <div className="space-y-2">
            <Textarea
              id={taskId}
              value={task}
              onChange={(event) => setTask(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) submit()
              }}
              placeholder="For example: write a function that returns the indices of the two numbers in a list that add up to a target."
              rows={8}
              aria-invalid={taskError ? true : undefined}
              aria-describedby={describedBy}
              className="min-h-44 resize-y text-base leading-7"
            />
            {(taskError || showCounter) && (
              <div className="flex items-start justify-between gap-4 text-sm">
                <p id={errorId} className="text-destructive">
                  {taskError}
                </p>
                {showCounter && (
                  <p
                    id={counterId}
                    className={cn("shrink-0 font-mono text-xs text-muted-foreground", length > TASK_MAX_LENGTH && "text-destructive")}
                  >
                    {length.toLocaleString()} / {TASK_MAX_LENGTH.toLocaleString()}
                  </p>
                )}
              </div>
            )}
          </div>

          {generalError && (
            <Alert variant="destructive">
              <AlertTitle>{generalError.status === 429 ? "AstraAi is busy" : "Couldn't start the run"}</AlertTitle>
              <AlertDescription>
                {generalError.detail}
                {generalError.retryAfterSeconds !== null && ` Try again in ${generalError.retryAfterSeconds} seconds.`}
              </AlertDescription>
            </Alert>
          )}

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <ToggleGroup
              type="single"
              variant="outline"
              value={language}
              onValueChange={(value) => value && setLanguage(value as Language)}
              aria-label="Language"
            >
              <ToggleGroupItem
                value="python"
                className="px-4 data-[state=on]:border-brand/60 data-[state=on]:bg-brand/10 data-[state=on]:text-foreground"
              >
                Python
              </ToggleGroupItem>
              <ToggleGroupItem
                value="cpp"
                className="px-4 data-[state=on]:border-brand/60 data-[state=on]:bg-brand/10 data-[state=on]:text-foreground"
              >
                C++
              </ToggleGroupItem>
            </ToggleGroup>
            <Button
              type="submit"
              size="lg"
              disabled={createRun.isPending}
              aria-keyshortcuts="Control+Enter Meta+Enter"
              className="w-full px-5 sm:w-auto"
            >
              {createRun.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
              {createRun.isPending ? "Starting…" : "Run with AstraAi"}
            </Button>
          </div>
        </form>
      </main>
    </div>
  )
}
