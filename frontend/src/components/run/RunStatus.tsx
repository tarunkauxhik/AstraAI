import { useCallback, useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, Check, Loader2, Plus, X } from "lucide-react"
import { Link, useNavigate } from "react-router"

import type { Run } from "@/api/types"
import { CopyButton } from "@/components/CopyButton"
import { ApprovalCountdown } from "@/components/run/ApprovalCountdown"
import { InlineText } from "@/components/run/InlineText"
import { Button } from "@/components/ui/button"
import { useApproval, useExtendApproval } from "@/hooks/useApproval"
import { useCreateRun } from "@/hooks/useCreateRun"
import { boostRunPolling, runQueryKey } from "@/hooks/useRun"
import { useServerNow } from "@/hooks/useServerNow"
import { formatClock, formatCount, formatSpan } from "@/lib/format"
import { FILE_NAMES } from "@/lib/labels"
import {
  describeApprovalError,
  describeEnding,
  failingEvidence,
  runPhase,
  testRunSummary,
  workDurationMs,
  workSteps,
  type EndingAction,
  type WorkStep,
} from "@/lib/run-view"
import { cn, TOUCH_TARGET } from "@/lib/utils"

/** Touch-sized on phones, compact beside the content on desktop. */
const ACTION = "h-11 lg:h-9"

function Elapsed({ since }: { since: string }) {
  const now = useServerNow()
  const start = Date.parse(since)
  if (Number.isNaN(start)) return null
  return (
    <span className="font-normal text-muted-foreground tabular-nums">
      <span aria-hidden="true">· </span>
      {formatClock(now - start)}
    </span>
  )
}

const STEP_STATE: Record<WorkStep["state"], string> = {
  done: "done",
  current: "in progress",
  pending: "not started",
}

function StepMarker({ step }: { step: WorkStep }) {
  return (
    <span className="flex h-5 w-4 shrink-0 items-center justify-center" aria-hidden="true">
      {step.state === "done" &&
        (step.problem ? (
          <X className="size-3.5 text-destructive" />
        ) : (
          <Check className="size-3.5 text-muted-foreground" />
        ))}
      {/* The only animation on the page: something is happening right now. */}
      {step.state === "current" && (
        <span className="size-2 animate-pulse rounded-full bg-brand motion-reduce:animate-none" />
      )}
      {step.state === "pending" && <span className="size-2 rounded-full border border-muted-foreground/40" />}
    </span>
  )
}

function WorkList({ steps }: { steps: WorkStep[] }) {
  return (
    <ol className="space-y-2 text-sm" aria-label="Progress">
      {steps.map((step) => (
        <li
          key={step.id}
          aria-current={step.state === "current" ? "step" : undefined}
          className="flex gap-2.5"
        >
          <StepMarker step={step} />
          <div className="min-w-0 leading-5">
            <p
              className={cn(
                step.state === "pending" ? "text-muted-foreground" : "text-foreground",
                step.state === "current" && "font-medium",
              )}
            >
              {step.label}
              <span className="sr-only">: {step.problem ? "problem found" : STEP_STATE[step.state]}</span>
            </p>
            {step.detail && (
              <p className="mt-0.5 text-muted-foreground">
                <InlineText text={step.detail} />
              </p>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}

/** On phones the review actions dock to the bottom; the page reserves exactly their height. */
function useDockHeight() {
  const dock = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const element = dock.current
    if (!element || typeof ResizeObserver === "undefined") return
    const root = document.documentElement
    const observer = new ResizeObserver(() =>
      root.style.setProperty("--dock-height", `${element.offsetHeight}px`),
    )
    observer.observe(element)
    return () => {
      observer.disconnect()
      root.style.removeProperty("--dock-height")
    }
  }, [])
  return dock
}

interface ReviewProps {
  run: Run
  onDecided: () => void
  onViewTests: () => void
}

/**
 * The decision. Nothing is applied locally: the panel changes when a refetch shows the
 * server moved on. The actions exist once; on phones they dock to the bottom of the screen.
 */
function Review({ run, onDecided, onViewTests }: ReviewProps) {
  const queryClient = useQueryClient()
  const approval = useApproval(run.run_id)
  const extend = useExtendApproval(run.run_id)
  const [expiryReached, setExpiryReached] = useState(false)
  const dock = useDockHeight()

  // Zero on the countdown only means "check with the server"; the run stays as reported.
  const handleExpiryReached = useCallback(() => {
    setExpiryReached(true)
    boostRunPolling(run.run_id)
    void queryClient.invalidateQueries({ queryKey: runQueryKey(run.run_id) })
  }, [queryClient, run.run_id])

  const locked = approval.isPending || approval.isSuccess || expiryReached
  const result = run.execution_result
  const fixes = run.revision_count > 0 ? ` after ${formatCount(run.revision_count, "fix", "fixes")}` : ""
  // Execution evidence leads; the model's own assessment is secondary to it.
  const tested = result
    ? `${testRunSummary(result, run.generated_tests?.cases.length ?? null)}${fixes}`
    : "All checks passed"
  const pending = approval.isPending ? approval.variables : null

  function decide(decision: "approve" | "reject") {
    if (locked) return
    onDecided()
    approval.mutate(decision)
  }

  return (
    <div className="space-y-4">
      <div>
        <p className="flex items-center gap-1.5 font-medium text-success">
          <Check className="size-4" aria-hidden="true" />
          {tested}
        </p>
        <p className="mt-0.5 pl-5.5 text-xs text-muted-foreground">AI review found no issues</p>
      </div>
      <p className="text-sm text-muted-foreground">
        AstraAi wrote these tests — check that they match what you meant.{" "}
        <button
          type="button"
          onClick={onViewTests}
          className={cn(TOUCH_TARGET, "rounded-sm font-medium text-foreground underline underline-offset-4 hover:text-brand")}
        >
          View tests
        </button>
      </p>

      <div
        ref={dock}
        role="group"
        aria-label="Review actions"
        className="space-y-1.5 max-lg:fixed max-lg:inset-x-0 max-lg:bottom-0 max-lg:z-30 max-lg:m-0 max-lg:border-t max-lg:bg-background max-lg:px-4 sm:max-lg:px-6 max-lg:pt-2 max-lg:pb-[max(0.75rem,env(safe-area-inset-bottom))]"
      >
        {run.approval_expires_at && (
          <ApprovalCountdown
            expiresAt={run.approval_expires_at}
            onReached={handleExpiryReached}
            onMoreTime={() => extend.mutate()}
            extending={extend.isPending}
            disabled={locked}
          />
        )}
        <div className="flex gap-2">
          <Button onClick={() => decide("approve")} disabled={locked} className={cn(ACTION, "flex-2")}>
            {pending === "approve" ? (
              <Loader2 className="animate-spin" aria-hidden="true" />
            ) : (
              <Check aria-hidden="true" />
            )}
            {pending === "approve" ? "Accepting…" : "Accept"}
          </Button>
          <Button
            variant="outline"
            onClick={() => decide("reject")}
            disabled={locked}
            className={cn(ACTION, "flex-1")}
          >
            {pending === "reject" ? "Rejecting…" : "Reject"}
          </Button>
        </div>
      </div>

      <p className="text-xs leading-5 text-muted-foreground">
        Accepting marks this run complete. Nothing is published or deployed.
      </p>
      {approval.error && !approval.isPending && (
        <p role="alert" className="text-sm text-destructive">
          {describeApprovalError(approval.error)}
        </p>
      )}
      {extend.error && !extend.isPending && (
        <p role="alert" className="text-sm text-destructive">
          {describeApprovalError(extend.error)}
        </p>
      )}
      {approval.isSuccess && (
        <p role="status" className="text-sm text-muted-foreground">
          Decision sent. Updating…
        </p>
      )}
      {expiryReached && !approval.isSuccess && (
        <p role="status" className="text-sm text-muted-foreground">
          Checking whether the review window has closed…
        </p>
      )}
    </div>
  )
}

function EndingActions({ run, actions, onOpenLog }: { run: Run; actions: EndingAction[]; onOpenLog: () => void }) {
  const navigate = useNavigate()
  const createRun = useCreateRun()
  const code = run.generated_code

  function runAgain() {
    createRun.mutate(
      { task: run.task, language: run.language },
      { onSuccess: (accepted) => navigate(`/runs/${accepted.run_id}`) },
    )
  }

  // The first available action leads; the rest are quieter.
  const available = actions.filter((action) => action !== "copy" || code !== null)
  const variant = (action: EndingAction) =>
    action === available[0] ? "default" : action === "log" ? "ghost" : "outline"

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {available.map((action) => {
          switch (action) {
            case "copy":
              return (
                <CopyButton
                  key={action}
                  text={code!.solution_code}
                  label={FILE_NAMES[run.language].solution}
                  variant={variant(action)}
                  size="lg"
                  className={ACTION}
                >
                  Copy solution
                </CopyButton>
              )
            case "new_run":
              return (
                <Button key={action} asChild variant={variant(action)} size="lg" className={ACTION}>
                  <Link to="/">
                    <Plus aria-hidden="true" />
                    New run
                  </Link>
                </Button>
              )
            case "run_again":
              return (
                <Button
                  key={action}
                  variant={variant(action)}
                  size="lg"
                  className={ACTION}
                  onClick={runAgain}
                  disabled={createRun.isPending}
                >
                  {createRun.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
                  {createRun.isPending ? "Starting…" : "Run again"}
                </Button>
              )
            case "edit":
              return (
                <Button
                  key={action}
                  variant={variant(action)}
                  size="lg"
                  className={ACTION}
                  onClick={() => navigate("/", { state: { task: run.task, language: run.language } })}
                >
                  Edit task
                </Button>
              )
            case "log":
              return (
                <Button key={action} variant={variant(action)} size="lg" className={ACTION} onClick={onOpenLog}>
                  Run log
                </Button>
              )
          }
        })}
      </div>
      {createRun.error && (
        <p role="alert" className="text-sm text-destructive">
          Couldn't start a new run. {createRun.error.detail}
        </p>
      )}
    </div>
  )
}

function Ending({ run, onOpenLog }: { run: Run; onOpenLog: () => void }) {
  const ending = describeEnding(run)
  const evidence = ending.kind === "unverified" ? failingEvidence(run) : null
  const worked = ending.kind === "accepted" ? workDurationMs(run) : null
  const description = worked !== null ? `${ending.description} · ${formatSpan(worked)}` : ending.description

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{description}</p>
      {evidence &&
        (evidence.source === "output" ? (
          <p className="font-mono text-xs leading-5 break-all text-destructive">{evidence.text}</p>
        ) : (
          <p className="text-sm">
            <span className="text-muted-foreground">AI review: </span>
            <InlineText text={evidence.text} />
          </p>
        ))}
      {run.status === "failed" && run.approval_status === "approved" && (
        <p className="text-sm text-muted-foreground">You accepted the solution, but the run couldn't finish.</p>
      )}
      <EndingActions run={run} actions={ending.actions} onOpenLog={onOpenLog} />
    </div>
  )
}

function Title({ run }: { run: Run }) {
  const phase = runPhase(run)
  switch (phase) {
    case "queued":
      return (
        <>
          <span id="status-title">Waiting to start</span> <Elapsed since={run.created_at} />
        </>
      )
    case "working":
      return (
        <>
          <span id="status-title">Working</span> <Elapsed since={run.created_at} />
        </>
      )
    case "resuming":
      return <span id="status-title">Accepting…</span>
    case "awaiting_approval":
      return <span id="status-title">Ready for review</span>
    default: {
      const ending = describeEnding(run)
      return (
        <>
          {ending.tone === "success" && <Check className="size-4 text-success" aria-hidden="true" />}
          {ending.tone === "attention" && <AlertTriangle className="size-4 text-warning" aria-hidden="true" />}
          <span id="status-title" className={cn(ending.tone === "success" && "text-success")}>
            {ending.title}
          </span>
        </>
      )
    }
  }
}

interface RunStatusProps {
  run: Run
  onViewTests: () => void
  onOpenLog: () => void
}

/** The one place that says where the run stands and what the user can do about it. */
export function RunStatus({ run, onViewTests, onOpenLog }: RunStatusProps) {
  const phase = runPhase(run)
  const heading = useRef<HTMLHeadingElement>(null)
  const [decided, setDecided] = useState(false)

  // After a decision its buttons disappear. The heading stays mounted as its text changes,
  // so moving focus there keeps keyboard and screen reader users on the outcome.
  useEffect(() => {
    if (decided && phase !== "awaiting_approval") heading.current?.focus()
  }, [decided, phase])

  return (
    <section aria-labelledby="status-title" className="space-y-4">
      <h2
        id="status-heading"
        ref={heading}
        tabIndex={-1}
        className="flex items-center gap-2 rounded-sm text-base font-semibold"
      >
        <Title run={run} />
      </h2>
      {phase === "queued" || phase === "working" ? (
        <WorkList steps={workSteps(run)} />
      ) : phase === "awaiting_approval" ? (
        <Review run={run} onDecided={() => setDecided(true)} onViewTests={onViewTests} />
      ) : phase === "resuming" ? null : (
        <Ending run={run} onOpenLog={onOpenLog} />
      )}
    </section>
  )
}
