import * as React from "react"
import { CheckCircle2, CircleAlert, PauseCircle, Play } from "lucide-react"
import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, Spinner } from "@/components/ui/feedback"
import { useAgentRuns, useResumeRun, type AgentRun } from "@/hooks/automation"
import { formatDateTime } from "@/lib/utils"

const STATUS_TONE: Record<string, "warning" | "success" | "destructive" | "muted"> = {
  awaiting_approval: "warning",
  completed: "success",
  cancelled: "destructive",
  step_budget_reached: "destructive",
  no_quotations: "muted",
}

const STATUS_LABEL: Record<string, string> = {
  awaiting_approval: "Waiting for you",
  completed: "Done",
  cancelled: "Stopped",
  step_budget_reached: "Stopped",
  no_quotations: "No quotations",
}

/** What is waiting for the user, and the button that lets it carry on. */
function Pending({ run }: { run: AgentRun }) {
  const resume = useResumeRun()
  const pending = run.output?.pending
  if (run.status !== "awaiting_approval" || !pending) return null
  const target = pending.purchase_order_id ? "/purchase-orders" : "/communications"

  return (
    <Alert tone="warning" title="This is waiting for you">
      <p>
        Approve it on the{" "}
        <Link to={target} className="text-primary hover:underline">
          {pending.purchase_order_id ? "Purchase orders" : "Emails"}
        </Link>{" "}
        page, then continue.
      </p>
      {resume.error && <p className="text-destructive">We could not do this right now. Please try again in a minute.</p>}
      <div className="mt-2 flex gap-2">
        <Button size="sm" onClick={() => resume.mutate({ runId: run.id, approved: true })} disabled={resume.isPending}>
          {resume.isPending ? <Spinner /> : <Play className="h-4 w-4" />}Continue
        </Button>
        <Button size="sm" variant="ghost" className="text-destructive"
                onClick={() => resume.mutate({ runId: run.id, approved: false })} disabled={resume.isPending}>
          Stop here
        </Button>
      </div>
    </Alert>
  )
}

function Run({ run }: { run: AgentRun }) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <Badge variant={STATUS_TONE[run.status] ?? "muted"}>{STATUS_LABEL[run.status] ?? "Done"}</Badge>
        <span className="text-xs">{formatDateTime(run.created_at)}</span>
      </div>
      <ul className="space-y-2">
        {run.steps.map((step, i) => (
          <li key={i} className="flex gap-2 text-sm">
            {step.error ? (
              <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
            ) : (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
            )}
            <span>{step.error ? "We could not finish this step." : step.summary}</span>
          </li>
        ))}
        {run.status === "awaiting_approval" && (
          <li className="flex gap-2 text-sm">
            <PauseCircle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <span>Waiting for your approval</span>
          </li>
        )}
      </ul>
      <Pending run={run} />
    </div>
  )
}

/** Short plain-words activity list for one request or quotation. */
export function AgentRuns({ filters, title = "Activity" }: { filters: Record<string, string | undefined>; title?: string }) {
  const { data } = useAgentRuns(filters)
  if (!data?.length) return null
  const [latest, ...older] = data.slice(0, 4)
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">{title}</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <Run run={latest} />
        {older.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer select-none text-muted-foreground">Earlier activity</summary>
            <div className="mt-3 space-y-5">
              {older.map((run) => <Run key={run.id} run={run} />)}
            </div>
          </details>
        )}
      </CardContent>
    </Card>
  )
}
