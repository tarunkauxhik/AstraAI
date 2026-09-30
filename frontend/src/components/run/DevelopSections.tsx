import { ChevronRight } from "lucide-react"

import type { FileChange, Run } from "@/api/types"
import { Disclosure } from "@/components/Disclosure"
import { InlineText } from "@/components/run/InlineText"
import { OutputBlock } from "@/components/run/OutputBlock"
import { SectionHeading, SectionSkeleton } from "@/components/run/Section"
import { formatCount } from "@/lib/format"
import { existingTestsSummary, isWorking, verificationOutcome, verificationSummary } from "@/lib/run-view"
import { cn } from "@/lib/utils"

/** Diffs this long start collapsed, so many files stay scannable. */
const OPEN_BY_DEFAULT = 3

function lineTone(line: string): string | undefined {
  if (line.startsWith("@@")) return "bg-muted/40 text-muted-foreground"
  if (line.startsWith("+")) return "bg-success/10 text-success"
  if (line.startsWith("-")) return "bg-destructive/10 text-destructive"
  if (line.startsWith("\\")) return "text-muted-foreground"
  return undefined
}

/** A read-only unified diff: its hunks, without the ---/+++ header the summary repeats. */
function DiffView({ file }: { file: FileChange }) {
  const lines = file.diff.replace(/\n$/, "").split("\n").slice(2)
  return (
    <pre
      tabIndex={0}
      aria-label={`Changes to ${file.path}`}
      className="max-h-[32rem] overflow-auto border-t py-1 font-mono text-xs leading-5"
    >
      {lines.map((line, index) => (
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

/** The primary DEVELOP result: what changed, file by file. */
export function ChangesSection({ run }: { run: Run }) {
  // While the one repair works, its diff isn't known yet: never show one in between.
  const fixing = run.stage === "fixing_issue"
  const changes = fixing ? null : run.changes
  if (changes === null) {
    return run.stage === "making_changes" || fixing ? (
      <SectionSkeleton id="changes" title="Changes" note={fixing ? "Fixing an issue…" : "Making changes…"} />
    ) : null
  }
  const additions = changes.files.reduce((sum, file) => sum + file.additions, 0)
  const deletions = changes.files.reduce((sum, file) => sum + file.deletions, 0)
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
          <FileDiff key={file.path} file={file} open={changes.files.length <= OPEN_BY_DEFAULT} />
        ))}
      </div>
      {changes.explanation && (
        <Disclosure summary="AstraAi's explanation">
          <p className="text-sm leading-relaxed">
            <InlineText text={changes.explanation} />
          </p>
        </Disclosure>
      )}
    </section>
  )
}

/** The evidence: the repository's own tests, before the change and after it. */
export function VerificationSection({ run }: { run: Run }) {
  const existing = run.existing_tests
  // While the one repair works, the first change's results are no longer the answer.
  const fixing = run.stage === "fixing_issue"
  const after = fixing ? null : run.verification
  if (existing === null || (run.changes === null && !isWorking(run))) return null
  const outcome = after ? verificationOutcome(after) : null
  const review = fixing ? null : run.critic_result
  return (
    <section id="verification" aria-labelledby="verification-heading" className="scroll-mt-6 space-y-3">
      <SectionHeading id="verification-heading">Verification</SectionHeading>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Existing tests</dt>
        <dd>{existingTestsSummary(existing)}</dd>
        {(after || run.stage === "running_tests" || fixing) && (
          <>
            <dt className="text-muted-foreground">After the changes</dt>
            <dd
              className={cn(
                outcome === "passed" && "text-success",
                outcome === "failed" && "text-destructive",
              )}
            >
              {after ? verificationSummary(after) : fixing ? "Waiting for the fix…" : "Running…"}
            </dd>
          </>
        )}
      </dl>
      {outcome === "failed" && after?.stdout && (
        <OutputBlock label="Test output" text={after.stdout} defaultOpen tone="error" />
      )}
      {outcome === "not_run" && (
        <p className="text-sm text-muted-foreground">
          AstraAi couldn't run the tests on the changed repository, so they say nothing about the
          changes yet.
        </p>
      )}
      {review && (
        <p className="text-xs text-muted-foreground">
          {review.verdict === "pass" ? (
            "AI review found no issues"
          ) : (
            <>
              AI review: <InlineText text={review.code_issue || review.test_issue || review.reason} />
            </>
          )}
        </p>
      )}
    </section>
  )
}
