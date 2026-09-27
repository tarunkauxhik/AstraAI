import type { ReactNode } from "react"
import { ChevronRight } from "lucide-react"


interface DisclosureProps {
  summary: ReactNode
  children: ReactNode
  id?: string
  /** Controlled open state; omit for a native, self-managed disclosure. */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  className?: string
}

/** A native <details> with one consistent affordance for secondary information. */
export function Disclosure({ summary, children, id, open, onOpenChange, className }: DisclosureProps) {
  return (
    <details
      id={id}
      open={open}
      onToggle={(event) => onOpenChange?.(event.currentTarget.open)}
      className={className}
    >
      <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-sm py-1 text-sm pointer-coarse:min-h-11 text-muted-foreground select-none hover:text-foreground [&::-webkit-details-marker]:hidden">
        <ChevronRight
          className="disclosure-chevron size-4 shrink-0"
          aria-hidden="true"
        />
        {summary}
      </summary>
      <div className="pt-2">{children}</div>
    </details>
  )
}
