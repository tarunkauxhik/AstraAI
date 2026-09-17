import { useSyncExternalStore } from "react"

/** The desktop layout: main content beside a sticky decision panel. */
export const DESKTOP_QUERY = "(min-width: 1024px)"

/**
 * Whether a media query matches, kept in sync with the viewport. Used where an element must
 * exist in exactly one place per layout (approval actions, the countdown), rather than being
 * rendered twice and hidden with CSS. Without matchMedia it assumes `fallback`.
 */
export function useMediaQuery(query: string, fallback = true): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => undefined
      const media = window.matchMedia(query)
      media.addEventListener("change", onChange)
      return () => media.removeEventListener("change", onChange)
    },
    () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : fallback),
    () => fallback,
  )
}
