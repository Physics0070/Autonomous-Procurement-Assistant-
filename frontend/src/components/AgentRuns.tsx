import * as React from "react"
import { Bot, CheckCircle2, CircleAlert, PauseCircle, Play, Workflow } from "lucide-react"
import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, Spinner } from "@/components/ui/feedback"
import { useAgentRuns, useResumeRun, type AgentRun } from "@/hooks/automation"
import { cn, formatDateTime } from "@/lib/utils"

const STATUS_TONE: Record<string, "warning" | "success" | "destructive" | "muted"> = {
  awaiting_approval: "warning",
  completed: "success",
  cancelled: "destructive",
  step_budget_reached: "destructive",
  no_quotations: "muted",
}

/** What the run is waiting for, and the button that lets it carry on. */
function Pending({ run }: { run: AgentRun }) {
  const resume = useResumeRun()
  const pending = run.output?.pending
  if (run.status !== "awaiting_approval" || !pending) return null
  const target = pending.purchase_order_id ? "/purchase-orders" : "/communications"

  return (
    <Alert tone="warning" title={`Paused — waiting for you to approve ${pending.waiting_for}`}>
      <p>
        Approve it on the <Link to={target} className="text-primary hover:underline">
          {pending.purchase_order_id ? "Purchase orders" : "Communications"}
        </Link> page, then let the agents carry on.
      </p>
      {resume.error && <p className="text-destructive">{resume.error.message}</p>}
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

function Decisions({ run }: { run: AgentRun }) {
  const decisions = run.output?.decisions ?? []
  if (!decisions.length) return null
  return (
    <details className="rounded-md border bg-muted/40 px-3 py-2 text-xs">
      <summary className="cursor-pointer select-none">
        <Bot className="mr-1 inline h-3 w-3" />Why the supervisor chose each agent
      </summary>
      <ol className="mt-2 space-y-1">
        {decisions.map((d, i) => (
          <li key={i} className="flex gap-2">
            <span className="font-medium">{d.action.replace(/_/g, " ")}</span>
            <span className="text-muted-foreground">{d.reason}</span>
            <Badge variant={d.by === "llm" ? "default" : "muted"} className="ml-auto shrink-0">{d.by}</Badge>
          </li>
        ))}
      </ol>
    </details>
  )
}

/** Step-by-step timeline of the agent runs for one request or quotation. */
export function AgentRuns({ filters, title = "Agent runs" }: { filters: Record<string, string | undefined>; title?: string }) {
  const { data } = useAgentRuns(filters)
  if (!data?.length) return null
  return (
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Workflow className="h-4 w-4" />{title}</CardTitle></CardHeader>
      <CardContent className="space-y-5">
        {data.slice(0, 3).map((run) => (
          <div key={run.id} className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{run.graph.replace(/_/g, " ")}</span>
              <Badge variant={STATUS_TONE[run.status] ?? "muted"}>{run.status.replace(/_/g, " ")}</Badge>
              {run.input?.started_by === "monitor_agent" && <Badge variant="secondary">started automatically</Badge>}
              {formatDateTime(run.created_at)}
            </div>
            <ol className="relative space-y-2 border-l pl-4">
              {run.steps.map((step, i) => (
                <li key={i} className={cn("text-sm", step.agent === "Supervisor Agent" && "text-muted-foreground")}>
                  {step.error
                    ? <CircleAlert className="absolute -left-2 h-4 w-4 bg-card text-destructive" />
                    : step.agent === "Supervisor Agent"
                      ? <Bot className="absolute -left-2 h-4 w-4 bg-card text-primary" />
                      : <CheckCircle2 className="absolute -left-2 h-4 w-4 bg-card text-success" />}
                  <span className="font-medium">{step.agent}</span>
                  <span className="text-muted-foreground"> — {step.error ?? step.summary}</span>
                </li>
              ))}
              {run.status === "awaiting_approval" && (
                <li className="text-sm">
                  <PauseCircle className="absolute -left-2 h-4 w-4 bg-card text-warning" />
                  <span className="font-medium">Paused for approval</span>
                </li>
              )}
            </ol>
            <Decisions run={run} />
            <Pending run={run} />
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
