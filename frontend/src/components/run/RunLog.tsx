import type { ReactNode } from "react"

import type { CriticResult, ExecutionResult, Run } from "@/api/types"
import { Disclosure } from "@/components/Disclosure"
import { InlineText } from "@/components/run/InlineText"
import { OutputBlock } from "@/components/run/OutputBlock"
import { formatCount, formatDateTime, formatDuration, formatSpan } from "@/lib/format"
import {
  ACTION_LABELS,
  EXECUTION_STATUS,
  executionErrorTypeLabel,
  STAGE_ACTIVITY,
  VERDICTS,
} from "@/lib/labels"
import {
  criticFreshness,
  evidenceAttempt,
  executionAttempt,
  executionFreshness,
  isTerminal,
  workDurationMs,
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
      <dd className="min-w-0 break-words">{children}</dd>
    </>
  )
}

function Part({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-2.5">
      <h3 className="text-sm font-medium">{title}</h3>
      {children}
    </section>
  )
}

/** A previous attempt's result is history: labelled as such and never coloured as current. */
function attemptTitle(name: string, run: Run, freshness: Freshness) {
  const attempt = evidenceAttempt(run, freshness)
  return (
    <>
      {name}
      <span className="font-normal text-muted-foreground">
        {freshness === "stale" ? ` · previous attempt (${attempt})` : ` · attempt ${attempt}`}
      </span>
    </>
  )
}

function Execution({
  result,
  historical,
  unavailable = "The sandbox couldn't run the code, so this says nothing about whether the solution is correct.",
}: {
  result: ExecutionResult
  historical: boolean
  /** What an unavailable sandbox means for this result. */
  unavailable?: string
}) {
  const infrastructure = result.status === "infrastructure_error"
  const failing = result.status !== "passed"
  const errorType = executionErrorTypeLabel(result.error_type)
  return (
    <div className="space-y-3">
      <Facts>
        <Fact label="Result">
          <span className={cn(!historical && failing && !infrastructure && "text-destructive")}>
            {EXECUTION_STATUS[result.status]}
          </span>
        </Fact>
        {(result.tests_passed !== null || result.tests_failed !== null) && (
          <Fact label="Tests">
            {[
              result.tests_passed !== null ? `${result.tests_passed} passed` : null,
              result.tests_failed ? `${result.tests_failed} failed` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </Fact>
        )}
        {errorType && !infrastructure && <Fact label="Error">{errorType}</Fact>}
        <Fact label="Duration">{formatDuration(result.duration_ms)}</Fact>
        {result.exit_code !== null && !infrastructure && (
          <Fact label="Exit code">
            <span className="font-mono">{result.exit_code}</span>
          </Fact>
        )}
      </Facts>
      {infrastructure ? (
        <p className="text-sm text-muted-foreground">{unavailable}</p>
      ) : (
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
            <p className="text-xs text-muted-foreground">Output was cut off at the sandbox output limit.</p>
          )}
        </div>
      )}
    </div>
  )
}

/** Why a recommended action wasn't carried out, when the run's own outcome explains it. */
function actionNote(run: Run, review: CriticResult): string | null {
  const code = run.error?.code
  if (code === "revision_budget_exhausted" && review.recommended_action.startsWith("revise_")) {
    return "Not carried out: no fixes were left."
  }
  if (code === "sandbox_unavailable" && review.recommended_action === "retry_execution") {
    return "Not carried out: the tests had already been retried."
  }
  return null
}

function Review({ run, review, historical }: { run: Run; review: CriticResult; historical: boolean }) {
  const note = historical ? null : actionNote(run, review)
  return (
    <div className="space-y-2 text-sm">
      <p className="font-medium">{VERDICTS[review.verdict]}</p>
      <p className="leading-relaxed text-muted-foreground">
        <InlineText text={review.reason} />
      </p>
      {review.code_issue && (
        <p>
          <span className="text-muted-foreground">Code: </span>
          <InlineText text={review.code_issue} />
        </p>
      )}
      {review.test_issue && (
        <p>
          <span className="text-muted-foreground">Tests: </span>
          <InlineText text={review.test_issue} />
        </p>
      )}
      {!historical && (
        <p className="text-muted-foreground">
          Recommended: <span className="text-foreground">{ACTION_LABELS[review.recommended_action]}</span>
          {note && <span className="block">{note}</span>}
        </p>
      )}
    </div>
  )
}

/**
 * Everything technical, in one place: test output, the AI review, earlier attempts, errors
 * and timing. Collapsed unless it explains why the run couldn't be verified.
 */
export function RunLog({
  run,
  open,
  onOpenChange,
}: {
  run: Run
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const execution = executionFreshness(run)
  const review = criticFreshness(run)
  const stale = execution === "stale" || review === "stale"
  const attempts = executionAttempt(run)
  const fixesAndRetries = [
    run.revision_count > 0 ? formatCount(run.revision_count, "fix", "fixes") : null,
    run.execution_retry_count > 0 ? formatCount(run.execution_retry_count, "retry", "retries") : null,
  ].filter(Boolean)
  const error = run.error && run.error.code !== "approval_rejected" ? run.error : null
  const worked = workDurationMs(run)

  return (
    <section id="run-log" aria-labelledby="run-log-heading" className="scroll-mt-6">
      <Disclosure
        open={open}
        onOpenChange={onOpenChange}
        summary={
          <h2 id="run-log-heading" className="font-semibold text-foreground">
            Run log
          </h2>
        }
      >
        <div className="space-y-6 pt-2 pl-5.5">
          {stale && (
            <p className="text-sm text-muted-foreground">
              {run.status === "running"
                ? `Attempt ${attempts} is running. The results below are from the previous attempt.`
                : `Attempt ${attempts} didn't finish. The results below are from the previous attempt.`}
            </p>
          )}
          {run.existing_tests && (
            <Part title="Existing tests">
              <Execution
                result={run.existing_tests}
                historical={false}
                unavailable="The sandbox couldn't run the tests, so there is no result."
              />
            </Part>
          )}
          {execution && (
            <Part title={attemptTitle("Test run", run, execution)}>
              <Execution result={run.execution_result!} historical={execution === "stale"} />
            </Part>
          )}
          {review && (
            <Part title={attemptTitle("AI review", run, review)}>
              <Review run={run} review={run.critic_result!} historical={review === "stale"} />
            </Part>
          )}
          {error && (
            <Part title="Error">
              <Facts>
                <Fact label="Code">
                  <span className="font-mono text-xs">{error.code}</span>
                </Fact>
                <Fact label="Message">{error.message}</Fact>
                <Fact label="Stopped while">{STAGE_ACTIVITY[error.stage].toLowerCase()}</Fact>
              </Facts>
            </Part>
          )}
          <Part title="Run">
            <Facts>
              {run.mode === "solve" && (
                <Fact label="Attempts">
                  {fixesAndRetries.length > 0 ? `${attempts} (${fixesAndRetries.join(", ")})` : attempts}
                </Fact>
              )}
              <Fact label="Started">{formatDateTime(run.created_at)}</Fact>
              {isTerminal(run) && <Fact label="Ended">{formatDateTime(run.updated_at)}</Fact>}
              {worked !== null && <Fact label="AstraAi's work">{formatSpan(worked)}</Fact>}
            </Facts>
          </Part>
        </div>
      </Disclosure>
    </section>
  )
}
