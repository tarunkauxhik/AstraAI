import { useEffect, useId, useRef, useState, type FormEvent } from "react"
import { useQuery } from "@tanstack/react-query"
import { Loader2, WifiOff } from "lucide-react"
import { useLocation, useNavigate } from "react-router"

import { api } from "@/api/client"
import { TASK_MAX_LENGTH, type Language, type Mode } from "@/api/types"
import { Brand } from "@/components/Brand"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useCreateRun } from "@/hooks/useCreateRun"
import { parseRepository } from "@/lib/repository"
import { cn } from "@/lib/utils"

/** The counter only appears once the task is long enough for the limit to matter. */
const COUNTER_THRESHOLD = Math.floor(TASK_MAX_LENGTH * 0.9)

const LANGUAGE_KEY = "astraai:language"
const MODE_KEY = "astraai:mode"

/** What each kind of task is, in one line under the choice. */
const MODES: Record<Mode, { label: string; description: string }> = {
  develop: {
    label: "Change a repository",
    description:
      "Give AstraAi a repository and a small coding task. It makes the change, runs the tests, reviews it and gives you the patch.",
  },
  solve: {
    label: "Solve a coding problem",
    description: "Give AstraAi a standalone coding problem. It generates, tests and reviews a solution.",
  },
}

/** The kind of task last started on this device; changing a repository at first. */
function rememberedMode(): Mode {
  try {
    return window.localStorage.getItem(MODE_KEY) === "solve" ? "solve" : "develop"
  } catch {
    return "develop"
  }
}

function rememberMode(mode: Mode) {
  try {
    window.localStorage.setItem(MODE_KEY, mode)
  } catch {
    // Remembering is a convenience only.
  }
}

/** The last language used on this device. Storage can be blocked, so it's only a default. */
function rememberedLanguage(): Language {
  try {
    const stored = window.localStorage.getItem(LANGUAGE_KEY)
    return stored === "cpp" ? "cpp" : "python"
  } catch {
    return "python"
  }
}

function rememberLanguage(language: Language) {
  try {
    window.localStorage.setItem(LANGUAGE_KEY, language)
  } catch {
    // Remembering is a convenience only.
  }
}

const SUBMIT_HINT =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘ ↵" : "Ctrl ↵"

/** "Edit task" on a finished run opens this page with that run's request. */
interface Prefill {
  task?: string
  language?: Language
  mode?: Mode
  repository?: string
}

const CHOICE =
  "h-11 px-4 data-[state=on]:border-brand/60 data-[state=on]:bg-brand/10 data-[state=on]:text-foreground sm:h-9"

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
  const prefill = (useLocation().state ?? {}) as Prefill
  const createRun = useCreateRun()
  const [task, setTask] = useState(prefill.task ?? "")
  const [language, setLanguage] = useState<Language>(() => prefill.language ?? rememberedLanguage())
  // A task being edited keeps its own kind; a solve request carries no mode.
  const [mode, setMode] = useState<Mode>(
    () => prefill.mode ?? (prefill.task !== undefined ? "solve" : rememberedMode()),
  )
  const [repository, setRepository] = useState(prefill.repository ?? "")
  const [attempted, setAttempted] = useState(false)
  const develop = mode === "develop"
  const textarea = useRef<HTMLTextAreaElement>(null)
  const taskId = useId()
  const hintId = useId()
  const counterId = useId()
  const errorId = useId()
  const repositoryId = useId()
  const repositoryErrorId = useId()

  // Ready to type on desktop; not on touch screens, where focus would pop up the keyboard.
  useEffect(() => {
    const element = textarea.current
    if (!element || !window.matchMedia?.("(pointer: fine)").matches) return
    element.focus()
    element.setSelectionRange(element.value.length, element.value.length)
  }, [])

  // Mirrors the backend: strip, then count code points (Python len()), not UTF-16 units.
  // The server rechecks.
  const length = [...task.trim()].length
  const localError =
    length === 0
      ? develop
        ? "Describe what you want changed."
        : "Describe what you want AstraAi to solve."
      : length > TASK_MAX_LENGTH
        ? `The task is too long: ${length.toLocaleString()} of ${TASK_MAX_LENGTH.toLocaleString()} characters.`
        : null
  const serverFieldError = createRun.error?.fieldErrors.find((item) => item.field === "task")?.message
  // An empty box isn't an error until the user tries to run it; an over-long one is at once.
  const taskError =
    (localError && (attempted || length > TASK_MAX_LENGTH) ? localError : null) ?? serverFieldError ?? null
  // Mirrors the backend's address rules; the server rechecks and never fetches anything else.
  const localRepositoryError = !develop
    ? null
    : parseRepository(repository) !== null
      ? null
      : repository.trim()
        ? "Enter a GitHub repository, like https://github.com/owner/name."
        : "Enter a GitHub repository."
  const serverRepositoryError = createRun.error?.fieldErrors.find(
    (item) => item.field === "repository",
  )?.message
  const repositoryError = (attempted ? localRepositoryError : null) ?? serverRepositoryError ?? null
  const generalError =
    createRun.error && !serverFieldError && !serverRepositoryError ? createRun.error : null
  const showCounter = length >= COUNTER_THRESHOLD

  function submit(event?: FormEvent) {
    event?.preventDefault()
    setAttempted(true)
    if (localError || localRepositoryError || createRun.isPending) return
    const request = develop
      ? { task, language: "python" as const, mode, repository: repository.trim() }
      : { task, language }
    createRun.mutate(request, { onSuccess: (accepted) => navigate(`/runs/${accepted.run_id}`) })
  }

  function chooseMode(value: string) {
    if (value !== "solve" && value !== "develop") return
    setMode(value)
    rememberMode(value)
    setAttempted(false)
    createRun.reset()
  }

  function chooseLanguage(value: string) {
    if (value !== "python" && value !== "cpp") return
    setLanguage(value)
    rememberLanguage(value)
  }

  const describedBy = [hintId, showCounter && counterId, taskError && errorId]
    .filter(Boolean)
    .join(" ")

  return (
    <div className="mx-auto flex min-h-dvh max-w-2xl flex-col px-4 pb-10 sm:px-6">
      <header className="flex h-12 items-center sm:h-14">
        <Brand />
      </header>

      <main className="flex-1 pt-8 sm:pt-16">
        <ServiceWarning />
        <h1 className="mb-8 text-2xl font-semibold tracking-tight text-balance sm:text-3xl">
          Describe a small change. Get a tested patch.
        </h1>
        <form onSubmit={submit} noValidate className="space-y-5">
          <div className="space-y-2">
            <ToggleGroup
              type="single"
              variant="outline"
              value={mode}
              onValueChange={chooseMode}
              aria-label="What AstraAi does"
              className="w-full sm:w-auto"
            >
              {(["develop", "solve"] as const).map((value) => (
                <ToggleGroupItem key={value} value={value} className={cn(CHOICE, "flex-1 sm:flex-none")}>
                  {MODES[value].label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <p className="text-sm text-muted-foreground">{MODES[mode].description}</p>
          </div>

          {develop && (
            <div className="space-y-2">
              <label htmlFor={repositoryId} className="text-sm font-medium">
                Repository
              </label>
              <Input
                id={repositoryId}
                value={repository}
                onChange={(event) => setRepository(event.target.value)}
                placeholder="https://github.com/owner/name"
                inputMode="url"
                autoComplete="off"
                autoCapitalize="off"
                spellCheck={false}
                aria-invalid={repositoryError ? true : undefined}
                aria-describedby={repositoryError ? repositoryErrorId : undefined}
              />
              {repositoryError && (
                <p id={repositoryErrorId} className="text-sm text-destructive">
                  {repositoryError}
                </p>
              )}
            </div>
          )}

          <div className="space-y-2">
            <label htmlFor={taskId} className="text-sm font-medium">
              {develop ? "What should change?" : "What should AstraAi solve?"}
            </label>
            <Textarea
              ref={textarea}
              id={taskId}
              value={task}
              onChange={(event) => setTask(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) submit()
              }}
              placeholder={
                develop
                  ? 'For example: parse_duration("1h30m") returns 90; it should return 5400. Fix it and add a regression test.'
                  : "For example: write a function that returns the indices of the two numbers in a list that add up to a target."
              }
              rows={8}
              aria-invalid={taskError ? true : undefined}
              aria-describedby={describedBy}
              className="min-h-44 resize-y text-base leading-7"
            />
            <p id={hintId} className="text-sm text-muted-foreground">
              {develop
                ? "Public Python repositories whose tests run with pytest without additional dependencies. Works on a copy. AstraAi never writes to GitHub."
                : "Describe one self-contained function."}
            </p>
            {(taskError || showCounter) && (
              <div className="flex items-start justify-between gap-4 text-sm">
                <p id={errorId} className="text-destructive">
                  {taskError}
                </p>
                {showCounter && (
                  <p
                    id={counterId}
                    className={cn(
                      "shrink-0 font-mono text-xs text-muted-foreground",
                      length > TASK_MAX_LENGTH && "text-destructive",
                    )}
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

          <div
            className={cn(
              "flex flex-col gap-3 sm:flex-row sm:items-center",
              develop ? "sm:justify-end" : "sm:justify-between",
            )}
          >
            {!develop && (
              <ToggleGroup
                type="single"
                variant="outline"
                value={language}
                onValueChange={chooseLanguage}
                aria-label="Language"
              >
                <ToggleGroupItem value="python" className={CHOICE}>
                  Python
                </ToggleGroupItem>
                <ToggleGroupItem value="cpp" className={CHOICE}>
                  C++
                </ToggleGroupItem>
              </ToggleGroup>
            )}
            <Button
              type="submit"
              size="lg"
              disabled={createRun.isPending}
              aria-keyshortcuts="Control+Enter Meta+Enter"
              className="h-11 w-full px-5 sm:h-9 sm:w-auto"
            >
              {createRun.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
              {createRun.isPending ? "Starting…" : develop ? "Start" : "Solve"}
              {!createRun.isPending && (
                <kbd
                  aria-hidden="true"
                  className="ml-1 hidden font-sans text-xs font-normal opacity-60 pointer-fine:inline"
                >
                  {SUBMIT_HINT}
                </kbd>
              )}
            </Button>
          </div>
        </form>
      </main>
    </div>
  )
}
