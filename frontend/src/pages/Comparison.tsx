import * as React from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { ArrowLeft, BarChart3, RefreshCw, Trophy } from "lucide-react"
import { PageHeader } from "@/components/layout/AppShell"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Alert, EmptyState, ErrorState, LoadingState, Spinner, ValueOrMissing } from "@/components/ui/feedback"
import { useComparison, useComputeComparison, useRequests } from "@/hooks/queries"
import { useCommunicationActions, usePurchaseOrderActions, useRunSupervisor } from "@/hooks/automation"
import { AgentRuns } from "@/components/AgentRuns"
import { cn, formatCurrency } from "@/lib/utils"
import type { SupplierScore } from "@/types"

const TRY_AGAIN = "We could not do this right now. Please try again in a minute."

function rating(supplier: SupplierScore): { label: string; variant: "success" | "warning" | "destructive" | "muted" } {
  const score = supplier.reliability_score
  if (score == null) return { label: "Not rated", variant: "muted" }
  if (score >= 0.75) return { label: "Good", variant: "success" }
  if (score >= 0.45) return { label: "OK", variant: "warning" }
  return { label: "Risky", variant: "destructive" }
}

const price = (s: SupplierScore) => s.landed_cost ?? s.total_cost

function paymentText(s: SupplierScore): string | null {
  if (s.payment_days == null) return null
  return s.payment_days === 0 ? "Pay in advance" : `${s.payment_days} days to pay`
}

/** Plain reasons the top supplier was picked, worked out from the numbers. */
function reasonsFor(top: SupplierScore, all: SupplierScore[]): string[] {
  const out: string[] = []
  const prices = all.map(price).filter((v): v is number => v != null)
  const topPrice = price(top)
  if (all.length > 1 && topPrice != null && topPrice === Math.min(...prices)) out.push("Lowest price")
  const days = all.map((s) => s.delivery_days).filter((v): v is number => v != null)
  if (all.length > 1 && top.delivery_days != null && top.delivery_days === Math.min(...days)) out.push("Delivers fastest")
  const pay = all.map((s) => s.payment_days).filter((v): v is number => v != null)
  if (all.length > 1 && top.payment_days != null && top.payment_days > 0 && top.payment_days === Math.max(...pay)) {
    out.push("Most time to pay")
  }
  if (top.reliability_score != null && top.reliability_score >= 0.75) out.push("Reliable supplier")
  if (top.requested_items > 0 && top.matched_items === top.requested_items) out.push("Quotes every item you need")
  return out.slice(0, 3)
}

/** Compare prices landing page: pick a request. */
export function ComparisonIndexPage() {
  const { data, isLoading, error, refetch } = useRequests()
  const navigate = useNavigate()

  if (isLoading) return <LoadingState />
  if (error) return <ErrorState error={error} onRetry={refetch} />

  const withQuotations = data?.items.filter((request) => request.quotation_count > 0) ?? []

  return (
    <div className="space-y-6">
      <PageHeader title="Compare prices" />

      {withQuotations.length === 0 ? (
        <EmptyState
          icon={BarChart3}
          title="Nothing to compare yet. Upload a quotation first."
          action={
            <Button asChild>
              <Link to="/requests">Go to purchase requests</Link>
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {withQuotations.map((request) => (
            <Card
              key={request.id}
              className="cursor-pointer transition-shadow hover:shadow-sm"
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

export function ComparisonPage() {
  const { requestId } = useParams<{ requestId: string }>()
  const { data, isLoading, error, refetch } = useComparison(requestId)
  const compute = useComputeComparison(requestId ?? "")
  const navigate = useNavigate()
  const { award } = usePurchaseOrderActions()
  const { draftNegotiation } = useCommunicationActions()
  const sourcing = useRunSupervisor()
  const [actionError, setActionError] = React.useState<string | null>(null)
  const act = (promise: Promise<unknown>, to: string) =>
    promise.then(() => navigate(to)).catch(() => setActionError(TRY_AGAIN))

  if (isLoading) return <LoadingState label="Comparing prices…" />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  if (!data) return null

  const suppliers = data.suppliers
  const top = suppliers[0]
  const reasons = top ? reasonsFor(top, suppliers) : []
  const bullets =
    reasons.length > 0 ? reasons : data.ai_explanation.available ? data.ai_explanation.reasoning.slice(0, 3) : []
  const topPrice = top ? price(top) : null

  const chartData = suppliers.map((supplier) => ({
    name: supplier.supplier_name.length > 18 ? `${supplier.supplier_name.slice(0, 17)}…` : supplier.supplier_name,
    price: price(supplier) ?? 0,
  }))

  return (
    <div className="space-y-6">
      <Link
        to="/comparison"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Compare prices
      </Link>

      <PageHeader
        title={data.procurement_request_title ?? "Compare prices"}
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => sourcing.mutateAsync(requestId ?? "").catch(() => setActionError(TRY_AGAIN))}
              disabled={sourcing.isPending || suppliers.length === 0}
            >
              {sourcing.isPending && <Spinner />}
              Get advice
            </Button>
            <Button variant="outline" onClick={() => compute.mutate({})} disabled={compute.isPending}>
              {compute.isPending ? <Spinner /> : <RefreshCw className="h-4 w-4" />}
              Refresh
            </Button>
          </>
        }
      />
      {actionError && <Alert tone="error">{actionError}</Alert>}
      {sourcing.data?.status === "awaiting_approval" && (
        <Alert tone="success" title="Waiting for you">
          {sourcing.data.output?.pending?.waiting_for === "the negotiation draft" ? (
            <>
              A message to {sourcing.data.output?.recommended_supplier_name} is ready on the{" "}
              <Link to="/communications" className="text-primary hover:underline">Emails</Link> page.
            </>
          ) : (
            <>
              {sourcing.data.output?.po_number} is ready on the{" "}
              <Link to="/purchase-orders" className="text-primary hover:underline">Purchase orders</Link> page.
            </>
          )}{" "}
          Approve it, then continue in Activity below.
        </Alert>
      )}

      {suppliers.length === 0 ? (
        <EmptyState
          icon={BarChart3}
          title="No quotations to compare yet. Check your quotations."
          action={
            <Button asChild variant="outline">
              <Link to="/documents">View quotations</Link>
            </Button>
          }
        />
      ) : (
        <>
          {top && (
            <Card className="border-success/30 bg-success/5">
              <CardContent className="flex flex-wrap items-center gap-4 p-5">
                <div className="rounded-full bg-success/15 p-2.5">
                  <Trophy className="h-5 w-5 text-success" />
                </div>
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="text-lg font-semibold">
                    Best choice: {top.supplier_name}
                    {topPrice != null && ` at ${formatCurrency(topPrice, top.currency)}`}
                    {top.delivery_days != null && `, delivery in ${top.delivery_days} days`}
                  </p>
                  {bullets.length > 0 && (
                    <ul className="list-inside list-disc text-sm text-muted-foreground">
                      {bullets.map((line, index) => (
                        <li key={index}>{line}</li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" disabled={draftNegotiation.isPending}
                          onClick={() => act(draftNegotiation.mutateAsync({ requestId: requestId ?? "", quotationId: top.quotation_id }), "/communications")}>
                    Negotiate
                  </Button>
                  <Button disabled={award.isPending}
                          onClick={() => act(award.mutateAsync({ requestId: requestId ?? "", quotationId: top.quotation_id }), "/purchase-orders")}>
                    Award
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-12">Rank</TableHead>
                    <TableHead>Supplier</TableHead>
                    <TableHead className="text-right">Total price</TableHead>
                    <TableHead className="text-right">Delivery</TableHead>
                    <TableHead>Payment</TableHead>
                    <TableHead>Rating</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {suppliers.map((supplier) => {
                    const rate = rating(supplier)
                    const pay = paymentText(supplier)
                    const total = price(supplier)
                    return (
                      <TableRow key={supplier.quotation_id} className={cn(supplier.rank === 1 && "bg-success/5")}>
                        <TableCell className="tabular font-medium">{supplier.rank}</TableCell>
                        <TableCell className="font-medium">{supplier.supplier_name}</TableCell>
                        <TableCell className="tabular text-right">
                          {total != null ? (
                            formatCurrency(total, supplier.currency)
                          ) : (
                            <ValueOrMissing value={null} missingLabel="Not given" />
                          )}
                        </TableCell>
                        <TableCell className="tabular text-right">
                          {supplier.delivery_days != null ? (
                            `${supplier.delivery_days} days`
                          ) : (
                            <ValueOrMissing value={null} missingLabel="Not given" />
                          )}
                        </TableCell>
                        <TableCell className="text-sm">
                          {pay ?? <ValueOrMissing value={null} missingLabel="Not given" />}
                        </TableCell>
                        <TableCell>
                          <Badge variant={rate.variant}>{rate.label}</Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-1">
                            <Button size="sm" variant="ghost" disabled={draftNegotiation.isPending}
                                    onClick={() => act(draftNegotiation.mutateAsync({ requestId: requestId ?? "", quotationId: supplier.quotation_id }), "/communications")}>
                              Negotiate
                            </Button>
                            <Button size="sm" variant={supplier.rank === 1 ? "default" : "outline"} disabled={award.isPending}
                                    onClick={() => act(award.mutateAsync({ requestId: requestId ?? "", quotationId: supplier.quotation_id }), "/purchase-orders")}>
                              Award
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {suppliers.length > 1 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Total price by supplier</CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} interval={0} />
                    <YAxis tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} />
                    <Tooltip
                      formatter={(value) => formatCurrency(Number(value), top?.currency ?? "INR")}
                      contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 14 }}
                    />
                    <Bar dataKey="price" radius={[4, 4, 0, 0]}>
                      {chartData.map((_, index) => (
                        <Cell key={index} fill={index === 0 ? "hsl(var(--success))" : "hsl(var(--muted-foreground))"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

          {data.excluded.length > 0 && (
            <p className="text-sm text-muted-foreground">
              Not compared: {data.excluded.map((row) => row.supplier_name ?? "Unknown supplier").join(", ")}.
            </p>
          )}
        </>
      )}
      <AgentRuns filters={{ procurement_request_id: requestId }} title="Activity" />
    </div>
  )
}
