import type { ReactNode } from "react"
import { AlertTriangle, Check, ChevronRight, X } from "lucide-react"

import type { FileChange, Run } from "@/api/types"
import { InlineText } from "@/components/run/InlineText"
import { OutputBlock } from "@/components/run/OutputBlock"
import { SectionHeading, SectionSkeleton } from "@/components/run/Section"
import { formatCount } from "@/lib/format"
import {
  existingTestsSummary,
  isWorking,
  reviewFinding,
  testName,
  verificationOutcome,
  verificationSummary,
} from "@/lib/run-view"
import { cn } from "@/lib/utils"

/** Diffs open by themselves while the changed lines shown stay under this. */
const OPEN_LINE_BUDGET = 200

function lineTone(line: string): string | undefined {
  if (line.startsWith("@@")) return "bg-muted/40 text-muted-foreground"
  if (line.startsWith("+")) return "bg-success/10 text-success"
  if (line.startsWith("-")) return "bg-destructive/10 text-destructive"
  if (line.startsWith("\\")) return "text-muted-foreground"
  return undefined
}

/** A read-only unified diff: its hunks, without the git header the summary repeats. */
function DiffView({ file }: { file: FileChange }) {
  const lines = file.diff.replace(/\n$/, "").split("\n")
  const firstHunk = lines.findIndex((line) => line.startsWith("@@"))
  if (firstHunk === -1) {
    return <p className="border-t px-3 py-2 text-xs text-muted-foreground">An empty new file.</p>
  }
  return (
    <pre
      tabIndex={0}
      aria-label={`Changes to ${file.path}`}
      className="max-h-[32rem] overflow-auto border-t py-1 font-mono text-xs leading-5"
    >
      {lines.slice(firstHunk).map((line, index) => (
        <div key={index} className={cn("min-w-max px-3 whitespace-pre", lineTone(line))}>
          {line || " "}
        </div>
      ))}
    </pre>
  )
}

function FileDiff({ file, open }: { file: FileChange; open: boolean }) {
  return (
    <details open={open} className="rounded-md border bg-[oklch(0.135_0.004_250)]">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-1.5 text-sm select-none pointer-coarse:min-h-11 [&::-webkit-details-marker]:hidden">
        <ChevronRight className="disclosure-chevron size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        <span className="min-w-0 truncate font-mono text-xs">{file.path}</span>
        {file.status === "added" && <span className="text-xs text-muted-foreground">new</span>}
        <span className="ml-auto shrink-0 font-mono text-xs">
          <span className="text-success">+{file.additions}</span>{" "}
          <span className="text-destructive">−{file.deletions}</span>
        </span>
      </summary>
      <DiffView file={file} />
    </details>
  )
}

/** Which files open by themselves: in order, while the lines shown stay within the budget. */
function openFiles(files: FileChange[]): Set<string> {
  const open = new Set<string>()
  let shown = 0
  for (const file of files) {
    shown += file.additions + file.deletions
    if (shown > OPEN_LINE_BUDGET) break
    open.add(file.path)
  }
  return open
}

/** What changed, file by file: code first, then tests, then everything else. */
export function ChangesSection({ run }: { run: Run }) {
  // While the one repair works, its diff isn't known yet: never show one in between.
  const fixing = run.stage === "fixing_issue"
  const changes = fixing ? null : run.changes
  if (changes === null || changes.files.length === 0) {
    return run.stage === "making_changes" || fixing ? (
      <SectionSkeleton id="changes" title="Changes" note={fixing ? "Fixing an issue…" : "Making changes…"} />
    ) : null
  }
  const additions = changes.files.reduce((sum, file) => sum + file.additions, 0)
  const deletions = changes.files.reduce((sum, file) => sum + file.deletions, 0)
  const open = openFiles(changes.files)
  return (
    <section id="changes" aria-labelledby="changes-heading" className="scroll-mt-6 space-y-3">
      <SectionHeading
        id="changes-heading"
        aside={
          <>
            {formatCount(changes.files.length, "file")} changed ·{" "}
            <span className="text-success">+{additions}</span>{" "}
            <span className="text-destructive">−{deletions}</span>
          </>
        }
      >
        Changes
      </SectionHeading>
      <div className="space-y-2">
        {changes.files.map((file) => (
          <FileDiff key={file.path} file={file} open={open.has(file.path)} />
        ))}
      </div>
    </section>
  )
}

type Mark = "ok" | "problem" | "flag" | "neutral"

function CheckMark({ mark }: { mark: Mark }) {
  return (
    <span className="flex h-5 w-4 shrink-0 items-center justify-center" aria-hidden="true">
      {mark === "ok" && <Check className="size-3.5 text-success" />}
      {mark === "problem" && <X className="size-3.5 text-destructive" />}
      {mark === "flag" && <AlertTriangle className="size-3.5 text-warning" />}
      {mark === "neutral" && <span className="size-1.5 rounded-full bg-muted-foreground/50" />}
    </span>
  )
}

/** What a mark means, for screen readers; a passing or neutral row needs no word. */
const MARK_TEXT: Record<Mark, string> = { ok: "", problem: "problem: ", flag: "to check: ", neutral: "" }

function CheckRow({ mark, label, children }: { mark: Mark; label: string; children: ReactNode }) {
  return (
    <li className="flex gap-2.5 text-sm">
      <CheckMark mark={mark} />
      <p className="min-w-0 leading-5">
        <span className="text-muted-foreground">{label} — </span>
        {MARK_TEXT[mark] && <span className="sr-only">{MARK_TEXT[mark]}</span>}
        <span className={cn(mark === "problem" && "text-destructive")}>{children}</span>
      </p>
    </li>
  )
}

function names(ids: string[]): string {
  const shown = ids.slice(0, 3).map(testName).join(", ")
  return ids.length > 3 ? `${shown} and ${ids.length - 3} more` : shown
}

/**
 * The evidence, as a developer would check it: the repository's own tests, the tests the
 * change added, the final run, and an AI review finding only when there is one. Tests that
 * couldn't run are never called failures, and a review that found nothing claims nothing.
 */
export function ChecksSection({ run }: { run: Run }) {
  const existing = run.existing_tests
  if (existing === null || (!run.changes?.files.length && !isWorking(run))) return null
  // While the one repair works, the first change's results are no longer the answer.
  const fixing = run.stage === "fixing_issue"
  const after = fixing ? null : run.verification
  const checks = fixing ? null : run.checks
  const outcome = after ? verificationOutcome(after) : null
  const finding = fixing ? null : reviewFinding(run)

  const before = existing.tests_failed
    ? `${existing.tests_passed ?? 0} passed · ${existing.tests_failed} already failing`
    : existingTestsSummary(existing)
  let existingRow: ReactNode = <CheckRow mark="neutral" label="Existing tests">{before}</CheckRow>
  if (checks?.by_id && checks.broken.length > 0) {
    existingRow = (
      <CheckRow mark="problem" label="Existing tests">
        {formatCount(checks.broken.length, "test")} that passed before{" "}
        {checks.broken.length === 1 ? "fails" : "fail"} now: {names(checks.broken)}
      </CheckRow>
    )
  } else if (checks?.clean || (checks?.by_id && after !== null)) {
    // By test id, nothing that passed before fails now, whatever else does.
    const fixed = checks.fixed.length > 0 ? ` · ${checks.fixed.length} now fixed` : ""
    existingRow = (
      <CheckRow mark="ok" label="Existing tests">
        {before} · none broken{fixed}
      </CheckRow>
    )
  }

  const added = checks?.added ?? 0
  const newRow =
    checks !== null && added > 0 ? (
      checks.new_failing.length > 0 ? (
        <CheckRow mark="problem" label="New tests">
          {added} added · {names(checks.new_failing)} {checks.new_failing.length === 1 ? "fails" : "fail"}
        </CheckRow>
      ) : (
        <CheckRow mark={checks.clean ? "ok" : "neutral"} label="New tests">
          {checks.clean ? `${added} passed` : `${added} added`}
        </CheckRow>
      )
    ) : null

  const retest = run.first_attempt !== null
  let finalRow: ReactNode = null
  if (after !== null) {
    const mark: Mark =
      outcome === "passed" ? "ok" : outcome === "not_run" ? "flag" : checks?.clean ? "neutral" : "problem"
    finalRow = (
      <CheckRow mark={mark} label="Final test run">
        {verificationSummary(after)}
      </CheckRow>
    )
  } else if (run.stage === "running_tests" || fixing) {
    finalRow = (
      <CheckRow mark="neutral" label="Final test run">
        {fixing ? "Waiting for the fix…" : retest ? "Running again…" : "Running…"}
      </CheckRow>
    )
  }

  return (
    <section id="checks" aria-labelledby="checks-heading" className="scroll-mt-6 space-y-3">
      <SectionHeading id="checks-heading">Checks</SectionHeading>
      <ul className="space-y-1.5">
        {existingRow}
        {newRow}
        {finalRow}
        {finding && (
          <CheckRow mark="flag" label="AI review">
            flagged something to check: <InlineText text={finding} />
          </CheckRow>
        )}
      </ul>
      {outcome === "failed" && !checks?.clean && after?.stdout && (
        <OutputBlock label="Test output" text={after.stdout} defaultOpen tone="error" />
      )}
      {outcome === "not_run" && (
        <p className="text-sm text-muted-foreground">
          AstraAi couldn't run the tests on the changed repository, so they say nothing about the
          changes.
        </p>
      )}
    </section>
  )
}
