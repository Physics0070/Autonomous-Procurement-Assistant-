import { Link } from "react-router-dom"
import {
  Area,
  AreaChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  AlertTriangle,
  Building2,
  ClipboardList,
  FileStack,
  IndianRupee,
  Loader2,
} from "lucide-react"
import { PageHeader } from "@/components/layout/AppShell"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { StatusBadge } from "@/components/ui/badge"
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/feedback"
import { useDashboard } from "@/hooks/queries"
import { formatCompactCurrency, formatCurrency, relativeTime } from "@/lib/utils"

const STATUS_COLORS: Record<string, string> = {
  COMPLETED: "hsl(var(--success))",
  REQUIRES_REVIEW: "hsl(var(--warning))",
  FAILED: "hsl(var(--destructive))",
  QUEUED: "hsl(var(--muted-foreground))",
  UPLOADED: "hsl(var(--muted-foreground))",
  EXTRACTING: "hsl(var(--primary))",
  AI_EXTRACTING: "hsl(var(--primary))",
  NORMALIZING: "hsl(var(--primary))",
}

const STATUS_LABELS: Record<string, string> = {
  COMPLETED: "Completed",
  REQUIRES_REVIEW: "Needs review",
  FAILED: "Failed",
  QUEUED: "Queued",
  UPLOADED: "Uploaded",
  EXTRACTING: "Extracting",
  AI_EXTRACTING: "Reading data",
  NORMALIZING: "Normalizing",
}

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  tone = "default",
  to,
}: {
  label: string
  value: string | number
  sub?: string
  icon: React.ComponentType<{ className?: string }>
  tone?: "default" | "warning" | "success"
  to?: string
}) {
  const toneClass = {
    default: "bg-primary/10 text-primary",
    warning: "bg-warning/12 text-warning",
    success: "bg-success/12 text-success",
  }[tone]

  const body = (
    <Card className="transition-shadow hover:shadow-md">
      <CardContent className="flex items-start justify-between gap-3 p-5">
        <div className="min-w-0 space-y-1">
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="text-2xl font-semibold tabular tracking-tight">{value}</p>
          {sub && <p className="truncate text-xs text-muted-foreground">{sub}</p>}
        </div>
        <div className={`rounded-lg p-2.5 ${toneClass}`}>
          <Icon className="h-4 w-4" />
        </div>
      </CardContent>
    </Card>
  )

  return to ? <Link to={to}>{body}</Link> : body
}

export function DashboardPage() {
  const { data, isLoading, error, refetch } = useDashboard()

  if (isLoading) return <LoadingState label="Loading dashboard…" />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  if (!data) return null

  const statusData = Object.entries(data.quotations.by_status)
    .filter(([, count]) => count > 0)
    .map(([status, count]) => ({
      name: STATUS_LABELS[status] ?? status,
      value: count,
      color: STATUS_COLORS[status] ?? "hsl(var(--muted-foreground))",
    }))

  const hasTrend = data.trend.some((point) => point.quotations > 0)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Live figures from your organization's procurement data."
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Active requests"
          value={data.procurement_requests.active}
          sub={`${data.procurement_requests.total} total`}
          icon={ClipboardList}
          to="/requests"
        />
        <StatCard
          label="Quotations"
          value={data.quotations.total}
          sub={`${data.quotations.processed} processed · ${data.quotations.in_progress} in progress`}
          icon={FileStack}
          to="/documents"
        />
        <StatCard
          label="Needs review"
          value={data.quotations.requires_review}
          sub={data.quotations.failed > 0 ? `${data.quotations.failed} failed` : "No failures"}
          icon={AlertTriangle}
          tone={data.quotations.requires_review > 0 ? "warning" : "default"}
          to="/documents?status=REQUIRES_REVIEW"
        />
        <StatCard
          label="Suppliers"
          value={data.suppliers.total}
          sub={`${formatCompactCurrency(data.value.quoted_total, data.value.currency)} quoted`}
          icon={Building2}
          to="/suppliers"
        />
      </div>

      {data.queue.depth > 0 || data.queue.in_flight > 0 ? (
        <Card className="border-primary/25 bg-primary/5">
          <CardContent className="flex items-center gap-3 p-4 text-sm">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            <span>
              Processing {data.queue.in_flight} document{data.queue.in_flight === 1 ? "" : "s"}
              {data.queue.depth > 0 && `, ${data.queue.depth} queued`}. This page updates automatically.
            </span>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Quotations received</CardTitle>
            <p className="text-sm text-muted-foreground">Last 14 days</p>
          </CardHeader>
          <CardContent>
            {hasTrend ? (
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={data.trend} margin={{ top: 4, right: 8, left: -24, bottom: 0 }}>
                  <defs>
                    <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.28} />
                      <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <XAxis
                    dataKey="date"
                    tickFormatter={(value: string) => value.slice(5)}
                    tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    allowDecimals={false}
                    tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                    axisLine={false}
                    tickLine={false}
                    width={40}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "hsl(var(--card))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="quotations"
                    stroke="hsl(var(--primary))"
                    strokeWidth={2}
                    fill="url(#trendFill)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-[220px] items-center justify-center text-sm text-muted-foreground">
                No quotations received in the last 14 days.
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Processing status</CardTitle>
            <p className="text-sm text-muted-foreground">All quotations</p>
          </CardHeader>
          <CardContent>
            {statusData.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={160}>
                  <PieChart>
                    <Pie
                      data={statusData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={45}
                      outerRadius={72}
                      paddingAngle={2}
                      stroke="none"
                    >
                      {statusData.map((entry) => (
                        <Cell key={entry.name} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        background: "hsl(var(--card))",
                        border: "1px solid hsl(var(--border))",
                        borderRadius: 8,
                        fontSize: 12,
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <ul className="mt-3 space-y-1.5">
                  {statusData.map((entry) => (
                    <li key={entry.name} className="flex items-center gap-2 text-sm">
                      <span className="h-2 w-2 rounded-full" style={{ background: entry.color }} />
                      <span className="flex-1 text-muted-foreground">{entry.name}</span>
                      <span className="tabular font-medium">{entry.value}</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <div className="flex h-[160px] items-center justify-center text-sm text-muted-foreground">
                No quotations yet.
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recent activity</CardTitle>
        </CardHeader>
        <CardContent>
          {data.recent_activity.length === 0 ? (
            <EmptyState
              icon={FileStack}
              title="Nothing here yet"
              description="Upload a supplier quotation to see it move through the pipeline."
            />
          ) : (
            <ul className="divide-y">
              {data.recent_activity.map((row) => (
                <li key={row.quotation_id}>
                  <Link
                    to={`/documents/${row.quotation_id}`}
                    className="-mx-2 flex items-center gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-accent"
                  >
                    <div className="rounded-md bg-muted p-2">
                      <FileStack className="h-3.5 w-3.5 text-muted-foreground" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{row.filename ?? "Untitled document"}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {row.supplier_name ?? "Supplier not identified"} · {relativeTime(row.created_at)}
                      </p>
                    </div>
                    {row.total_amount != null && (
                      <span className="hidden tabular text-sm sm:inline">
                        {formatCurrency(row.total_amount)}
                      </span>
                    )}
                    <StatusBadge status={row.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <IndianRupee className="h-3 w-3" />
        Every figure above is a live count or aggregate from the database — nothing is simulated.
      </p>
    </div>
  )
}
