import { useEffect, useState } from "react"

import { serverNow } from "@/lib/server-clock"

/** Server-clock time, refreshed every second. Only the component using it re-renders. */
export function useServerNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => serverNow())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(serverNow()), intervalMs)
    return () => window.clearInterval(timer)
  }, [intervalMs])
  return now
}
