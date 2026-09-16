import { useEffect, useState, type ReactNode } from "react"
import { Check, Copy, Plus, WifiOff } from "lucide-react"
import { Link, useParams } from "react-router"

import type { ApiError } from "@/api/client"
import type { Run } from "@/api/types"
import { MAX_EXECUTION_RETRIES, MAX_REVISIONS } from "@/api/types"
import { Brand } from "@/components/Brand"
import { ArtifactPanel } from "@/components/run/ArtifactPanel"
import { CriticPanel } from "@/components/run/CriticPanel"
import { ExecutionPanel } from "@/components/run/ExecutionPanel"
import { RunStatusPanel } from "@/components/run/RunStatusPanel"
import { RunTimeline } from "@/components/run/RunTimeline"
import { StatusBadge } from "@/components/run/StatusBadge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useRun } from "@/hooks/useRun"
import { formatDateTime, shortId } from "@/lib/format"
import { LANGUAGE_LABELS, STAGE_LABELS, STATUS_LABELS } from "@/lib/labels"
import { pageState, showApprovalControls } from "@/lib/run-view"

function CopyRunId({ runId }: { runId: string }) {
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(timer)
  }, [copied])
  return (
    <Button
      variant="ghost"
      size="xs"
      className="font-mono text-muted-foreground"
      aria-label={copied ? "Run ID copied" : `Copy run ID ${runId}`}
      onClick={() =>
        navigator.clipboard.writeText(runId).then(
          () => setCopied(true),
          () => undefined,
        )
      }
    >
      {shortId(runId)}
      {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
    </Button>
  )
}

function TopBar({ run }: { run?: Run }) {
  return (
    <header className="sticky top-0 z-20 border-b bg-background/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-3 px-4 sm:px-6">
        <Brand />
        {run && (
          <>
            <span className="hidden h-5 w-px bg-border sm:block" aria-hidden="true" />
            <p className="hidden min-w-0 flex-1 truncate text-sm text-muted-foreground sm:block" title={run.task}>
              {run.task}
            </p>
            <div className="ml-auto flex shrink-0 items-center gap-2 sm:ml-0">
              <StatusBadge run={run} />
              <Badge variant="outline" className="hidden h-6 rounded-md text-muted-foreground md:inline-flex">
                {LANGUAGE_LABELS[run.language]}
              </Badge>
              <span className="hidden lg:inline-flex">
                <CopyRunId runId={run.run_id} />
              </span>
            </div>
          </>
        )}
        <Button asChild variant="outline" size="sm" className={run ? "hidden md:inline-flex" : "ml-auto"}>
          <Link to="/">
            <Plus aria-hidden="true" />
            New run
          </Link>
        </Button>
      </div>
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

function ConnectionBanner({ error }: { error: ApiError }) {
  return (
    <Alert className="mb-4">
      <WifiOff aria-hidden="true" />
      <AlertTitle>Reconnecting</AlertTitle>
      <AlertDescription>
        {error.detail} Showing the last known state; it may be out of date.
      </AlertDescription>
    </Alert>
  )
}

function Workspace({ run, connectionError }: { run: Run; connectionError: ApiError | null }) {
  const waiting = showApprovalControls(run)
  return (
    <main
      className={
        "mx-auto grid max-w-[1600px] grid-cols-[minmax(0,1fr)] items-start gap-4 px-4 py-4 sm:px-6 " +
        "[grid-template-areas:'banner'_'timeline'_'status'_'artifacts'_'evidence'] " +
        "lg:grid-cols-[minmax(0,1fr)_340px] lg:[grid-template-areas:'banner_banner'_'timeline_timeline'_'artifacts_status'_'artifacts_evidence'] " +
        "xl:grid-cols-[220px_minmax(0,1fr)_380px] xl:[grid-template-areas:'banner_banner_banner'_'timeline_artifacts_status'_'timeline_artifacts_evidence'] " +
        "lg:grid-rows-[auto_auto_auto_1fr] xl:grid-rows-[auto_auto_1fr] " +
        (waiting ? "pb-24 md:pb-4" : "")
      }
    >
      <div className="[grid-area:banner] empty:hidden">
        {connectionError && <ConnectionBanner error={connectionError} />}
      </div>

      <div className="min-w-0 [grid-area:timeline] rounded-lg border bg-card p-2 xl:sticky xl:top-18 xl:border-0 xl:bg-transparent xl:p-0">
        <RunTimeline run={run} />
      </div>

      <section aria-labelledby="task-heading" className="min-w-0 space-y-4 [grid-area:artifacts]">
        <div className="rounded-lg border bg-card p-4">
          <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
            <h1 id="task-heading" className="label-caps">
              Task
            </h1>
            <span className="text-xs text-muted-foreground">
              {LANGUAGE_LABELS[run.language]} · started {formatDateTime(run.created_at)}
            </span>
          </div>
          <p className="max-h-40 overflow-auto text-sm leading-relaxed whitespace-pre-wrap">
            {run.task}
          </p>
          <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-t pt-3 text-xs">
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Status</dt>
              <dd>{STATUS_LABELS[run.status]}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Stage</dt>
              <dd>{STAGE_LABELS[run.stage]}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Revisions</dt>
              <dd>
                {run.revision_count}/{MAX_REVISIONS}
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">Execution retries</dt>
              <dd>
                {run.execution_retry_count}/{MAX_EXECUTION_RETRIES}
              </dd>
            </div>
          </dl>
        </div>
        <ArtifactPanel run={run} />
      </section>

      <div className="min-w-0 [grid-area:status]">
        <RunStatusPanel run={run} />
      </div>

      <div className="min-w-0 space-y-4 [grid-area:evidence]">
        <ExecutionPanel run={run} />
        <CriticPanel run={run} />
      </div>
    </main>
  )
}

export function RunPage() {
  const { runId = "" } = useParams()
  const query = useRun(runId)
  const state = pageState(query.data, query.error)
  const run = state.kind === "run" ? state.run : undefined

  useEffect(() => {
    document.title = run ? `${STATUS_LABELS[run.status]} · ${shortId(run.run_id)} · AstraAi` : "AstraAi"
  }, [run])

  return (
    <div className="min-h-dvh">
      <TopBar run={run} />
      {/* One polite announcement per status/stage change, not per poll. */}
      <p className="sr-only" aria-live="polite">
        {run ? `${STATUS_LABELS[run.status]}: ${STAGE_LABELS[run.stage]}` : ""}
      </p>

      {state.kind === "loading" && (
        <main className="mx-auto grid max-w-[1600px] gap-4 px-4 py-4 sm:px-6 xl:grid-cols-[220px_minmax(0,1fr)_380px]" aria-busy="true">
          <Skeleton className="h-64" />
          <Skeleton className="h-96" />
          <Skeleton className="h-64" />
          <span className="sr-only">Loading run…</span>
        </main>
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
