import * as React from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  ArrowLeft,
  BarChart3,
  Calculator,
  RefreshCw,
  Sparkles,
  Trophy,
} from "lucide-react"
import { PageHeader } from "@/components/layout/AppShell"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Select } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  Alert,
  EmptyState,
  ErrorState,
  LoadingState,
  ScoreBar,
  Spinner,
  ValueOrMissing,
} from "@/components/ui/feedback"
import { useComparison, useComputeComparison, useRequests } from "@/hooks/queries"
import { cn, formatCurrency, formatDateTime, percent } from "@/lib/utils"
import type { SupplierScore } from "@/types"

const CRITERION_LABELS: Record<string, string> = {
  price: "Price",
  delivery: "Delivery",
  payment: "Payment terms",
  reliability: "Reliability",
  other: "Completeness",
}

const RANK_COLORS = [
  "hsl(var(--success))",
  "hsl(var(--primary))",
  "hsl(var(--muted-foreground))",
  "hsl(var(--muted-foreground))",
  "hsl(var(--muted-foreground))",
]

/** Comparison landing page: pick a request. */
export function ComparisonIndexPage() {
  const { data, isLoading, error, refetch } = useRequests()
  const navigate = useNavigate()

  if (isLoading) return <LoadingState />
  if (error) return <ErrorState error={error} onRetry={refetch} />

  const withQuotations = data?.items.filter((request) => request.quotation_count > 0) ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title="Supplier comparison"
        description="Rank suppliers for a procurement request using deterministic, auditable scoring."
      />

      {withQuotations.length === 0 ? (
        <EmptyState
          icon={BarChart3}
          title="Nothing to compare yet"
          description="A procurement request needs at least one processed quotation before suppliers can be compared."
          action={
            <Button asChild>
              <Link to="/requests">Go to procurement requests</Link>
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {withQuotations.map((request) => (
            <Card
              key={request.id}
              className="cursor-pointer transition-shadow hover:shadow-md"
              onClick={() => navigate(`/comparison/${request.id}`)}
            >
              <CardHeader>
                <CardTitle className="text-base">{request.title}</CardTitle>
                <p className="text-sm text-muted-foreground">
                  {request.quotation_count} quotation{request.quotation_count === 1 ? "" : "s"} ·{" "}
                  {request.items.length} item{request.items.length === 1 ? "" : "s"}
                </p>
              </CardHeader>
              <CardContent>
                <Button variant="outline" size="sm" className="w-full">
                  <BarChart3 className="h-3.5 w-3.5" />
                  Compare suppliers
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

function ScoreCell({ score }: { score: number }) {
  const tone = score >= 0.75 ? "success" : score >= 0.45 ? "warning" : "destructive"
  return (
    <div className="flex items-center gap-2">
      <ScoreBar value={score} tone={tone} className="w-14" />
      <span className="tabular text-xs">{score.toFixed(2)}</span>
    </div>
  )
}

export function ComparisonPage() {
  const { requestId } = useParams<{ requestId: string }>()
  const { data, isLoading, error, refetch } = useComparison(requestId)
  const compute = useComputeComparison(requestId ?? "")
  const [selected, setSelected] = React.useState<string | null>(null)

  if (isLoading) return <LoadingState label="Computing comparison…" />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  if (!data) return null

  const suppliers = data.suppliers
  const top = suppliers[0]
  const detail = selected ? suppliers.find((s) => s.quotation_id === selected) : null

  const chartData = suppliers.map((supplier) => ({
    name: supplier.supplier_name.length > 18
      ? `${supplier.supplier_name.slice(0, 17)}…`
      : supplier.supplier_name,
    score: supplier.overall_score,
    cost: supplier.landed_cost ?? 0,
  }))

  const radarData = Object.keys(CRITERION_LABELS).map((criterion) => {
    const row: Record<string, number | string> = { criterion: CRITERION_LABELS[criterion] }
    suppliers.slice(0, 3).forEach((supplier) => {
      const found = supplier.criteria.find((c) => c.criterion === criterion)
      row[supplier.supplier_name.slice(0, 14)] = found?.score ?? 0
    })
    return row
  })

  return (
    <div className="space-y-6">
      <Link
        to="/comparison"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        All comparisons
      </Link>

      <PageHeader
        title={data.procurement_request_title ?? "Supplier comparison"}
        description={`Computed ${formatDateTime(data.computed_at)} · ${data.method.replace(/_/g, " ")}`}
        actions={
          <Button
            variant="outline"
            onClick={() => compute.mutate({})}
            disabled={compute.isPending}
          >
            {compute.isPending ? <Spinner /> : <RefreshCw className="h-4 w-4" />}
            Recompute
          </Button>
        }
      />

      {suppliers.length === 0 ? (
        <EmptyState
          icon={BarChart3}
          title="No comparable quotations"
          description="Quotations must finish processing before they can be scored. Check the Documents page."
          action={
            <Button asChild variant="outline">
              <Link to="/documents">View documents</Link>
            </Button>
          }
        />
      ) : (
        <>
          {data.warnings.length > 0 && (
            <Alert tone="warning" title="Before you decide">
              <ul className="list-inside list-disc space-y-1">
                {data.warnings.map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
              </ul>
            </Alert>
          )}

          {/* Recommendation */}
          {top && (
            <Card className="border-success/30 bg-success/5">
              <CardContent className="flex flex-wrap items-center gap-4 p-5">
                <div className="rounded-full bg-success/15 p-2.5">
                  <Trophy className="h-5 w-5 text-success" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Highest ranked
                  </p>
                  <p className="text-lg font-semibold">{top.supplier_name}</p>
                  <p className="text-sm text-muted-foreground">
                    Weighted score {top.overall_score.toFixed(3)} ·{" "}
                    {top.landed_cost != null
                      ? formatCurrency(top.landed_cost, top.currency)
                      : "total not stated"}
                    {top.delivery_days != null && ` · ${top.delivery_days} day delivery`}
                  </p>
                </div>
                <Button asChild variant="outline">
                  <Link to={`/documents/${top.quotation_id}`}>View quotation</Link>
                </Button>
              </CardContent>
            </Card>
          )}

          {/* Weights */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Calculator className="h-4 w-4" />
                Scoring weights
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                Configured server-side and normalized to sum to 100%. Every score below is computed
                from these — no model is involved in the arithmetic.
              </p>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {Object.entries(data.weights).map(([criterion, weight]) => (
                <Badge key={criterion} variant="secondary">
                  {CRITERION_LABELS[criterion] ?? criterion} · {percent(weight)}
                </Badge>
              ))}
            </CardContent>
          </Card>

          {/* Main comparison matrix */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Comparison matrix</CardTitle>
              <p className="text-sm text-muted-foreground">
                Select a supplier to see its full score breakdown.
              </p>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-12">Rank</TableHead>
                    <TableHead>Supplier</TableHead>
                    <TableHead className="text-right">Total cost</TableHead>
                    <TableHead className="text-right">Delivery</TableHead>
                    <TableHead className="text-right">Payment</TableHead>
                    <TableHead>Reliability</TableHead>
                    <TableHead className="text-right">Items quoted</TableHead>
                    <TableHead>Final score</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {suppliers.map((supplier) => (
                    <TableRow
                      key={supplier.quotation_id}
                      className={cn(
                        "cursor-pointer",
                        selected === supplier.quotation_id && "bg-accent",
                        supplier.rank === 1 && "bg-success/5",
                      )}
                      onClick={() =>
                        setSelected(selected === supplier.quotation_id ? null : supplier.quotation_id)
                      }
                    >
                      <TableCell>
                        <span
                          className={cn(
                            "inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold",
                            supplier.rank === 1
                              ? "bg-success text-success-foreground"
                              : "bg-muted text-muted-foreground",
                          )}
                        >
                          {supplier.rank}
                        </span>
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">{supplier.supplier_name}</div>
                        {supplier.missing_data.length > 0 && (
                          <div className="mt-0.5 text-xs text-warning">
                            missing: {supplier.missing_data.join(", ")}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="tabular text-right">
                        {supplier.landed_cost != null ? (
                          formatCurrency(supplier.landed_cost, supplier.currency)
                        ) : (
                          <ValueOrMissing value={null} />
                        )}
                      </TableCell>
                      <TableCell className="tabular text-right">
                        {supplier.delivery_days != null ? (
                          `${supplier.delivery_days}d`
                        ) : (
                          <ValueOrMissing value={null} />
                        )}
                      </TableCell>
                      <TableCell className="tabular text-right">
                        {supplier.payment_days != null ? (
                          supplier.payment_days === 0 ? (
                            <span className="text-warning">Advance</span>
                          ) : (
                            `${supplier.payment_days}d`
                          )
                        ) : (
                          <ValueOrMissing value={null} />
                        )}
                      </TableCell>
                      <TableCell>
                        {supplier.reliability_score != null ? (
                          <ScoreCell score={supplier.reliability_score} />
                        ) : (
                          <ValueOrMissing value={null} />
                        )}
                      </TableCell>
                      <TableCell className="tabular text-right">
                        {supplier.matched_items}/{supplier.requested_items}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <ScoreBar
                            value={supplier.overall_score}
                            tone={supplier.rank === 1 ? "success" : "primary"}
                            className="w-16"
                          />
                          <span className="tabular text-sm font-semibold">
                            {supplier.overall_score.toFixed(3)}
                          </span>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* Breakdown for the selected supplier */}
          {detail && (
            <Card className="animate-fade-in">
              <CardHeader>
                <CardTitle className="text-base">Score breakdown — {detail.supplier_name}</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Each criterion score × its weight, summed to the final score. Data completeness{" "}
                  {percent(detail.data_completeness)}.
                </p>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Criterion</TableHead>
                      <TableHead className="text-right">Measured value</TableHead>
                      <TableHead>Score</TableHead>
                      <TableHead className="text-right">Weight</TableHead>
                      <TableHead className="text-right">Contribution</TableHead>
                      <TableHead>Deductions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {detail.criteria.map((criterion) => (
                      <TableRow key={criterion.criterion}>
                        <TableCell className="font-medium">
                          {CRITERION_LABELS[criterion.criterion] ?? criterion.criterion}
                        </TableCell>
                        <TableCell className="tabular text-right text-sm">
                          {criterion.data_available && criterion.raw_value != null ? (
                            <>
                              {criterion.unit === detail.currency
                                ? formatCurrency(criterion.raw_value, detail.currency)
                                : `${criterion.raw_value} ${criterion.unit ?? ""}`}
                            </>
                          ) : (
                            <ValueOrMissing value={null} missingLabel="No data" />
                          )}
                        </TableCell>
                        <TableCell>
                          <ScoreCell score={criterion.score} />
                        </TableCell>
                        <TableCell className="tabular text-right text-sm">
                          {percent(criterion.weight)}
                        </TableCell>
                        <TableCell className="tabular text-right text-sm font-medium">
                          {criterion.weighted_score.toFixed(3)}
                        </TableCell>
                        <TableCell className="max-w-xs text-xs text-muted-foreground">
                          {criterion.deductions.length > 0 ? criterion.deductions.join(" ") : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                    <TableRow className="bg-muted/50 font-semibold">
                      <TableCell colSpan={4}>Final weighted score</TableCell>
                      <TableCell className="tabular text-right">
                        {detail.overall_score.toFixed(3)}
                      </TableCell>
                      <TableCell />
                    </TableRow>
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {/* Charts */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Weighted score by supplier</CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={chartData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                    <XAxis
                      dataKey="name"
                      tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                      axisLine={false}
                      tickLine={false}
                      interval={0}
                      angle={-15}
                      textAnchor="end"
                      height={50}
                    />
                    <YAxis
                      domain={[0, 1]}
                      tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <Tooltip
                      contentStyle={{
                        background: "hsl(var(--card))",
                        border: "1px solid hsl(var(--border))",
                        borderRadius: 8,
                        fontSize: 12,
                      }}
                    />
                    <Bar dataKey="score" radius={[4, 4, 0, 0]}>
                      {chartData.map((_, index) => (
                        <Cell key={index} fill={RANK_COLORS[Math.min(index, RANK_COLORS.length - 1)]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Criterion profile</CardTitle>
                <p className="text-sm text-muted-foreground">Top 3 suppliers</p>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={240}>
                  <RadarChart data={radarData}>
                    <PolarGrid stroke="hsl(var(--border))" />
                    <PolarAngleAxis
                      dataKey="criterion"
                      tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                    />
                    <PolarRadiusAxis domain={[0, 1]} tick={false} axisLine={false} />
                    {suppliers.slice(0, 3).map((supplier, index) => (
                      <Radar
                        key={supplier.quotation_id}
                        name={supplier.supplier_name.slice(0, 14)}
                        dataKey={supplier.supplier_name.slice(0, 14)}
                        stroke={RANK_COLORS[index]}
                        fill={RANK_COLORS[index]}
                        fillOpacity={0.15}
                      />
                    ))}
                    <Tooltip
                      contentStyle={{
                        background: "hsl(var(--card))",
                        border: "1px solid hsl(var(--border))",
                        borderRadius: 8,
                        fontSize: 12,
                      }}
                    />
                  </RadarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>

          {/* AI explanation - visually separated from calculated data */}
          <Card className="border-dashed">
            <CardHeader>
              <CardTitle className="flex flex-wrap items-center gap-2 text-base">
                <Sparkles className="h-4 w-4 text-primary" />
                Explanation
                <Badge variant={data.ai_explanation.provider === "deterministic" ? "secondary" : "default"}>
                  {data.ai_explanation.provider === "deterministic"
                    ? "Computed summary — not AI"
                    : `AI generated · ${data.ai_explanation.provider}`}
                </Badge>
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                Narrative only. The ranking above was calculated before this was written, and nothing
                here can change it.
              </p>
            </CardHeader>
            <CardContent className="space-y-4">
              {data.ai_explanation.unavailable_reason && (
                <Alert tone="info" title="Why this is not AI-written">
                  <p>{data.ai_explanation.unavailable_reason}</p>
                </Alert>
              )}

              {data.ai_explanation.summary && (
                <p className="text-sm leading-relaxed">{data.ai_explanation.summary}</p>
              )}

              {data.ai_explanation.reasoning.length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Reasoning
                  </p>
                  <ul className="space-y-1.5 text-sm">
                    {data.ai_explanation.reasoning.map((line, index) => (
                      <li key={index} className="flex gap-2">
                        <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary" />
                        {line}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {data.ai_explanation.risks.length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Risks and caveats
                  </p>
                  <ul className="space-y-1.5 text-sm">
                    {data.ai_explanation.risks.map((risk, index) => (
                      <li key={index} className="flex gap-2">
                        <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-warning" />
                        {risk}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>

          {data.excluded.length > 0 && (
            <Alert tone="info" title={`${data.excluded.length} quotation(s) excluded`}>
              <ul className="list-inside list-disc space-y-1">
                {data.excluded.map((row, index) => (
                  <li key={index}>
                    {row.supplier_name ?? "Unknown supplier"} — {row.reason}
                  </li>
                ))}
              </ul>
            </Alert>
          )}
        </>
      )}
    </div>
  )
}
