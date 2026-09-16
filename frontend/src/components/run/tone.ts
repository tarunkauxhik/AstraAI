import { AlertTriangle, CheckCircle2, CircleSlash, Info, XCircle, type LucideIcon } from "lucide-react"

import type { Tone } from "@/lib/labels"

/** Tinted badge styling per tone. Always paired with a text label and usually an icon. */
export const TONE_BADGE: Record<Tone, string> = {
  neutral: "border-border bg-muted text-muted-foreground",
  info: "border-info/30 bg-info/10 text-info",
  success: "border-success/30 bg-success/10 text-success",
  warning: "border-warning/30 bg-warning/10 text-warning",
  danger: "border-destructive/30 bg-destructive/10 text-destructive",
}

export const TONE_TEXT: Record<Tone, string> = {
  neutral: "text-muted-foreground",
  info: "text-info",
  success: "text-success",
  warning: "text-warning",
  danger: "text-destructive",
}

/** Thin left accent for panels that carry an outcome. */
export const TONE_ACCENT: Record<Tone, string> = {
  neutral: "border-l-muted-foreground/40",
  info: "border-l-info",
  success: "border-l-success",
  warning: "border-l-warning",
  danger: "border-l-destructive",
}

/** Icon for an outcome of a given tone, so state never relies on color alone. */
export const TONE_ICON: Record<Tone, LucideIcon> = {
  neutral: CircleSlash,
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: XCircle,
}
