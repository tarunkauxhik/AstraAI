import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react"
import { Plus, WifiOff } from "lucide-react"
import { Link, useParams } from "react-router"

import type { ApiError } from "@/api/client"
import type { Run } from "@/api/types"
import { Brand } from "@/components/Brand"
import { ChangesSection, VerificationSection } from "@/components/run/DevelopSections"
import { RunLog } from "@/components/run/RunLog"
import { RunStatus } from "@/components/run/RunStatus"
import { SolutionSection } from "@/components/run/SolutionSection"
import { TestsSection } from "@/components/run/TestsSection"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useRun } from "@/hooks/useRun"
import { LANGUAGE_LABELS } from "@/lib/labels"
import { announcement, describeEnding, hasRunLog, isTerminal, pageState } from "@/lib/run-view"
import { cn, TOUCH_TARGET } from "@/lib/utils"

function AppHeader() {
  return (
    <header className="mx-auto flex h-12 max-w-6xl items-center justify-between px-4 sm:h-14 sm:px-6">
      <Brand />
      <Button asChild variant="ghost" size="sm" className="-mr-2 pointer-coarse:h-11">
        <Link to="/">
          <Plus aria-hidden="true" />
          New run
        </Link>
      </Button>
    </header>
  )
}

/** The task is the page's title: two lines, with the rest one click away. */
function TaskTitle({ run }: { run: Run }) {
  const [expanded, setExpanded] = useState(false)
  const [clamped, setClamped] = useState(false)
  const title = useRef<HTMLHeadingElement>(null)

  useLayoutEffect(() => {
    const element = title.current
    if (element) setClamped(element.scrollHeight > element.clientHeight + 1)
  }, [run.task])

  return (
    <div className="pt-2 pb-6 sm:pt-4 sm:pb-8">
      <h1
        ref={title}
        className="line-clamp-2 text-lg leading-snug font-semibold tracking-tight text-balance sm:text-xl"
      >
        {run.task}
      </h1>
      <p className="mt-1.5 flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
        <span>
          {run.mode === "develop"
            ? (run.repository_ref?.full_name ?? run.repository)
            : LANGUAGE_LABELS[run.language]}
        </span>
        {(clamped || expanded) && (
          <>
            <span aria-hidden="true">·</span>
            <button
              type="button"
              onClick={() => setExpanded((open) => !open)}
              aria-expanded={expanded}
              aria-controls="full-task"
              className={cn(TOUCH_TARGET, "rounded-sm underline-offset-4 hover:text-foreground hover:underline")}
            >
              {expanded ? "Hide full task" : "Show full task"}
            </button>
          </>
        )}
      </p>
      {expanded && (
        <p
          id="full-task"
          className="mt-3 max-h-72 overflow-auto rounded-md bg-muted/40 px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap"
        >
          {run.task}
        </p>
      )}
    </div>
  )
}

/** Scroll a section into view and put keyboard focus on its heading (or disclosure). */
function reveal(sectionId: string, focusSelector: string) {
  document.getElementById(sectionId)?.scrollIntoView?.({ block: "start", behavior: "smooth" })
  document.querySelector<HTMLElement>(focusSelector)?.focus({ preventScroll: true })
}

function RunView({ run, connectionError }: { run: Run; connectionError: ApiError | null }) {
  // The log opens by itself when it explains the ending, unless the user has chosen.
  const [logChoice, setLogOpen] = useState<boolean | null>(null)
  const logOpen = logChoice ?? (isTerminal(run) && describeEnding(run).openLog)
  const [revealLog, setRevealLog] = useState(0)
  // An ending with nothing to show reads as one column; work in progress keeps its place.
  const beside =
    run.mode === "develop"
      ? run.changes !== null || !isTerminal(run)
      : run.generated_tests !== null || run.generated_code !== null || !isTerminal(run)

  useEffect(() => {
    if (revealLog > 0) reveal("run-log", "#run-log summary")
  }, [revealLog])

  return (
    <main className="mx-auto max-w-6xl px-4 pb-[calc(2.5rem+var(--dock-height,0px))] sm:px-6 lg:pb-16">
      <TaskTitle run={run} />
      {connectionError && (
        <Alert className="mb-6">
          <WifiOff aria-hidden="true" />
          <AlertTitle>Reconnecting</AlertTitle>
          <AlertDescription>{connectionError.detail} Showing the last known state.</AlertDescription>
        </Alert>
      )}
      <div className={cn("grid gap-10", beside && "lg:grid-cols-[minmax(0,1fr)_19rem] lg:gap-x-14")}>
        {/* First in reading order everywhere; beside the work on desktop. */}
        <div className={cn(beside ? "lg:col-start-2 lg:row-start-1" : "max-w-xl")}>
          <div className={cn(beside && "lg:sticky lg:top-6")}>
            <RunStatus
              run={run}
              onViewTests={() => reveal("tests", "#tests-heading")}
              onOpenLog={() => {
                setLogOpen(true)
                setRevealLog((count) => count + 1)
              }}
            />
          </div>
        </div>
        <div className={cn("min-w-0 space-y-12", beside && "lg:col-start-1 lg:row-start-1")}>
          {run.mode === "develop" ? (
            <>
              <ChangesSection run={run} />
              <VerificationSection run={run} />
            </>
          ) : (
            <>
              <SolutionSection run={run} />
              <TestsSection run={run} />
            </>
          )}
          {hasRunLog(run) && <RunLog run={run} open={logOpen} onOpenChange={setLogOpen} />}
        </div>
      </div>
    </main>
  )
}

function CenteredMessage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="mx-auto max-w-lg px-4 pt-20 text-center">
      <h1 className="text-xl font-semibold">{title}</h1>
      <div className="mt-2 text-sm text-muted-foreground">{children}</div>
      <Button asChild className="mt-6">
        <Link to="/">Start a new run</Link>
      </Button>
    </main>
  )
}

export function RunPage() {
  const { runId = "" } = useParams()
  const query = useRun(runId)
  const state = pageState(query.data, query.error)
  const run = state.kind === "run" ? state.run : undefined

  useEffect(() => {
    document.title = run ? `${announcement(run)} · AstraAi` : "AstraAi"
  }, [run])

  return (
    <div className="min-h-dvh">
      <AppHeader />
      {/* One polite announcement per state change, not per poll. */}
      <p className="sr-only" aria-live="polite">
        {run ? announcement(run) : ""}
      </p>

      {state.kind === "loading" && (
        <div
          className="mx-auto grid max-w-6xl gap-10 px-4 pt-4 sm:px-6 lg:grid-cols-[minmax(0,1fr)_19rem]"
          aria-busy="true"
        >
          <Skeleton className="h-64" />
          <Skeleton className="h-40" />
          <span className="sr-only">Loading run…</span>
        </div>
      )}
      {state.kind === "not_found" && (
        <CenteredMessage title="Run not found">
          <p>
            There is no run with this ID. Finished runs are removed after many newer runs
            have finished.
          </p>
        </CenteredMessage>
      )}
      {state.kind === "unreachable" && (
        <CenteredMessage title="Can't load this run">
          <p>{state.error.detail}</p>
          <p className="mt-1">Retrying automatically.</p>
        </CenteredMessage>
      )}
      {state.kind === "run" && (
        <RunView key={state.run.run_id} run={state.run} connectionError={state.connectionError} />
      )}
    </div>
  )
}
