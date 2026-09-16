import type { ReactNode } from "react"

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"

interface PanelProps {
  title: string
  action?: ReactNode
  className?: string
  children: ReactNode
}

/** The shared frame for verification panels: a compact small-caps title and content. */
export function Panel({ title, action, className, children }: PanelProps) {
  return (
    <Card size="sm" className={cn("rounded-lg", className)}>
      <CardHeader>
        <CardTitle>
          <h2 className="label-caps">{title}</h2>
        </CardTitle>
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      <CardContent className="space-y-3">{children}</CardContent>
    </Card>
  )
}
