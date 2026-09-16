import { RefreshCw } from "lucide-react"

import type { Run, RunStage } from "@/api/types"
import { CodeViewer } from "@/components/run/CodeViewer"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

const FILE_NAMES = {
  python: { solution: "solution.py", tests: "test_solution.py" },
  cpp: { solution: "solution.cpp", tests: "test_solution.cpp" },
} as const

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

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <section>
      <h3 className="label-caps mb-2">{title}</h3>
      <ul className="list-disc space-y-1 pl-5 text-sm">
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </section>
  )
}

export function ArtifactPanel({ run }: { run: Run }) {
  const files = FILE_NAMES[run.language]
  const code = run.generated_code
  const plan = run.generated_tests
  const requirements = run.requirements

  return (
    <Tabs defaultValue="solution" className="gap-3">
      <TabsList className="w-full justify-start sm:w-fit">
        <TabsTrigger value="solution">Solution</TabsTrigger>
        <TabsTrigger value="tests">Tests</TabsTrigger>
        <TabsTrigger value="plan">Test plan</TabsTrigger>
        <TabsTrigger value="requirements">Requirements</TabsTrigger>
      </TabsList>

      {run.revision_count > 0 && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <RefreshCw className="size-3.5" aria-hidden="true" />
          Revised {run.revision_count}× during verification. Showing the latest version; earlier
          versions are not kept.
        </p>
      )}

      <TabsContent value="solution" className="space-y-3">
        {code ? (
          <>
            <CodeViewer code={code.solution_code} label={files.solution} />
            {code.explanation && (
              <p className="text-sm text-muted-foreground">
                <span className="label-caps mr-2">Note</span>
                {code.explanation}
              </p>
            )}
          </>
        ) : (
          <Pending run={run} stage="generating_code" what="solution" />
        )}
      </TabsContent>

      <TabsContent value="tests">
        {code ? (
          <CodeViewer code={code.test_code} label={files.tests} />
        ) : (
          <Pending run={run} stage="generating_code" what="test code" />
        )}
      </TabsContent>

      <TabsContent value="plan" className="space-y-4">
        {plan ? (
          <>
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="label-caps mb-1">Interface</dt>
                <dd className="font-mono text-[13px]">{plan.interface}</dd>
              </div>
              <div>
                <dt className="label-caps mb-1">Comparison</dt>
                <dd>{plan.comparison}</dd>
              </div>
            </dl>
            <ul className="divide-y rounded-lg border">
              {plan.cases.map((testCase) => (
                <li key={testCase.name} className="space-y-1.5 px-3 py-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[13px] font-medium">{testCase.name}</span>
                    <Badge variant="outline" className="rounded-md text-muted-foreground">
                      {testCase.category.replaceAll("_", " ")}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">{testCase.description}</p>
                  <dl className="grid gap-x-3 gap-y-0.5 font-mono text-xs sm:grid-cols-[auto_1fr]">
                    {testCase.input && (
                      <>
                        <dt className="text-muted-foreground">input</dt>
                        <dd className="break-all">{testCase.input}</dd>
                      </>
                    )}
                    {testCase.input_generator && (
                      <>
                        <dt className="text-muted-foreground">generator</dt>
                        <dd className="break-all">{testCase.input_generator}</dd>
                      </>
                    )}
                    <dt className="text-muted-foreground">expected</dt>
                    <dd className="break-all">{testCase.expected_output}</dd>
                  </dl>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <Pending run={run} stage="generating_tests" what="test plan" />
        )}
      </TabsContent>

      <TabsContent value="requirements" className="space-y-4">
        {requirements ? (
          <>
            <p className="text-sm">{requirements.problem_summary}</p>
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="label-caps mb-1">Input</dt>
                <dd>{requirements.expected_input}</dd>
              </div>
              <div>
                <dt className="label-caps mb-1">Output</dt>
                <dd>{requirements.expected_output}</dd>
              </div>
            </dl>
            <List title="Functional requirements" items={requirements.functional_requirements} />
            <List title="Edge cases" items={requirements.edge_cases} />
            <List title="Constraints" items={requirements.constraints} />
            <List title="Language" items={requirements.relevant_language_requirements} />
          </>
        ) : (
          <Pending run={run} stage="analyzing" what="requirements analysis" />
        )}
      </TabsContent>
    </Tabs>
  )
}
