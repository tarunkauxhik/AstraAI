import { cn } from "@/lib/utils"

/** A small pulsing dot: "work is happening". Never a measure of progress. */
export function ActivityDot({ className }: { className?: string }) {
  return (
    <span aria-hidden="true" className={cn("relative flex size-2 shrink-0", className)}>
      <span className="absolute inline-flex size-full animate-ping rounded-full bg-info/60 motion-reduce:animate-none" />
      <span className="relative inline-flex size-2 rounded-full bg-info" />
    </span>
  )
}
