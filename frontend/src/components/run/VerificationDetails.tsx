import type { ReactNode } from "react"

import type { CriticResult, ExecutionResult, Run } from "@/api/types"
import { Disclosure } from "@/components/Disclosure"
import { OutputBlock } from "@/components/run/OutputBlock"
import { TONE_TEXT } from "@/components/run/tone"
import { formatCount, formatDuration, formatTestResult } from "@/lib/format"
import { ACTION_LABELS, EXECUTION_STATUS, executionErrorTypeLabel, VERDICTS } from "@/lib/labels"
import {
  criticFreshness,
  evidenceAttempt,
  executionAttempt,
  executionFreshness,
  type Freshness,
} from "@/lib/run-view"
import { cn } from "@/lib/utils"

function Facts({ children }: { children: ReactNode }) {
  return <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">{children}</dl>
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </>
  )
}

/** Execution facts. A historical result loses its outcome colour: it isn't the current one. */
function ExecutionFacts({ result, historical }: { result: ExecutionResult; historical: boolean }) {
  const status = EXECUTION_STATUS[result.status]
  const tests = formatTestResult(result.tests_passed, result.tests_failed)
  const errorType = executionErrorTypeLabel(result.error_type)
  const infrastructure = result.status === "infrastructure_error"
  const failing = result.status !== "passed"

  return (
    <div className="space-y-3">
      <Facts>
        <Fact label="Result">
          <span className={cn(!historical && TONE_TEXT[status.tone])}>{status.label}</span>
        </Fact>
        {tests && <Fact label="Tests">{tests}</Fact>}
        {errorType && !infrastructure && <Fact label="Error">{errorType}</Fact>}
        <Fact label="Duration">{formatDuration(result.duration_ms)}</Fact>
        {result.exit_code !== null && !infrastructure && (
          <Fact label="Exit code">
            <span className="font-mono">{result.exit_code}</span>
          </Fact>
        )}
      </Facts>
      {infrastructure ? (
        <p className="text-sm text-muted-foreground">
          The verification environment couldn't run the code, so this says nothing about whether
          the code is correct.
        </p>
      ) : (
        <div className="space-y-2">
          {result.stdout && (
            <OutputBlock label="stdout" text={result.stdout} defaultOpen={!historical && failing} />
          )}
          {result.stderr && (
            <OutputBlock label="stderr" text={result.stderr} tone="error" defaultOpen={!historical && failing} />
          )}
          {result.output_truncated && (
            <p className="text-xs text-muted-foreground">Output was cut off at the sandbox output limit.</p>
          )}
        </div>
      )}
    </div>
  )
}

/** Why a recommended action wasn't carried out, when the run's own outcome explains it. */
function actionNote(run: Run, critic: CriticResult): string | null {
  const code = run.error?.code
  if (code === "revision_budget_exhausted" && critic.recommended_action.startsWith("revise_")) {
    return "Not carried out: AstraAi had no repairs left."
  }
  if (code === "sandbox_unavailable" && critic.recommended_action === "retry_execution") {
    return "Not carried out: verification had already been retried."
  }
  return null
}

function ReviewFacts({ run, critic, historical }: { run: Run; critic: CriticResult; historical: boolean }) {
  const verdict = VERDICTS[critic.verdict]
  const note = historical ? null : actionNote(run, critic)
  return (
    <div className="space-y-3">
      <p className={cn("text-sm font-medium", !historical && TONE_TEXT[verdict.tone])}>{verdict.label}</p>
      <p className="text-sm leading-relaxed">{critic.reason}</p>
      {critic.code_issue && (
        <div>
          <p className="text-sm font-medium">Code issue</p>
          <p className="text-sm text-muted-foreground">{critic.code_issue}</p>
        </div>
      )}
      {critic.test_issue && (
        <div>
          <p className="text-sm font-medium">Test issue</p>
          <p className="text-sm text-muted-foreground">{critic.test_issue}</p>
        </div>
      )}
      {!historical && (
        <p className="text-sm text-muted-foreground">
          Recommended: <span className="text-foreground">{ACTION_LABELS[critic.recommended_action]}</span>
          {note && <span className="block">{note}</span>}
        </p>
      )}
    </div>
  )
}

/** Current evidence, or a note about the newer attempt plus the previous result behind a disclosure. */
function EvidenceSection({
  title,
  run,
  freshness,
  pendingText,
  children,
}: {
  title: string
  run: Run
  freshness: Freshness | null
  pendingText: string
  children: (historical: boolean) => ReactNode
}) {
  return (
    <section className="space-y-3">
      <h4 className="text-sm font-semibold">
        {title}
        {freshness === "current" && (
          <span className="font-normal text-muted-foreground"> · attempt {evidenceAttempt(run, freshness)}</span>
        )}
      </h4>
      {freshness === null && <p className="text-sm text-muted-foreground">{pendingText}</p>}
      {freshness === "current" && children(false)}
      {freshness === "stale" && (
        <Disclosure summary={`Previous attempt (attempt ${evidenceAttempt(run, freshness)})`}>
          <div className="border-l pl-3 opacity-80">{children(true)}</div>
        </Disclosure>
      )}
    </section>
  )
}

/** Execution and review evidence, with earlier-attempt results clearly separated. */
export function VerificationDetails({ run }: { run: Run }) {
  const counters = [
    run.revision_count > 0 ? formatCount(run.revision_count, "revision") : null,
    run.execution_retry_count > 0 ? formatCount(run.execution_retry_count, "retry", "retries") : null,
  ].filter(Boolean)

  const stale = executionFreshness(run) === "stale" || criticFreshness(run) === "stale"
  const attempt = executionAttempt(run)

  return (
    <div className="space-y-6">
      {stale && (
        <p className="text-sm">
          {run.status === "running"
            ? `Attempt ${attempt} is in progress. Results below are from the previous attempt.`
            : `Attempt ${attempt} didn't finish before the run stopped. Results below are from the previous attempt.`}
        </p>
      )}
      {counters.length > 0 && (
        <p className="text-sm text-muted-foreground">
          {/* The stale note above already names the attempt. */}
          {stale ? counters.join(" · ") : `Attempt ${attempt} · ${counters.join(" · ")}`}
        </p>
      )}
      <EvidenceSection
        title="Execution"
        run={run}
        freshness={executionFreshness(run)}
        pendingText="The tests haven't run yet."
      >
        {(historical) => <ExecutionFacts result={run.execution_result!} historical={historical} />}
      </EvidenceSection>
      <EvidenceSection
        title="Review"
        run={run}
        freshness={criticFreshness(run)}
        pendingText="No review yet."
      >
        {(historical) => <ReviewFacts run={run} critic={run.critic_result!} historical={historical} />}
      </EvidenceSection>
    </div>
  )
}
