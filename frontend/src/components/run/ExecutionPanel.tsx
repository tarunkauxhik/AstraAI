import { History } from "lucide-react"

import type { Run } from "@/api/types"
import { Panel } from "@/components/run/Panel"
import { TONE_BADGE } from "@/components/run/tone"
import { Badge } from "@/components/ui/badge"
import { formatDuration, formatTestCounts } from "@/lib/format"
import { EXECUTION_STATUS, executionErrorTypeLabel } from "@/lib/labels"
import { executionAttempt, executionFreshness } from "@/lib/run-view"
import { cn } from "@/lib/utils"

function Output({ label, text, open }: { label: string; text: string; open: boolean }) {
  if (!text) return null
  return (
    <details open={open} className="group rounded-md border">
      <summary className="cursor-pointer px-3 py-1.5 font-mono text-xs text-muted-foreground select-none hover:text-foreground">
        {label}
      </summary>
      <pre className="max-h-72 overflow-auto border-t px-3 py-2 font-mono text-xs leading-5 whitespace-pre">
        {text}
      </pre>
    </details>
  )
}

export function ExecutionPanel({ run }: { run: Run }) {
  const result = run.execution_result
  const freshness = executionFreshness(run)

  if (result === null || freshness === null) {
    return (
      <Panel title="Execution">
        <p className="text-sm text-muted-foreground">
          {run.stage === "executing"
            ? "Running the generated tests in the sandbox…"
            : "Nothing has been executed yet."}
        </p>
      </Panel>
    )
  }

  const stale = freshness === "stale"
  const status = EXECUTION_STATUS[result.status]
  // A superseded result keeps its label but loses its outcome color.
  const tone = stale ? "neutral" : status.tone
  const counts = formatTestCounts(result.tests_passed, result.tests_failed)
  const errorType = executionErrorTypeLabel(result.error_type)
  const infrastructure = result.status === "infrastructure_error"

  return (
    <Panel title="Execution">
      {stale && (
        <p className="flex items-start gap-2 rounded-md bg-muted px-2.5 py-2 text-xs text-muted-foreground">
          <History className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          Previous attempt ({executionAttempt(run) - 1}). Attempt {executionAttempt(run)}{" "}
          {run.status === "running" ? "is executing now" : "didn't finish"}, so this is not the
          current result.
        </p>
      )}
      <div className={cn("space-y-2", stale && "opacity-70")}>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className={cn("h-6 rounded-md px-2", TONE_BADGE[tone])}>
            {stale ? `Previously: ${status.label}` : status.label}
          </Badge>
          {counts && <span className="text-sm">{counts}</span>}
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
          <dt className="text-muted-foreground">Sandbox time</dt>
          <dd className="font-mono">{formatDuration(result.duration_ms)}</dd>
          {errorType && (
            <>
              <dt className="text-muted-foreground">Error</dt>
              <dd>{errorType}</dd>
            </>
          )}
          {result.exit_code !== null && !infrastructure && (
            <>
              <dt className="text-muted-foreground">Exit code</dt>
              <dd className="font-mono">{result.exit_code}</dd>
            </>
          )}
        </dl>
        {infrastructure ? (
          <p className="text-xs text-muted-foreground">
            The sandbox couldn't run the code. This says nothing about whether the code is correct.
          </p>
        ) : (
          <div className="space-y-2">
            <Output label="stdout" text={result.stdout} open={!stale && result.status !== "passed"} />
            <Output label="stderr" text={result.stderr} open={!stale && !result.stdout} />
            {result.output_truncated && (
              <p className="text-xs text-muted-foreground">Output was truncated at the sandbox limit.</p>
            )}
          </div>
        )}
      </div>
    </Panel>
  )
}
