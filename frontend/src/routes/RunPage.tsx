import { useEffect, useState, type ReactNode } from "react"
import { ChevronDown, Plus, WifiOff } from "lucide-react"
import { Link, useParams } from "react-router"

import type { ApiError } from "@/api/client"
import type { Run } from "@/api/types"
import { Brand } from "@/components/Brand"
import { ArtifactPanel, type ArtifactTab } from "@/components/run/ArtifactPanel"
import { DecisionPanel } from "@/components/run/DecisionPanel"
import { RunProgress } from "@/components/run/RunProgress"
import { StatusBadge } from "@/components/run/StatusBadge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useRun } from "@/hooks/useRun"
import { describeError, LANGUAGE_LABELS, STAGE_ACTIVITY, STATUS_LABELS } from "@/lib/labels"
import { pageState } from "@/lib/run-view"
import { cn } from "@/lib/utils"

/** One short sentence for the page title and the polite live region. */
function announcement(run: Run): string {
  if (run.status === "failed") return describeError(run.error).title
  if (run.status === "running") return STAGE_ACTIVITY[run.stage]
  return STATUS_LABELS[run.status]
}

function TopBar({ run }: { run?: Run }) {
  const [taskOpen, setTaskOpen] = useState(false)

  const taskToggle = run && (
    <button
      type="button"
      onClick={() => setTaskOpen((open) => !open)}
      aria-expanded={taskOpen}
      aria-controls="full-task"
      className="flex min-w-0 items-center gap-1 rounded-sm text-left text-sm text-muted-foreground hover:text-foreground"
    >
      <span className="truncate">{run.task}</span>
      <ChevronDown
        className={cn("size-4 shrink-0 transition-transform duration-150", taskOpen && "rotate-180")}
        aria-hidden="true"
      />
      <span className="sr-only">{taskOpen ? "Hide the full task" : "Show the full task"}</span>
    </button>
  )

  return (
    <header className="sticky top-0 z-20 border-b bg-background/95 backdrop-blur">
      {/* One task toggle: its own row on phones, inline between brand and status otherwise. */}
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 px-4 sm:h-14 sm:flex-nowrap sm:px-6">
        <div className="flex h-14 items-center sm:h-auto">
          <Brand />
        </div>
        {run && <div className="order-last flex min-w-0 basis-full pb-2.5 sm:order-none sm:flex-1 sm:basis-auto sm:pb-0">{taskToggle}</div>}
        <div className="ml-auto flex shrink-0 items-center gap-2 sm:ml-0">
          {run && <StatusBadge run={run} />}
          <Button asChild variant="ghost" size="sm" aria-label="New run">
            <Link to="/">
              <Plus aria-hidden="true" />
              <span className="hidden md:inline">New run</span>
            </Link>
          </Button>
        </div>
      </div>
      {run && taskOpen && (
        <div id="full-task" className="border-t">
          <div className="mx-auto max-w-6xl px-4 py-3 sm:px-6">
            <p className="max-h-60 overflow-auto text-sm leading-relaxed whitespace-pre-wrap">{run.task}</p>
            <p className="mt-1 text-xs text-muted-foreground">{LANGUAGE_LABELS[run.language]}</p>
          </div>
        </div>
      )}
    </header>
  )
}

function CenteredMessage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="mx-auto max-w-lg px-4 pt-24 text-center">
      <h1 className="text-xl font-semibold">{title}</h1>
      <div className="mt-2 text-sm text-muted-foreground">{children}</div>
      <Button asChild className="mt-6">
        <Link to="/">Start a new run</Link>
      </Button>
    </main>
  )
}

function Workspace({ run, connectionError }: { run: Run; connectionError: ApiError | null }) {
  const [tab, setTab] = useState<ArtifactTab>("solution")
  const [verificationOpen, setVerificationOpen] = useState(false)
  const [scrollToVerification, setScrollToVerification] = useState(0)

  useEffect(() => {
    if (scrollToVerification === 0) return
    document.getElementById("verification-details")?.scrollIntoView({ block: "start", behavior: "smooth" })
  }, [scrollToVerification])

  function showDetails() {
    setTab("details")
    setVerificationOpen(true)
    setScrollToVerification((count) => count + 1)
  }

  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6">
      <h1 className="sr-only">AstraAi run: {run.task}</h1>
      <div className="border-b py-3">
        <RunProgress run={run} />
      </div>
      {connectionError && (
        <Alert className="mt-4">
          <WifiOff aria-hidden="true" />
          <AlertTitle>Reconnecting</AlertTitle>
          <AlertDescription>{connectionError.detail} Showing the last known state.</AlertDescription>
        </Alert>
      )}
      {/* The mobile approval bar publishes its height while shown (0 otherwise); keep content clear of it. */}
      <div className="grid gap-6 pt-6 pb-[calc(1.5rem+var(--approval-bar-height,0px))] lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start lg:gap-8">
        {/* Content first in the document: on narrow screens the solution comes before the decision. */}
        <main className="min-w-0">
          <ArtifactPanel
            run={run}
            tab={tab}
            onTabChange={setTab}
            verificationOpen={verificationOpen}
            onVerificationOpenChange={setVerificationOpen}
          />
        </main>
        <aside aria-label="Run status" className="lg:sticky lg:top-20">
          <DecisionPanel run={run} onShowDetails={showDetails} />
        </aside>
      </div>
    </div>
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
      <TopBar run={run} />
      {/* One polite announcement per state change, not per poll. */}
      <p className="sr-only" aria-live="polite">
        {run ? announcement(run) : ""}
      </p>

      {state.kind === "loading" && (
        <div className="mx-auto grid max-w-6xl gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,1fr)_340px]" aria-busy="true">
          <Skeleton className="h-80" />
          <Skeleton className="h-48" />
          <span className="sr-only">Loading run…</span>
        </div>
      )}
      {state.kind === "not_found" && (
        <CenteredMessage title="Run not found">
          <p>
            There is no run with this ID. Runs are kept in memory, so they disappear when the
            service restarts or after many newer runs have finished.
          </p>
        </CenteredMessage>
      )}
      {state.kind === "unreachable" && (
        <CenteredMessage title="Can't load this run">
          <p>{state.error.detail}</p>
          <p className="mt-1">Retrying automatically.</p>
        </CenteredMessage>
      )}
      {state.kind === "run" && <Workspace run={state.run} connectionError={state.connectionError} />}
    </div>
  )
}
