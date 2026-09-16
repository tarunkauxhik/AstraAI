import { useEffect, useState } from "react"
import { Check, Copy } from "lucide-react"

import { Button } from "@/components/ui/button"

/** Copies text and confirms briefly. Silently does nothing where the clipboard is blocked. */
export function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(timer)
  }, [copied])

  return (
    <Button
      variant="ghost"
      size="xs"
      onClick={() =>
        navigator.clipboard?.writeText(text).then(
          () => setCopied(true),
          () => undefined,
        )
      }
      aria-label={copied ? `Copied ${label}` : `Copy ${label}`}
    >
      {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
      {copied ? "Copied" : "Copy"}
    </Button>
  )
}
