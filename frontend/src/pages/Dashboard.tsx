import { Link } from "react-router-dom"
import { AlertTriangle, ArrowRight, CheckCircle2, ClipboardList, FileText, Mail, Plus, Upload } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { StatusBadge } from "@/components/ui/badge"
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/feedback"
import { useAuth } from "@/features/auth"
import { useCommunications, usePurchaseOrders } from "@/hooks/automation"
import { useDashboard } from "@/hooks/queries"
import { formatCurrency, relativeTime } from "@/lib/utils"

function greeting(): string {
  const hour = new Date().getHours()
  return hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening"
}

type Task = { id: string; text: string; to: string; action: string; icon: React.ComponentType<{ className?: string }> }

export function DashboardPage() {
  const { user } = useAuth()
  const { data, isLoading, error, refetch } = useDashboard()
  const emails = useCommunications({ status: "draft" })
  const orders = usePurchaseOrders()

  if (isLoading) return <LoadingState label="Loading your home page…" />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  if (!data) return null

  const draftEmails = emails.data?.length ?? 0
  const ordersToApprove = orders.data?.filter((order) => order.status === "draft").length ?? 0
  const toCheck = data.quotations.requires_review
  const unreadable = data.quotations.failed

  // Only things the person can act on, most urgent first. Zero-count items are not shown.
  const tasks: Task[] = [
    toCheck > 0 && { id: "check", icon: AlertTriangle, text: `${toCheck} ${toCheck === 1 ? "quotation needs" : "quotations need"} checking`, to: "/documents?status=REQUIRES_REVIEW", action: "Check" },
    unreadable > 0 && { id: "failed", icon: AlertTriangle, text: `${unreadable} ${unreadable === 1 ? "quotation" : "quotations"} could not be read`, to: "/documents?status=FAILED", action: "See" },
    ordersToApprove > 0 && { id: "orders", icon: FileText, text: `${ordersToApprove} purchase ${ordersToApprove === 1 ? "order is" : "orders are"} waiting for your approval`, to: "/purchase-orders", action: "Open" },
    draftEmails > 0 && { id: "emails", icon: Mail, text: `${draftEmails} ${draftEmails === 1 ? "email is" : "emails are"} ready to send`, to: "/communications", action: "Open" },
  ].filter(Boolean) as Task[]

  const stats = [
    { label: "Open requests", value: data.procurement_requests.active.toLocaleString("en-IN"), to: "/requests" },
    { label: "Quotations received", value: data.quotations.total.toLocaleString("en-IN"), to: "/documents" },
    { label: "Suppliers", value: data.suppliers.total.toLocaleString("en-IN"), to: "/suppliers" },
    { label: "Total quoted", value: formatCurrency(Math.round(data.value.quoted_total), data.value.currency).replace(/\.00$/, ""), to: "/documents" },
  ]

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {greeting()}, {user?.name?.split(" ")[0] ?? "there"}
          </h1>
          <p className="text-muted-foreground">Here is what needs you today.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild>
            <Link to="/documents">
              <Upload /> Upload quotation
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/requests">
              <Plus /> New purchase request
            </Link>
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle>Needs your attention</CardTitle>
        </CardHeader>
        <CardContent>
          {tasks.length === 0 ? (
            <p className="flex items-center gap-2 text-muted-foreground">
              <CheckCircle2 className="h-5 w-5 text-success" /> You are all caught up. Nothing is waiting for you.
            </p>
          ) : (
            <ul className="divide-y">
              {tasks.map(({ id, icon: Icon, text, to, action }) => (
                <li key={id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                  <Icon className="h-5 w-5 shrink-0 text-warning" />
                  <span className="flex-1">{text}</span>
                  <Button asChild size="sm" variant="outline">
                    <Link to={to}>
                      {action} <ArrowRight />
                    </Link>
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {stats.map((stat) => (
          <Link key={stat.label} to={stat.to} className="rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <Card className="h-full transition-colors hover:bg-accent/40">
              <CardContent className="p-5">
                <p className="text-sm text-muted-foreground">{stat.label}</p>
                <p className="mt-1 text-2xl font-semibold tabular tracking-tight sm:text-3xl">{stat.value}</p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
          <CardTitle>Latest quotations</CardTitle>
          <Button asChild variant="ghost" size="sm">
            <Link to="/documents">
              See all <ArrowRight />
            </Link>
          </Button>
        </CardHeader>
        <CardContent>
          {data.recent_activity.length === 0 ? (
            <EmptyState icon={ClipboardList} title="No quotations yet" description="Upload your first quotation to get started." />
          ) : (
            <ul className="divide-y">
              {data.recent_activity.slice(0, 6).map((item) => (
                <li key={item.quotation_id}>
                  <Link
                    to={`/documents/${item.quotation_id}`}
                    className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3 hover:bg-accent/40 sm:flex-nowrap"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{item.supplier_name ?? item.filename ?? "Quotation"}</p>
                      <p className="text-sm text-muted-foreground">{relativeTime(item.created_at)}</p>
                    </div>
                    {item.total_amount != null && <span className="tabular font-medium">{formatCurrency(item.total_amount, data.value.currency)}</span>}
                    <StatusBadge status={item.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
