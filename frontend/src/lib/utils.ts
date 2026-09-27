export { cn } from "cn"

/**
 * A 44px-tall hit area for small text controls on touch screens, without changing how they
 * look or where they sit: the area is an invisible, absolutely positioned pseudo-element.
 */
export const TOUCH_TARGET =
  "relative pointer-coarse:after:absolute pointer-coarse:after:-inset-x-1 pointer-coarse:after:-inset-y-3 pointer-coarse:after:content-['']"
