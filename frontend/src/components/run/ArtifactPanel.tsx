import type { ReactNode } from "react"
import { RefreshCw } from "lucide-react"

import type { CaseCategory, GeneratedTestCase, GeneratedTests, Run, RunStage } from "@/api/types"
import { CodeViewer } from "@/components/run/CodeViewer"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { LANGUAGE_LABELS } from "@/lib/labels"

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

/** Empty state that says whether the artifact is being produced now, later, or never. */
function Pending({ run, stage, what }: { run: Run; stage: RunStage; what: string }) {
  const producing = run.status === "running" && run.stage === stage
  const text = producing
    ? `AstraAi is producing the ${what} now.`
    : run.status === "failed"
      ? `No ${what} was produced.`
      : `The ${what} will appear here once AstraAi produces it.`
  return (
    <div className="rounded-lg border border-dashed px-4 py-8 text-center">
      {producing && (
        <div className="mx-auto mb-4 max-w-sm space-y-2" aria-hidden="true">
          <Skeleton className="h-3 w-3/4" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      )}
      <p className="text-sm text-muted-foreground">{text}</p>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="label-caps">{title}</h3>
      {children}
    </section>
  )
}

function Bullets({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>
  return (
    <ul className="space-y-1.5 text-sm">
      {items.map((item, index) => (
        <li key={index} className="flex gap-2">
          <span aria-hidden="true" className="mt-2 size-1 shrink-0 rounded-full bg-muted-foreground" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  )
}

/** Literal test values: monospace, whitespace preserved, wrapping instead of overflowing. */
function Literal({ children }: { children: string }) {
  return (
    <code className="block rounded bg-muted px-2 py-1 font-mono text-xs leading-5 break-all whitespace-pre-wrap">
      {children}
    </code>
  )
}

function TestCaseCard({ testCase, index }: { testCase: GeneratedTestCase; index: number }) {
  return (
    <li className="space-y-2 px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
        <span className="font-mono text-[13px] font-medium">{testCase.name}</span>
        <Badge variant="outline" className="rounded-md text-muted-foreground">
          {CATEGORY_LABELS[testCase.category] ?? testCase.category}
        </Badge>
      </div>
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
    </li>
  )
}

function PlanSummary({ plan }: { plan: GeneratedTests }) {
  return (
    <dl className="grid gap-3 rounded-lg border bg-card p-3 text-sm sm:grid-cols-2">
      <div>
        <dt className="label-caps mb-1">Interface</dt>
        <dd className="font-mono text-[13px] wrap-break-word">{plan.interface}</dd>
      </div>
      <div>
        <dt className="label-caps mb-1">How results are compared</dt>
        <dd>{plan.comparison}</dd>
      </div>
    </dl>
  )
}

export function ArtifactPanel({ run }: { run: Run }) {
  const files = FILE_NAMES[run.language]
  const code = run.generated_code
  const plan = run.generated_tests
  const requirements = run.requirements
  const languageBadge = (
    <Badge variant="outline" className="h-5 rounded-md text-muted-foreground">
      {LANGUAGE_LABELS[run.language]}
    </Badge>
  )

  const coverage = plan
    ? Object.entries(
        plan.cases.reduce<Record<string, number>>((counts, testCase) => {
          counts[testCase.category] = (counts[testCase.category] ?? 0) + 1
          return counts
        }, {}),
      )
    : []

  return (
    <Tabs defaultValue="solution" className="gap-3">
      <TabsList className="w-full justify-start sm:w-fit" aria-label="Generated artifacts">
        <TabsTrigger value="solution">Solution</TabsTrigger>
        <TabsTrigger value="tests">Tests</TabsTrigger>
        <TabsTrigger value="plan">Test plan</TabsTrigger>
        <TabsTrigger value="requirements">Requirements</TabsTrigger>
      </TabsList>

      {run.revision_count > 0 && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <RefreshCw className="size-3.5" aria-hidden="true" />
          Repaired {run.revision_count}× during verification. Showing the latest version; earlier
          versions are not kept.
        </p>
      )}

      <TabsContent value="solution" className="space-y-3">
        {code ? (
          <>
            <CodeViewer code={code.solution_code} label={files.solution} meta={languageBadge} />
            {code.explanation && (
              <Section title="Approach">
                <p className="text-sm leading-relaxed text-muted-foreground">{code.explanation}</p>
              </Section>
            )}
          </>
        ) : (
          <Pending run={run} stage="generating_code" what="solution" />
        )}
      </TabsContent>

      <TabsContent value="tests" className="space-y-4">
        {plan ? (
          <>
            <PlanSummary plan={plan} />
            <Section title={`Test cases (${plan.cases.length})`}>
              <ul className="divide-y rounded-lg border">
                {plan.cases.map((testCase, index) => (
                  <TestCaseCard key={testCase.name} testCase={testCase} index={index} />
                ))}
              </ul>
            </Section>
          </>
        ) : (
          <Pending run={run} stage="generating_tests" what="test cases" />
        )}
        {code ? (
          <Section title="Executable test program">
            <CodeViewer code={code.test_code} label={files.tests} meta={languageBadge} />
          </Section>
        ) : (
          plan && <Pending run={run} stage="generating_code" what="test program" />
        )}
      </TabsContent>

      <TabsContent value="plan" className="space-y-4">
        {plan ? (
          <>
            <PlanSummary plan={plan} />
            <Section title="Coverage">
              <ul className="flex flex-wrap gap-2">
                {coverage.map(([category, count]) => (
                  <li key={category}>
                    <Badge variant="outline" className="rounded-md">
                      {CATEGORY_LABELS[category as CaseCategory] ?? category}
                      <span className="font-mono text-muted-foreground">{count}</span>
                    </Badge>
                  </li>
                ))}
              </ul>
            </Section>
            <Section title="Cases">
              <ol className="divide-y rounded-lg border text-sm">
                {plan.cases.map((testCase) => (
                  <li key={testCase.name} className="grid gap-1 px-3 py-2 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)] sm:gap-3">
                    <span className="font-mono text-[13px] break-all">{testCase.name}</span>
                    <span className="text-muted-foreground">{testCase.description}</span>
                  </li>
                ))}
              </ol>
            </Section>
          </>
        ) : (
          <Pending run={run} stage="generating_tests" what="test plan" />
        )}
      </TabsContent>

      <TabsContent value="requirements" className="space-y-5">
        {requirements ? (
          <>
            <Section title="Problem">
              <p className="text-sm leading-relaxed">{requirements.problem_summary}</p>
            </Section>
            <div className="grid gap-4 sm:grid-cols-2">
              <Section title="Expected input">
                <p className="text-sm">{requirements.expected_input}</p>
              </Section>
              <Section title="Expected output">
                <p className="text-sm">{requirements.expected_output}</p>
              </Section>
            </div>
            <Section title="Functional requirements">
              <Bullets items={requirements.functional_requirements} empty="None stated." />
            </Section>
            <div className="grid gap-4 sm:grid-cols-2">
              <Section title="Edge cases">
                <Bullets items={requirements.edge_cases} empty="None identified." />
              </Section>
              <Section title="Constraints">
                <Bullets items={requirements.constraints} empty="None stated." />
              </Section>
            </div>
            <Section title={`${LANGUAGE_LABELS[run.language]} requirements`}>
              <Bullets items={requirements.relevant_language_requirements} empty="None stated." />
            </Section>
          </>
        ) : (
          <Pending run={run} stage="analyzing" what="requirements analysis" />
        )}
      </TabsContent>
    </Tabs>
  )
}
