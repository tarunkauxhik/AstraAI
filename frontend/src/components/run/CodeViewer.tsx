import { useEffect, useState } from "react"
import { Check, Copy } from "lucide-react"

import { Button } from "@/components/ui/button"

interface CodeViewerProps {
  code: string
  /** Accessible name and visible caption, e.g. "solution.py". */
  label: string
}

/** Read-only code with line numbers. Always plain text: nothing is rendered as HTML. */
export function CodeViewer({ code, label }: CodeViewerProps) {
  const [copied, setCopied] = useState(false)
  const lines = code.replace(/\n$/, "").split("\n")

  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(timer)
  }, [copied])

  async function copy() {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
    } catch {
      // Clipboard unavailable (insecure context or denied): the code stays selectable.
    }
  }

  return (
    <figure className="overflow-hidden rounded-lg border bg-[oklch(0.135_0.004_250)]">
      <figcaption className="flex items-center justify-between border-b px-3 py-1.5">
        <span className="font-mono text-xs text-muted-foreground">{label}</span>
        <Button
          variant="ghost"
          size="xs"
          onClick={copy}
          aria-label={copied ? `Copied ${label}` : `Copy ${label}`}
        >
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {copied ? "Copied" : "Copy"}
        </Button>
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
