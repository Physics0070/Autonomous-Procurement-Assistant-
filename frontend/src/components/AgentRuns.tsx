import { CheckCircle2, CircleAlert, Workflow } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAgentRuns } from "@/hooks/automation"
import { formatDateTime } from "@/lib/utils"

/** Step-by-step timeline of the agent graph runs for one request or quotation. */
export function AgentRuns({ filters, title = "Agent runs" }: { filters: Record<string, string | undefined>; title?: string }) {
  const { data } = useAgentRuns(filters)
  if (!data?.length) return null
  return (
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Workflow className="h-4 w-4" />{title}</CardTitle></CardHeader>
      <CardContent className="space-y-5">
        {data.slice(0, 3).map((run) => (
          <div key={run.id} className="space-y-2">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{run.graph.replace(/_/g, " ")}</span>
              <Badge variant={run.status === "awaiting_approval" ? "warning" : run.status === "completed" ? "success" : "muted"}>
                {run.status.replace(/_/g, " ")}
              </Badge>
              {formatDateTime(run.created_at)}
            </div>
            <ol className="relative space-y-2 border-l pl-4">
              {run.steps.map((step, i) => (
                <li key={i} className="text-sm">
                  {step.error
                    ? <CircleAlert className="absolute -left-2 h-4 w-4 bg-card text-destructive" />
                    : <CheckCircle2 className="absolute -left-2 h-4 w-4 bg-card text-success" />}
                  <span className="font-medium">{step.agent}</span>
                  <span className="text-muted-foreground"> — {step.error ?? step.summary}</span>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
