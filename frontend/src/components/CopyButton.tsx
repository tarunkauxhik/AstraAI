import { useEffect, useState, type ComponentProps } from "react"
import { Check, Copy } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn, TOUCH_TARGET } from "@/lib/utils"

interface CopyButtonProps {
  text: string
  /** What is copied, e.g. "solution.py"; part of the accessible name. */
  label: string
  /** Visible text before copying. */
  children?: string
  variant?: ComponentProps<typeof Button>["variant"]
  size?: ComponentProps<typeof Button>["size"]
  className?: string
}

/** Copies text and confirms briefly. Silently does nothing where the clipboard is blocked. */
export function CopyButton({
  text,
  label,
  children = "Copy",
  variant = "ghost",
  size = "xs",
  className,
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(timer)
  }, [copied])

  return (
    <Button
      variant={variant}
      size={size}
      className={cn(size === "xs" && TOUCH_TARGET, className)}
      onClick={() =>
        navigator.clipboard?.writeText(text).then(
          () => setCopied(true),
          () => undefined,
        )
      }
      aria-label={copied ? `Copied ${label}` : `Copy ${label}`}
    >
      {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
      {copied ? "Copied" : children}
    </Button>
  )
}
