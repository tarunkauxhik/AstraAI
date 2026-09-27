import type { ReactNode } from "react"

import { CopyButton } from "@/components/CopyButton"

interface CodeViewerProps {
  code: string
  /** Accessible name and visible caption, e.g. "solution.py". */
  label: string
  /** Extra caption content after the label, e.g. the language and verification status. */
  meta?: ReactNode
}

/** Read-only code with line numbers. Always plain text: nothing is rendered as HTML. */
export function CodeViewer({ code, label, meta }: CodeViewerProps) {
  const lines = code.replace(/\n$/, "").split("\n")

  return (
    <figure className="overflow-hidden rounded-lg border bg-[oklch(0.135_0.004_250)]">
      <figcaption className="flex items-center justify-between gap-2 border-b py-1 pr-1.5 pl-3">
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
          <span className="truncate font-mono">{label}</span>
          {meta}
        </span>
        <CopyButton text={code} label={label} />
      </figcaption>
      <div
        className="overflow-x-auto focus-visible:outline-offset-[-2px]"
        tabIndex={0}
        role="region"
        aria-label={label}
      >
        <pre className="grid min-w-max grid-cols-[auto_1fr] py-3 font-mono text-[13px] leading-6">
          {lines.map((line, index) => (
            <code key={index} className="contents">
              <span
                className="select-none pr-4 pl-3 text-right text-muted-foreground/50"
                aria-hidden="true"
              >
                {index + 1}
              </span>
              <span className="pr-4 whitespace-pre">{line || " "}</span>
            </code>
          ))}
        </pre>
      </div>
    </figure>
  )
}
