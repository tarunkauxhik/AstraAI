import { ChevronRight } from "lucide-react"

import { CopyButton } from "@/components/CopyButton"
import { cn } from "@/lib/utils"

interface OutputBlockProps {
  label: string
  text: string
  defaultOpen: boolean
  tone?: "default" | "error"
}

/** Program output: collapsible, copyable, whitespace-preserving, height-bounded. */
export function OutputBlock({ label, text, defaultOpen, tone = "default" }: OutputBlockProps) {
  const lines = text.replace(/\n$/, "").split("\n").length
  return (
    <details open={defaultOpen} className="rounded-md border bg-[oklch(0.135_0.004_250)]">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-1.5 select-none [&::-webkit-details-marker]:hidden">
        <ChevronRight
          className="disclosure-chevron size-3.5 text-muted-foreground"
          aria-hidden="true"
        />
        <span className={cn("font-mono text-xs", tone === "error" ? "text-destructive" : "text-foreground")}>
          {label}
        </span>
        <span className="text-xs text-muted-foreground">
          {lines} {lines === 1 ? "line" : "lines"}
        </span>
      </summary>
      <div className="relative border-t">
        <div className="absolute top-1 right-1">
          <CopyButton text={text} label={label} />
        </div>
        <pre
          tabIndex={0}
          aria-label={label}
          className="max-h-80 overflow-auto px-3 py-2 pr-20 font-mono text-xs leading-5 whitespace-pre"
        >
          {text}
        </pre>
      </div>
    </details>
  )
}
