import { ChevronRight, History } from "lucide-react"

import type { ExecutionResult, Run } from "@/api/types"
import { ActivityDot } from "@/components/run/ActivityDot"
import { OutputBlock } from "@/components/run/OutputBlock"
import { Panel } from "@/components/run/Panel"
import { TONE_BADGE, TONE_ICON } from "@/components/run/tone"
import { Badge } from "@/components/ui/badge"
import { formatDuration, formatTestCounts } from "@/lib/format"
import { EXECUTION_STATUS, executionErrorTypeLabel } from "@/lib/labels"
import { evidenceAttempt, executionAttempt, executionFreshness } from "@/lib/run-view"
import { cn } from "@/lib/utils"

function ResultBody({ result, historical }: { result: ExecutionResult; historical: boolean }) {
  const status = EXECUTION_STATUS[result.status]
  const tone = historical ? "neutral" : status.tone
  const Icon = TONE_ICON[tone]
  const counts = formatTestCounts(result.tests_passed, result.tests_failed)
  const errorType = executionErrorTypeLabel(result.error_type)
  const infrastructure = result.status === "infrastructure_error"
  const showOutput = !infrastructure && (result.stdout || result.stderr)
  const failing = result.status !== "passed"

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className={cn("h-6 gap-1.5 rounded-md px-2", TONE_BADGE[tone])}>
          <Icon aria-hidden="true" />
          {status.label}
        </Badge>
        {counts && <span className="text-sm">{counts}</span>}
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
        {errorType && !infrastructure && (
          <>
            <dt className="text-muted-foreground">Error</dt>
            <dd>{errorType}</dd>
          </>
        )}
        <dt className="text-muted-foreground">Sandbox time</dt>
        <dd className="font-mono">{formatDuration(result.duration_ms)}</dd>
        {result.exit_code !== null && !infrastructure && (
          <>
            <dt className="text-muted-foreground">Exit code</dt>
            <dd className="font-mono">{result.exit_code}</dd>
          </>
        )}
      </dl>

      {infrastructure && (
        <p className="rounded-md bg-muted px-2.5 py-2 text-xs text-muted-foreground">
          The execution environment couldn't run the code, so this attempt says nothing about
          whether the code is correct.
        </p>
      )}

      {showOutput && (
        <div className="space-y-2">
          {result.stdout && (
            <OutputBlock label="stdout" text={result.stdout} defaultOpen={!historical && failing} />
          )}
          {result.stderr && (
            <OutputBlock
              label="stderr"
              text={result.stderr}
              tone="error"
              defaultOpen={!historical && failing}
            />
          )}
          {result.output_truncated && (
            <p className="text-xs text-muted-foreground">
              Output was cut off at the sandbox output limit.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export function ExecutionPanel({ run }: { run: Run }) {
  const result = run.execution_result
  const freshness = executionFreshness(run)
  const attempt = executionAttempt(run)

  if (result === null || freshness === null) {
    const running = run.stage === "executing" && run.status === "running"
    return (
      <Panel title="Execution">
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          {running && <ActivityDot />}
          {running ? `Running attempt ${attempt} in the sandbox…` : "Nothing has been executed yet."}
        </p>
      </Panel>
    )
  }

  if (freshness === "current") {
    return (
      <Panel
        title="Execution"
        action={<span className="text-xs text-muted-foreground">Attempt {evidenceAttempt(run, freshness)}</span>}
      >
        <ResultBody result={result} historical={false} />
      </Panel>
    )
  }

  // A newer attempt is running (or was, when the run stopped): the stored result is history.
  const previous = evidenceAttempt(run, freshness)
  const running = run.status === "running"
  return (
    <Panel
      title="Execution"
      action={<span className="text-xs text-muted-foreground">Attempt {attempt}</span>}
    >
      <p className="flex items-center gap-2 text-sm">
        {running && <ActivityDot />}
        {running
          ? `Running attempt ${attempt} in the sandbox…`
          : `Attempt ${attempt} didn't finish before the run stopped.`}
      </p>
      <details className="group rounded-md border">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-2 text-xs text-muted-foreground select-none [&::-webkit-details-marker]:hidden">
          <ChevronRight
            className="size-3.5 transition-transform duration-150 group-open:rotate-90"
            aria-hidden="true"
          />
          <History className="size-3.5" aria-hidden="true" />
          Previous attempt ({previous}) · not the current result
        </summary>
        <div className="border-t p-3 opacity-80">
          <ResultBody result={result} historical />
        </div>
      </details>
    </Panel>
  )
}
