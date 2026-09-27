import { Link } from "react-router"

import { cn, TOUCH_TARGET } from "@/lib/utils"

export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={className}>
      <rect width="32" height="32" rx="7" className="fill-muted" />
      <path d="M16 6 25 26h-4.2L16 15.2 11.2 26H7Z" className="fill-brand" />
    </svg>
  )
}

export function Brand() {
  return (
    <Link
      to="/"
      className={cn(TOUCH_TARGET, "flex shrink-0 items-center gap-2 rounded-md font-semibold tracking-tight")}
      aria-label="AstraAi home"
    >
      <BrandMark className="size-6" />
      <span>AstraAi</span>
    </Link>
  )
}
