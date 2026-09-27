import type { ReactNode } from "react"

import { Skeleton } from "@/components/ui/skeleton"

/** A section title with optional quiet context on the right, e.g. "8 passed". */
export function SectionHeading({ id, children, aside }: { id: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <h2 id={id} tabIndex={-1} className="rounded-sm text-sm font-semibold">
        {children}
      </h2>
      {aside && <p className="text-sm text-muted-foreground">{aside}</p>}
    </div>
  )
}

/** A result that is being produced right now; nothing is shown for results not yet started. */
export function SectionSkeleton({ id, title, note }: { id: string; title: string; note: string }) {
  return (
    <section id={id} aria-labelledby={`${id}-heading`} aria-busy="true" className="space-y-4">
      <SectionHeading id={`${id}-heading`} aside={note}>
        {title}
      </SectionHeading>
      <div className="max-w-lg space-y-2.5" aria-hidden="true">
        <Skeleton className="h-3 w-3/4" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-2/3" />
      </div>
    </section>
  )
}
