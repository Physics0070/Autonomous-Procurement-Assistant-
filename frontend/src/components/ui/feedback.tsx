import * as React from "react"
import { AlertCircle, AlertTriangle, Info, Loader2, CheckCircle2 } from "lucide-react"
import { cn } from "@/lib/utils"

// --- Loading ---------------------------------------------------------------

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-4 w-4 animate-spin", className)} />
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
      <Spinner />
      {label}
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn("relative overflow-hidden rounded-md bg-muted", className)}>
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-black/5 to-transparent" />
    </div>
  )
}

// --- Alerts ----------------------------------------------------------------

const ALERT_STYLES = {
  info: { wrap: "border-primary/25 bg-primary/5 text-foreground", icon: "text-primary", Icon: Info },
  warning: { wrap: "border-warning/30 bg-warning/8 text-foreground", icon: "text-warning", Icon: AlertTriangle },
  error: {
    wrap: "border-destructive/30 bg-destructive/8 text-foreground",
    icon: "text-destructive",
    Icon: AlertCircle,
  },
  success: { wrap: "border-success/30 bg-success/8 text-foreground", icon: "text-success", Icon: CheckCircle2 },
} as const

export function Alert({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: keyof typeof ALERT_STYLES
  title?: React.ReactNode
  children?: React.ReactNode
  className?: string
}) {
  const { wrap, icon, Icon } = ALERT_STYLES[tone]
  return (
    <div className={cn("flex gap-3 rounded-lg border p-3.5 text-sm", wrap, className)}>
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", icon)} />
      <div className="min-w-0 flex-1 space-y-1">
        {title && <p className="font-medium leading-snug">{title}</p>}
        {children && <div className="text-muted-foreground [&_p]:leading-relaxed">{children}</div>}
      </div>
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "Something went wrong."
  return (
    <Alert tone="error" title="Could not load this">
      <p>{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 text-sm font-medium text-primary underline-offset-4 hover:underline"
        >
          Try again
        </button>
      )}
    </Alert>
  )
}

// --- Empty state -----------------------------------------------------------

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon?: React.ComponentType<{ className?: string }>
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed px-6 py-14 text-center">
      {Icon && (
        <div className="rounded-full bg-muted p-3">
          <Icon className="h-5 w-5 text-muted-foreground" />
        </div>
      )}
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  )
}

// --- Score bar -------------------------------------------------------------

export function ScoreBar({
  value,
  tone = "primary",
  className,
}: {
  value: number
  tone?: "primary" | "success" | "warning" | "destructive"
  className?: string
}) {
  const pct = Math.max(0, Math.min(1, value)) * 100
  const bg = {
    primary: "bg-primary",
    success: "bg-success",
    warning: "bg-warning",
    destructive: "bg-destructive",
  }[tone]
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}>
      <div className={cn("h-full rounded-full transition-all", bg)} style={{ width: `${pct}%` }} />
    </div>
  )
}

/** Renders a value or an explicit "not stated" marker - never a silent blank. */
export function ValueOrMissing({
  value,
  missingLabel = "Not stated",
}: {
  value: React.ReactNode
  missingLabel?: string
}) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-xs italic text-muted-foreground">{missingLabel}</span>
  }
  return <>{value}</>
}
