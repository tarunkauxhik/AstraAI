import { useId, useState, type FormEvent } from "react"
import { useQuery } from "@tanstack/react-query"
import { ArrowRight, Loader2 } from "lucide-react"
import { useNavigate } from "react-router"

import { api } from "@/api/client"
import { TASK_MAX_LENGTH, type Language } from "@/api/types"
import { Brand } from "@/components/Brand"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useCreateRun } from "@/hooks/useCreateRun"
import { cn } from "@/lib/utils"

const FLOW = ["Describe the problem", "Tests + code", "Sandbox run + review", "Your approval"]

function ServiceStatus() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => api.health(signal),
    retry: false,
    refetchInterval: 30_000,
  })
  const online = health.isSuccess
  const label = health.isPending ? "Checking service" : online ? "Service online" : "Service unreachable"
  return (
    <span className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
      <span
        aria-hidden="true"
        className={cn(
          "size-1.5 rounded-full",
          health.isPending ? "bg-muted-foreground" : online ? "bg-success" : "bg-destructive",
        )}
      />
      {label}
    </span>
  )
}

export function NewRunPage() {
  const navigate = useNavigate()
  const createRun = useCreateRun()
  const [task, setTask] = useState("")
  const [language, setLanguage] = useState<Language>("python")
  const [touched, setTouched] = useState(false)
  const taskId = useId()
  const hintId = useId()
  const errorId = useId()

  // Mirrors the backend: strip, then count code points (Python len()), not UTF-16 units.
  // The server rechecks.
  const length = [...task.trim()].length
  const localError =
    length === 0
      ? "Describe the coding task."
      : length > TASK_MAX_LENGTH
        ? `The task is too long: ${length.toLocaleString()} of ${TASK_MAX_LENGTH.toLocaleString()} characters.`
        : null
  const serverFieldError = createRun.error?.fieldErrors.find((item) => item.field === "task")?.message
  const taskError = (touched && localError) || serverFieldError || null
  const generalError =
    createRun.error && !serverFieldError ? createRun.error : null

  function submit(event?: FormEvent) {
    event?.preventDefault()
    setTouched(true)
    if (localError || createRun.isPending) return
    createRun.mutate(
      { task, language },
      { onSuccess: (accepted) => navigate(`/runs/${accepted.run_id}`) },
    )
  }

  return (
    <div className="mx-auto flex min-h-dvh max-w-3xl flex-col px-4 pb-10 sm:px-6">
      <header className="flex h-14 items-center justify-between">
        <Brand />
        <ServiceStatus />
      </header>

      <main className="flex-1 pt-8 sm:pt-14">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">New run</h1>
        <p className="mt-2 max-w-2xl text-muted-foreground">
          Describe a standalone coding problem. AstraAi writes tests and a solution, runs them in
          an isolated sandbox, reviews the result, repairs it if needed, and asks for your
          approval.
        </p>
        <ol className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          {FLOW.map((step, index) => (
            <li key={step} className="flex items-center gap-2">
              <span className="rounded-md border px-2 py-0.5">{step}</span>
              {index < FLOW.length - 1 && <ArrowRight className="size-3" aria-hidden="true" />}
            </li>
          ))}
        </ol>

        <form onSubmit={submit} noValidate className="mt-8 space-y-5">
          <div className="space-y-2">
            <div className="flex items-end justify-between gap-4">
              <Label htmlFor={taskId}>Task</Label>
              <span
                id={hintId}
                className={cn(
                  "font-mono text-xs text-muted-foreground",
                  length > TASK_MAX_LENGTH && "text-destructive",
                )}
              >
                {length.toLocaleString()} / {TASK_MAX_LENGTH.toLocaleString()}
              </span>
            </div>
            <Textarea
              id={taskId}
              value={task}
              onChange={(event) => setTask(event.target.value)}
              onBlur={() => setTouched(true)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) submit()
              }}
              placeholder="e.g. Write a function two_sum(nums, target) that returns the indices of the two numbers adding up to target. Each input has exactly one solution."
              rows={10}
              aria-invalid={taskError ? true : undefined}
              aria-describedby={cn(hintId, taskError && errorId)}
              className="min-h-56 resize-y font-mono text-[13px] leading-6"
            />
            {taskError && (
              <p id={errorId} className="text-sm text-destructive">
                {taskError}
              </p>
            )}
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Language</legend>
            <ToggleGroup
              type="single"
              variant="outline"
              value={language}
              onValueChange={(value) => value && setLanguage(value as Language)}
              aria-label="Language"
            >
              <ToggleGroupItem value="python" className="px-4 data-[state=on]:border-brand/60 data-[state=on]:bg-brand/10 data-[state=on]:text-foreground">
                Python
              </ToggleGroupItem>
              <ToggleGroupItem value="cpp" className="px-4 data-[state=on]:border-brand/60 data-[state=on]:bg-brand/10 data-[state=on]:text-foreground">
                C++
              </ToggleGroupItem>
            </ToggleGroup>
          </fieldset>

          {generalError && (
            <Alert variant="destructive">
              <AlertTitle>
                {generalError.status === 429 ? "AstraAi is busy" : "Couldn't start the run"}
              </AlertTitle>
              <AlertDescription>
                {generalError.detail}
                {generalError.retryAfterSeconds !== null &&
                  ` Try again in ${generalError.retryAfterSeconds} seconds.`}
              </AlertDescription>
            </Alert>
          )}

          <div className="flex items-center justify-between gap-4 border-t pt-5">
            <p className="hidden text-xs text-muted-foreground sm:block">
              <kbd className="font-mono">Ctrl</kbd> + <kbd className="font-mono">Enter</kbd> to
              start
            </p>
            <Button type="submit" size="lg" disabled={createRun.isPending} className="px-4">
              {createRun.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
              {createRun.isPending ? "Starting…" : "Start run"}
            </Button>
          </div>
        </form>
      </main>
    </div>
  )
}
