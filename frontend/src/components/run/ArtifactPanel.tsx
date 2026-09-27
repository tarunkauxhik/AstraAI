import { useLayoutEffect, useRef, useState, type ReactNode } from "react"
import { RefreshCw } from "lucide-react"

import type { CaseCategory, GeneratedTestCase, Run, RunStage } from "@/api/types"
import { Disclosure } from "@/components/Disclosure"
import { CodeViewer } from "@/components/run/CodeViewer"
import { VerificationDetails } from "@/components/run/VerificationDetails"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { formatCount } from "@/lib/format"
import { LANGUAGE_LABELS } from "@/lib/labels"
import { cn } from "@/lib/utils"

export type ArtifactTab = "solution" | "tests" | "details"

/** Tab panels take keyboard focus, so they need a visible focus ring. */
const PANEL = "space-y-6 rounded-sm focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring"

const FILE_NAMES = {
  python: { solution: "solution.py", tests: "test_solution.py" },
  cpp: { solution: "solution.cpp", tests: "test_solution.cpp" },
} as const

const CATEGORY_LABELS: Record<CaseCategory, string> = {
  basic: "Basic",
  boundary: "Boundary",
  empty_or_small: "Empty or small",
  duplicates: "Duplicates",
  negative_or_zero: "Negative or zero",
  performance: "Performance",
  invalid_input: "Invalid input",
}

/** Quiet placeholder: whether the artifact is coming now, later, or never. */
function Pending({ run, stages, what }: { run: Run; stages: RunStage[]; what: string }) {
  const producing = run.status === "running" && stages.includes(run.stage)
  const text = producing
    ? `AstraAi is working on the ${what}.`
    : run.status === "failed"
      ? `No ${what} was produced.`
      : `The ${what} will appear here.`
  return (
    <div className="space-y-3 py-6">
      {producing && (
        <div className="max-w-md space-y-2" aria-hidden="true">
          <Skeleton className="h-3 w-3/4" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      )}
      <p className="text-sm text-muted-foreground">{text}</p>
    </div>
  )
}

function Heading({ children }: { children: ReactNode }) {
  return <h3 className="text-sm font-semibold">{children}</h3>
}

/** `**strong**` and `*emphasis*`; a lone `*` with a space beside it (as in `a * b`) stays literal. */
const EMPHASIS = /(\*\*[^*]+\*\*|\*[^\s*](?:[^*]*[^\s*])?\*)/

function Emphasis({ text }: { text: string }) {
  return text.split(EMPHASIS).map((part, index) =>
    index % 2 === 0 ? (
      part
    ) : part.startsWith("**") ? (
      <strong key={index} className="font-semibold text-foreground">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <em key={index}>{part.slice(1, -1)}</em>
    ),
  )
}

/** The model's plain-text notes: `code` spans (kept literal) and emphasis, rendered as text only. */
function InlineText({ text }: { text: string }) {
  return (
    <>
      {text.split(/(`[^`]+`)/).map((part, index) =>
        part.startsWith("`") && part.endsWith("`") && part.length > 1 ? (
          <code key={index} className="rounded bg-muted px-1 font-mono text-[0.85em] text-foreground">
            {part.slice(1, -1)}
          </code>
        ) : (
          <Emphasis key={index} text={part} />
        ),
      )}
    </>
  )
}

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
    <section className="space-y-1.5">
      <Heading>Approach</Heading>
      <div
        ref={body}
        className={
          "space-y-2 text-sm leading-6 text-muted-foreground " + (expanded ? "" : "line-clamp-3")
        }
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
          className="rounded-sm text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </section>
  )
}

function Literal({ children }: { children: string }) {
  return (
    <code className="block rounded bg-muted px-2 py-1 font-mono text-xs leading-5 break-all whitespace-pre-wrap">
      {children}
    </code>
  )
}

function TestCaseRow({ testCase }: { testCase: GeneratedTestCase }) {
  return (
    <li className="py-2">
      <Disclosure
        summary={
          <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="font-mono text-[13px] text-foreground">{testCase.name}</span>
            <span className="text-xs">{CATEGORY_LABELS[testCase.category] ?? testCase.category}</span>
          </span>
        }
      >
        <div className="space-y-2 pl-5.5">
          <p className="text-sm text-muted-foreground">{testCase.description}</p>
          <dl className="grid gap-x-3 gap-y-1.5 sm:grid-cols-[5.5rem_minmax(0,1fr)]">
            {testCase.input && (
              <>
                <dt className="text-xs text-muted-foreground sm:pt-1">Input</dt>
                <dd>
                  <Literal>{testCase.input}</Literal>
                </dd>
              </>
            )}
            {testCase.input_generator && (
              <>
                <dt className="text-xs text-muted-foreground sm:pt-1">Generated</dt>
                <dd>
                  <Literal>{testCase.input_generator}</Literal>
                </dd>
              </>
            )}
            <dt className="text-xs text-muted-foreground sm:pt-1">Expected</dt>
            <dd>
              <Literal>{testCase.expected_output}</Literal>
            </dd>
          </dl>
        </div>
      </Disclosure>
    </li>
  )
}

function Bullets({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  )
}

interface ArtifactPanelProps {
  run: Run
  tab: ArtifactTab
  onTabChange: (tab: ArtifactTab) => void
  verificationOpen: boolean
  onVerificationOpenChange: (open: boolean) => void
}

export function ArtifactPanel({ run, tab, onTabChange, verificationOpen, onVerificationOpenChange }: ArtifactPanelProps) {
  const files = FILE_NAMES[run.language]
  const code = run.generated_code
  const plan = run.generated_tests
  const requirements = run.requirements
  const language = LANGUAGE_LABELS[run.language]

  const coverage = plan
    ? Object.entries(
        plan.cases.reduce<Record<string, number>>((counts, testCase) => {
          counts[testCase.category] = (counts[testCase.category] ?? 0) + 1
          return counts
        }, {}),
      )
    : []

  return (
    <Tabs value={tab} onValueChange={(value) => onTabChange(value as ArtifactTab)} className="gap-4">
      <TabsList aria-label="Run results">
        <TabsTrigger value="solution">Solution</TabsTrigger>
        <TabsTrigger value="tests">Tests</TabsTrigger>
        <TabsTrigger value="details">Details</TabsTrigger>
      </TabsList>

      <TabsContent value="solution" className={PANEL}>
        {code ? (
          <>
            {run.revision_count > 0 && (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <RefreshCw className="size-3.5" aria-hidden="true" />
                Latest version, after {formatCount(run.revision_count, "repair")}.
              </p>
            )}
            <CodeViewer code={code.solution_code} label={files.solution} meta={<span className="text-xs text-muted-foreground">{language}</span>} />
            {code.explanation && <Approach text={code.explanation} />}
          </>
        ) : (
          <Pending run={run} stages={["analyzing", "generating_tests", "generating_code"]} what="solution" />
        )}
      </TabsContent>

      <TabsContent value="tests" className={PANEL}>
        {plan ? (
          <>
            <dl className="grid gap-4 text-sm sm:grid-cols-2">
              <div>
                <dt className="font-semibold">Interface</dt>
                <dd className="mt-1 font-mono text-[13px] wrap-break-word text-muted-foreground">{plan.interface}</dd>
              </div>
              <div>
                <dt className="font-semibold">How results are compared</dt>
                <dd className="mt-1 text-muted-foreground">{plan.comparison}</dd>
              </div>
            </dl>
            <section className="space-y-2">
              <Heading>Test cases ({plan.cases.length})</Heading>
              <ul className="flex flex-wrap gap-1.5" aria-label="Coverage by category">
                {coverage.map(([category, count]) => (
                  <li key={category}>
                    <Badge variant="outline" className="rounded-md font-normal text-muted-foreground">
                      {CATEGORY_LABELS[category as CaseCategory] ?? category} {count}
                    </Badge>
                  </li>
                ))}
              </ul>
              <ul className="divide-y">
                {plan.cases.map((testCase) => (
                  <TestCaseRow key={testCase.name} testCase={testCase} />
                ))}
              </ul>
            </section>
            {code && (
              <Disclosure summary={`Test program (${files.tests})`}>
                <CodeViewer code={code.test_code} label={files.tests} />
              </Disclosure>
            )}
          </>
        ) : (
          <Pending run={run} stages={["analyzing", "generating_tests"]} what="tests" />
        )}
      </TabsContent>

      <TabsContent value="details" className={cn(PANEL, "space-y-0 divide-y")}>
        <Disclosure
          id="verification-details"
          summary={<span className="font-semibold text-foreground">Verification details</span>}
          open={verificationOpen}
          onOpenChange={onVerificationOpenChange}
          className="pb-3"
        >
          <VerificationDetails run={run} />
        </Disclosure>
        <Disclosure summary={<span className="font-semibold text-foreground">Requirements</span>} className="py-3">
          {requirements ? (
            <div className="space-y-4">
              <p className="text-sm">{requirements.problem_summary}</p>
              <div className="grid gap-4 sm:grid-cols-2">
                <section className="space-y-1">
                  <Heading>Expected input</Heading>
                  <p className="text-sm text-muted-foreground">{requirements.expected_input}</p>
                </section>
                <section className="space-y-1">
                  <Heading>Expected output</Heading>
                  <p className="text-sm text-muted-foreground">{requirements.expected_output}</p>
                </section>
              </div>
              <section className="space-y-1">
                <Heading>Functional requirements</Heading>
                <Bullets items={requirements.functional_requirements} empty="None stated." />
              </section>
              <section className="space-y-1">
                <Heading>Edge cases</Heading>
                <Bullets items={requirements.edge_cases} empty="None identified." />
              </section>
              <section className="space-y-1">
                <Heading>Constraints</Heading>
                <Bullets items={requirements.constraints} empty="None stated." />
              </section>
              <section className="space-y-1">
                <Heading>{language} requirements</Heading>
                <Bullets items={requirements.relevant_language_requirements} empty="None stated." />
              </section>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {run.status === "failed" ? "No requirements were produced." : "The requirements will appear here."}
            </p>
          )}
        </Disclosure>
      </TabsContent>
    </Tabs>
  )
}
