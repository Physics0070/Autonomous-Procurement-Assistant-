import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import type { ProcessingStatus, ProcurementStatus, MatchConfidenceLevel } from "@/types"

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors whitespace-nowrap",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary/10 text-primary",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "text-foreground",
        success: "border-transparent bg-success/12 text-success",
        warning: "border-transparent bg-warning/15 text-warning",
        destructive: "border-transparent bg-destructive/12 text-destructive",
        muted: "border-transparent bg-muted text-muted-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

// --- Domain-specific badges ------------------------------------------------

const PROCESSING_LABELS: Record<ProcessingStatus, string> = {
  UPLOADED: "Uploaded",
  QUEUED: "Queued",
  EXTRACTING: "Extracting",
  AI_EXTRACTING: "Reading data",
  NORMALIZING: "Normalizing",
  COMPLETED: "Completed",
  REQUIRES_REVIEW: "Needs review",
  FAILED: "Failed",
}

const PROCESSING_VARIANTS: Record<ProcessingStatus, BadgeProps["variant"]> = {
  UPLOADED: "muted",
  QUEUED: "muted",
  EXTRACTING: "default",
  AI_EXTRACTING: "default",
  NORMALIZING: "default",
  COMPLETED: "success",
  REQUIRES_REVIEW: "warning",
  FAILED: "destructive",
}

export const IN_PROGRESS_STATUSES: ProcessingStatus[] = [
  "UPLOADED",
  "QUEUED",
  "EXTRACTING",
  "AI_EXTRACTING",
  "NORMALIZING",
]

export function StatusBadge({ status, className }: { status: ProcessingStatus; className?: string }) {
  const active = IN_PROGRESS_STATUSES.includes(status)
  return (
    <Badge variant={PROCESSING_VARIANTS[status] ?? "muted"} className={className}>
      {active && (
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      )}
      {PROCESSING_LABELS[status] ?? status}
    </Badge>
  )
}

const REQUEST_VARIANTS: Record<ProcurementStatus, BadgeProps["variant"]> = {
  draft: "muted",
  open: "default",
  comparing: "warning",
  awarded: "success",
  closed: "secondary",
  cancelled: "destructive",
}

export function RequestStatusBadge({ status }: { status: ProcurementStatus }) {
  return (
    <Badge variant={REQUEST_VARIANTS[status] ?? "muted"} className="capitalize">
      {status}
    </Badge>
  )
}

const CONFIDENCE_VARIANTS: Record<MatchConfidenceLevel, BadgeProps["variant"]> = {
  high: "success",
  medium: "warning",
  low: "destructive",
  none: "muted",
}

export function ConfidenceBadge({
  level,
  score,
}: {
  level: MatchConfidenceLevel
  score?: number
}) {
  return (
    <Badge variant={CONFIDENCE_VARIANTS[level] ?? "muted"} className="capitalize">
      {level}
      {score !== undefined && score > 0 ? ` · ${(score * 100).toFixed(0)}%` : ""}
    </Badge>
  )
}

export { Badge, badgeVariants }
