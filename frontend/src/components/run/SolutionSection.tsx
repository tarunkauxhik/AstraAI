import { useLayoutEffect, useRef, useState } from "react"
import { Check } from "lucide-react"

import type { Run } from "@/api/types"
import { CodeViewer } from "@/components/run/CodeViewer"
import { InlineText } from "@/components/run/InlineText"
import { SectionHeading, SectionSkeleton } from "@/components/run/Section"
import { FILE_NAMES, LANGUAGE_LABELS } from "@/lib/labels"
import { codeStatus, isTerminal, type CodeStatus } from "@/lib/run-view"
import { cn, TOUCH_TARGET } from "@/lib/utils"

/** Split a note into paragraphs and "- " / "* " bullet lists. */
function noteBlocks(text: string): ({ kind: "p"; text: string } | { kind: "ul"; items: string[] })[] {
  const blocks: ({ kind: "p"; text: string } | { kind: "ul"; items: string[] })[] = []
  for (const raw of text.split("\n")) {
    const line = raw.trim()
    if (!line) continue
    const bullet = /^[-*•]\s+(.*)$/.exec(line)
    const last = blocks.at(-1)
    if (bullet) {
      if (last?.kind === "ul") last.items.push(bullet[1])
      else blocks.push({ kind: "ul", items: [bullet[1]] })
    } else {
      blocks.push({ kind: "p", text: line })
    }
  }
  return blocks
}

/**
 * The model's explanation: readable, clamped to three whole lines until expanded. A line clamp
 * (not a fixed height) cuts between lines, so block spacing can never slice a line in half.
 */
function Approach({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false)
  const [overflowing, setOverflowing] = useState(false)
  const body = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const element = body.current
    if (element && !expanded) setOverflowing(element.scrollHeight > element.clientHeight + 1)
  }, [text, expanded])

  return (
    <div className="space-y-1.5">
      <h3 className="text-sm font-medium">Approach</h3>
      <div
        ref={body}
        className={cn("space-y-2 text-sm leading-6 text-muted-foreground", !expanded && "line-clamp-3")}
      >
        {noteBlocks(text).map((block, index) =>
          block.kind === "p" ? (
            <p key={index}>
              <InlineText text={block.text} />
            </p>
          ) : (
            <ul key={index} className="list-disc space-y-1 pl-5">
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>
                  <InlineText text={item} />
                </li>
              ))}
            </ul>
          ),
        )}
      </div>
      {(overflowing || expanded) && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className={cn(
            TOUCH_TARGET,
            "rounded-sm text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline",
          )}
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  )
}

/** Whether this exact code passed its checks, attached to the code itself. Never a promise of
 * correctness: AstraAi wrote these tests itself. */
function CodeStatusLabel({ status, final }: { status: CodeStatus; final: boolean }) {
  if (status === "verified") {
    return (
      <span className="flex items-center gap-1 font-medium text-success">
        <Check className="size-3.5" aria-hidden="true" />
        Checks passed
      </span>
    )
  }
  if (status === "checking") return <span>Checking…</span>
  // Still being worked on, it's just a draft; once the run is over it needs attention.
  return <span className={cn(final && "font-medium text-warning")}>Checks not passed</span>
}

export function SolutionSection({ run }: { run: Run }) {
  const code = run.generated_code
  if (!code) {
    return run.stage === "generating_code" ? (
      <SectionSkeleton id="solution" title="Solution" note="Writing…" />
    ) : null
  }

  return (
    <section id="solution" aria-labelledby="solution-heading" className="scroll-mt-6 space-y-4">
      <SectionHeading id="solution-heading">Solution</SectionHeading>
      <CodeViewer
        code={code.solution_code}
        label={FILE_NAMES[run.language].solution}
        meta={
          <>
            <span aria-hidden="true">·</span>
            <span>{LANGUAGE_LABELS[run.language]}</span>
            <span aria-hidden="true">·</span>
            <CodeStatusLabel status={codeStatus(run)} final={isTerminal(run)} />
          </>
        }
      />
      {code.explanation && <Approach text={code.explanation} />}
    </section>
  )
}
