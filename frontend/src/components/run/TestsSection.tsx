import { Check, X } from "lucide-react"

import type { GeneratedTestCase, Requirements, Run } from "@/api/types"
import { Disclosure } from "@/components/Disclosure"
import { CodeViewer } from "@/components/run/CodeViewer"
import { InlineText } from "@/components/run/InlineText"
import { SectionHeading, SectionSkeleton } from "@/components/run/Section"
import { FILE_NAMES, LANGUAGE_LABELS } from "@/lib/labels"
import { testReport, type CaseEvidence } from "@/lib/run-view"

/** A literal from the model, shown exactly; long ones wrap and stop at a few lines. */
function Value({ children }: { children: string }) {
  // An empty value is shown as such, so a row never looks like something is missing.
  if (children === "") return <span className="font-sans text-muted-foreground/70 italic">(empty)</span>
  return <span className="line-clamp-4 break-all whitespace-pre-wrap">{children}</span>
}

function TestRow({ testCase, evidence }: { testCase: GeneratedTestCase; evidence?: CaseEvidence }) {
  const status = evidence?.status ?? null
  return (
    <li className="grid grid-cols-[1rem_minmax(0,1fr)] gap-x-2.5 py-2.5">
      <span className="flex h-5 items-center" aria-hidden="true">
        {status === "passed" && <Check className="size-3.5 text-muted-foreground" />}
        {status === "failed" && <X className="size-3.5 text-destructive" />}
      </span>
      <div className="min-w-0 space-y-1">
        <p className="text-sm leading-5">
          <span className="font-mono text-[13px]">{testCase.name}</span>
          {status && <span className="sr-only"> {status}</span>}
          {testCase.description && (
            <span className="text-muted-foreground">
              {" — "}
              <InlineText text={testCase.description} />
            </span>
          )}
        </p>
        <p className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 font-mono text-xs leading-5 text-muted-foreground sm:flex sm:flex-wrap sm:items-baseline">
          <span className="sm:hidden">in</span>
          <Value>{testCase.input || `generated: ${testCase.input_generator}`}</Value>
          <span className="sm:hidden">out</span>
          <span className="flex min-w-0 gap-2">
            <span className="max-sm:hidden" aria-hidden="true">
              →
            </span>
            <span className="sr-only">expected</span>
            <Value>{testCase.expected_output}</Value>
          </span>
        </p>
        {status === "failed" && evidence?.actual !== null && evidence?.actual !== undefined && (
          <p className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 font-mono text-xs leading-5 text-destructive">
            <span>got</span>
            <Value>{evidence.actual}</Value>
          </p>
        )}
      </div>
    </li>
  )
}

function Bullets({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <p className="text-muted-foreground">{empty}</p>
  return (
    <ul className="list-disc space-y-1 pl-5">
      {items.map((item, index) => (
        <li key={index}>
          <InlineText text={item} />
        </li>
      ))}
    </ul>
  )
}

/** How AstraAi read the task: the interpretation every test is built on. */
function Interpretation({ requirements, language }: { requirements: Requirements; language: string }) {
  const sections: [string, string[], string][] = [
    ["Must do", requirements.functional_requirements, "None stated."],
    ["Edge cases", requirements.edge_cases, "None identified."],
    ["Constraints", requirements.constraints, "None stated."],
    [`${language} specifics`, requirements.relevant_language_requirements, "None stated."],
  ]
  return (
    <div className="space-y-4 text-sm">
      <p>
        <InlineText text={requirements.problem_summary} />
      </p>
      <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[7rem_minmax(0,1fr)]">
        <dt className="text-muted-foreground">Input</dt>
        <dd>
          <InlineText text={requirements.expected_input} />
        </dd>
        <dt className="text-muted-foreground">Output</dt>
        <dd>
          <InlineText text={requirements.expected_output} />
        </dd>
      </dl>
      {sections.map(([title, items, empty]) => (
        <div key={title} className="space-y-1">
          <h3 className="font-medium">{title}</h3>
          <Bullets items={items} empty={empty} />
        </div>
      ))}
    </div>
  )
}

export function TestsSection({ run }: { run: Run }) {
  const plan = run.generated_tests
  if (!plan) {
    return run.stage === "generating_tests" ? (
      <SectionSkeleton id="tests" title="Tests" note="Writing…" />
    ) : null
  }

  const report = testReport(run)
  const files = FILE_NAMES[run.language]
  return (
    <section id="tests" aria-labelledby="tests-heading" className="scroll-mt-6 space-y-3">
      <SectionHeading id="tests-heading" aside={report.summary}>
        Tests
      </SectionHeading>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
        <dt>Interface</dt>
        <dd className="font-mono break-words text-foreground/80">{plan.interface}</dd>
        <dt>Compared by</dt>
        <dd className="text-foreground/80">
          <InlineText text={plan.comparison} />
        </dd>
      </dl>
      <ul className="divide-y" aria-label={`Test cases, ${report.summary}`}>
        {plan.cases.map((testCase) => (
          <TestRow key={testCase.name} testCase={testCase} evidence={report.cases.get(testCase.name)} />
        ))}
      </ul>
      {report.unmatched.length > 0 && (
        <div className="space-y-1 text-xs">
          <p className="text-muted-foreground">Other failures the test program reported:</p>
          {report.unmatched.map((failure, index) => (
            <p key={index} className="font-mono break-all text-destructive">
              {failure.line}
            </p>
          ))}
        </div>
      )}
      <div className="pt-1">
        {run.requirements && (
          <Disclosure summary="How AstraAi read the task">
            <Interpretation requirements={run.requirements} language={LANGUAGE_LABELS[run.language]} />
          </Disclosure>
        )}
        {run.generated_code && (
          <Disclosure summary={`Test program · ${files.tests}`}>
            <CodeViewer code={run.generated_code.test_code} label={files.tests} />
          </Disclosure>
        )}
      </div>
    </section>
  )
}
